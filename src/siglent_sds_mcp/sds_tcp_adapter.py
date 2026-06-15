from __future__ import annotations

import base64
import csv
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .artifacts import default_artifact_paths, ensure_parent, write_json
from .tcp_transport import RawTcpTransport
from .uart_analyzer import analyze_uart_csv

# SDS800X HD 系列 WF? DAT2 返回 8bit 字节编码，垂直满屏 8 格。
# 优先从 WAVEDESC 二进制描述符自适应推导每码电压，无需硬编码型号特定常量。
# 仅当描述符不可用时，回退到 SDS824X HD 实测值 CODES_PER_DIV=30。
CODES_PER_DIV = 30

# ---------------------------------------------------------------------------
# WAVEDESC 二进制描述符字段偏移（Siglent SDS824X HD 实测，little-endian）
#
# 关键字段布局（相对 b"WAVEDESC" 签名起点）：
#   [116] WAVE_ARRAY_COUNT  int32   — 采样点数
#   [156] VERTICAL_GAIN     float32 — V/div（即 VDIV，注意：不是 V/code）
#   [160] VERTICAL_OFFSET   float32 — 垂直偏移 (V)，等于面板 OFST
#   [164] MAX_VALUE         float32 — ADC 满幅码值 = codes_per_div × 256
#                                     SDS824X HD 实测 7680 = 30 × 256
#   [176] HORIZ_INTERVAL    float32 — 水平采样间隔 (s/sample)
#   [180] HORIZ_OFFSET      float64 — 触发时刻相对首采样点偏移 (s)，= 面板 TRDL
#
# 电压解码公式（WAVEDESC 自适应推导）：
#   codes_per_div  = MAX_VALUE / 256
#   gain_v_per_code = VERTICAL_GAIN / codes_per_div      (= VDIV / CPD)
#   voltage         = code × gain_v_per_code - VERTICAL_OFFSET
# ---------------------------------------------------------------------------
_WAVEDESC_SIGNATURE = b"WAVEDESC"   # 描述符起始标记，位于 offset 0
_OFF_WAVE_ARRAY_COUNT: int = 116    # int32   — 采样点数
_OFF_VERTICAL_GAIN: int    = 156    # float32 — V/div（非 V/code）
_OFF_VERTICAL_OFFSET: int  = 160    # float32 — 垂直偏移 (V)
_OFF_MAX_VALUE: int        = 164    # float32 — ADC 满幅码值
_OFF_HORIZ_INTERVAL: int   = 176    # float32 — 水平采样间隔 (s/sample)
_OFF_HORIZ_OFFSET: int     = 180    # float64 — 触发偏移 (s)，= TRDL


@dataclass(slots=True)
class WaveDescriptor:
    """从 WAVEDESC 二进制块解析出的关键定标参数。"""

    vertical_gain_vdiv: float   # V/div（WAVEDESC VERTICAL_GAIN 字段原始值）
    max_value: float            # ADC 满幅码值（= codes_per_div × 256）
    codes_per_div: float        # = max_value / 256，如 SDS824X HD 为 30.0
    gain_v_per_code: float      # 每码电压 = VDIV / codes_per_div (V/code)
    vertical_offset: float      # V（解码：v = code × gain_v_per_code - offset）
    horiz_interval: float       # s/sample
    horiz_offset: float         # s，= TRDL
    wave_array_count: int       # 描述符中记录的点数
    raw_bytes: int              # 描述符总字节数（诊断用）
    source: str                 # "wavedesc" | "fallback"


def _parse_wavedesc(data: bytes) -> WaveDescriptor | None:
    """解析 WAVEDESC 二进制描述符，失败返回 None。

    SIGLENT SDS 返回的描述符数据开头可能附带 ASCII 前缀（如 "C1:WF DESC,"），
    本函数自动搜索 b"WAVEDESC" 标记并从其偏移处解析字段。
    """
    import math

    idx = data.find(_WAVEDESC_SIGNATURE)
    if idx < 0:
        return None
    desc = data[idx:]
    min_len = _OFF_HORIZ_OFFSET + 8  # float64 需要 8 字节
    if len(desc) < min_len:
        return None
    try:
        (wave_array_count,) = struct.unpack_from("<i", desc, _OFF_WAVE_ARRAY_COUNT)
        (vertical_gain,)    = struct.unpack_from("<f", desc, _OFF_VERTICAL_GAIN)
        (vertical_offset,)  = struct.unpack_from("<f", desc, _OFF_VERTICAL_OFFSET)
        (max_value,)        = struct.unpack_from("<f", desc, _OFF_MAX_VALUE)
        (horiz_interval,)   = struct.unpack_from("<f", desc, _OFF_HORIZ_INTERVAL)
        (horiz_offset,)     = struct.unpack_from("<d", desc, _OFF_HORIZ_OFFSET)
    except struct.error:
        return None

    # 合理性检验
    if not math.isfinite(vertical_gain) or vertical_gain == 0.0:
        return None
    if not math.isfinite(max_value) or max_value <= 0.0:
        return None

    codes_per_div = max_value / 256.0
    gain_v_per_code = float(vertical_gain) / codes_per_div

    return WaveDescriptor(
        vertical_gain_vdiv=float(vertical_gain),
        max_value=float(max_value),
        codes_per_div=codes_per_div,
        gain_v_per_code=gain_v_per_code,
        vertical_offset=float(vertical_offset),
        horiz_interval=float(horiz_interval),
        horiz_offset=float(horiz_offset),
        wave_array_count=int(wave_array_count),
        raw_bytes=len(desc),
        source="wavedesc",
    )

Channel = Literal["C1", "C2", "C3", "C4"]
MeasureParameter = Literal[
    "PKPK",
    "MAX",
    "MIN",
    "AMPL",
    "TOP",
    "BASE",
    "CMEAN",
    "MEAN",
    "RMS",
    "CRMS",
    "OVSN",
    "FPRE",
    "OVSP",
    "RPRE",
    "PER",
    "FREQ",
    "PWID",
    "NWID",
    "RISE",
    "FALL",
    "WID",
    "DUTY",
    "NDUTY",
    "ALL",
]


# ---------------------------------------------------------------------------
# 自动量程（auto_setup）档位表 —— 配置驱动，避免硬编码魔术数字。
# 取值参照 SDS800X HD 面板可选档位（1-2-5 序列）。
# ---------------------------------------------------------------------------
_VDIV_STEPS_V: tuple[float, ...] = (
    5e-3, 10e-3, 20e-3, 50e-3, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0,
)
_TDIV_STEPS_S: tuple[float, ...] = (
    1e-9, 2e-9, 5e-9, 10e-9, 20e-9, 50e-9,
    100e-9, 200e-9, 500e-9,
    1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6,
    100e-6, 200e-6, 500e-6,
    1e-3, 2e-3, 5e-3, 10e-3, 20e-3,
)
# 时基扫描序列：先中等粗到极粗（捕获慢信号），再由粗到细（捕获高频）。
# 解决高频信号在宽时基下因欠采样被测量为"直流"的问题。
_TDIV_SCAN_S: tuple[float, ...] = (
    5e-6, 50e-6, 500e-6, 5e-3, 50e-3, 1e-6, 200e-9, 50e-9, 10e-9,
)
# auto_setup 默认参数
_AUTOSET_DIVISIONS_V = 6.0    # 垂直方向期望信号占据的格数
_AUTOSET_DIVISIONS_H = 14.0   # 水平方向总格数（SDS800X HD 屏幕宽度）
_AUTOSET_SIGNAL_FRAC = 0.5    # 扫描时判定"有信号"的阈值（占 VDIV 的比例）


@dataclass(slots=True)
class WaveformResult:
    csv_path: str
    metadata_path: str
    metadata: dict[str, Any]


class SDS800XHDTcpAdapter:
    """Candidate SDS800X HD TCP/SCPI adapter.

    This adapter intentionally follows the command style used by the public
    `MagnusJohansson/siglent-sds-mcp` project because it is a working SIGLENT SDS
    MCP reference implementation. The target hardware here is SDS824X HD, so these
    commands must still be verified against the SDS800X HD Programming Guide and
    real firmware before being marked as production-safe.
    """

    def __init__(self, transport: RawTcpTransport):
        self.transport = transport

    def identify(self) -> str:
        return self.transport.query("*IDN?")

    def try_header_off(self) -> dict[str, Any]:
        try:
            self.transport.write("CHDR OFF")
            return {"ok": True, "command": "CHDR OFF"}
        except Exception as exc:  # noqa: BLE001 - compatibility probing
            return {"ok": False, "command": "CHDR OFF", "error": repr(exc)}

    def get_channel(self, channel: Channel) -> dict[str, Any]:
        ch = _channel(channel)
        result: dict[str, Any] = {"channel": ch}
        for key, command in {
            "volts_per_div": f"{ch}:VDIV?",
            "offset": f"{ch}:OFST?",
            "coupling": f"{ch}:CPL?",
            "trace": f"{ch}:TRA?",
            "probe_attenuation": f"{ch}:ATTN?",
            "unit": f"{ch}:UNIT?",
        }.items():
            result[key] = self._query_or_error(command)
        result["bandwidth_limit_all"] = self._query_or_error("BWL?")
        return result

    def configure_channel(
        self,
        channel: Channel,
        vdiv: str | None = None,
        offset: str | None = None,
        coupling: Literal["A1M", "A50", "D1M", "D50", "GND"] | None = None,
        bandwidth_limit: bool | None = None,
        trace: bool | None = None,
        probe: float | None = None,
    ) -> dict[str, Any]:
        ch = _channel(channel)
        commands: list[str] = []
        if vdiv is not None:
            commands.append(f"{ch}:VDIV {vdiv}")
        if offset is not None:
            commands.append(f"{ch}:OFST {offset}")
        if coupling is not None:
            commands.append(f"{ch}:CPL {coupling}")
        if bandwidth_limit is not None:
            commands.append(f"BWL {ch},{'ON' if bandwidth_limit else 'OFF'}")
        if trace is not None:
            commands.append(f"{ch}:TRA {'ON' if trace else 'OFF'}")
        if probe is not None:
            commands.append(f"{ch}:ATTN {probe:g}")

        for command in commands:
            self.transport.write(command)
        return {"channel": ch, "commands_sent": commands}

    def configure_acquisition(
        self,
        command: Literal["run", "stop", "single", "auto"] | None = None,
        timebase: str | None = None,
        trigger_mode: Literal["AUTO", "NORM", "SINGLE", "STOP"] | None = None,
        trigger_source: Channel | None = None,
        trigger_level: str | None = None,
        trigger_slope: Literal["POS", "NEG", "WINDOW"] | None = None,
        trigger_delay: str | None = None,
    ) -> dict[str, Any]:
        commands: list[str] = []
        if timebase is not None:
            commands.append(f"TDIV {timebase}")
        if trigger_delay is not None:
            commands.append(f"TRDL {trigger_delay}")
        if trigger_mode is not None:
            commands.append(f"TRMD {trigger_mode}")
        if trigger_level is not None:
            src = _channel(trigger_source or "C1")
            commands.append(f"{src}:TRLV {trigger_level}")
        if trigger_slope is not None:
            src = _channel(trigger_source or "C1")
            commands.append(f"{src}:TRSL {trigger_slope}")
        if command is not None:
            commands.append({"run": "ARM", "stop": "STOP", "single": "TRMD SINGLE", "auto": "TRMD AUTO"}[command])

        for cmd in commands:
            self.transport.write(cmd)
        return {"commands_sent": commands}

    def get_acquisition_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, command in {
            "acquisition_status": "SAST?",
            "sample_rate": "SARA?",
            "timebase": "TDIV?",
            "trigger_delay": "TRDL?",
            "trigger_mode": "TRMD?",
            "trigger_select": "TRSE?",
            "trigger_level_c1": "C1:TRLV?",
            "trigger_slope_c1": "C1:TRSL?",
        }.items():
            result[key] = self._query_or_error(command)
        return result

    def measure(self, channel: Channel, parameter: MeasureParameter) -> dict[str, Any]:
        ch = _channel(channel)
        self.transport.write(f"PACU {parameter},{ch}")
        time.sleep(0.2)
        value = self.transport.query(f"{ch}:PAVA? {parameter}")
        return {"channel": ch, "parameter": parameter, "value": value}

    def auto_setup(
        self,
        channel: Channel = "C1",
        *,
        target_cycles: float = 4.0,
        settle_s: float = 0.6,
        screenshot_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """自动探测信号并把波形调整到屏幕最佳显示（类似面板 Auto Setup）。

        经 SDS824X HD 真机验证的探测流程：
          1. 宽量程（1V/div, OFST=0）粗测 DC 电平与 PKPK；
          2. 时基扫描定位 AC 分量——解决高频信号在宽时基下因欠采样被
             测量为"直流"的问题（实测 62MHz 信号在 5µs/div 时 PKPK≈0，
             在 50µs/div 时 PKPK 跳到 85mV）；
          3. 在命中时基精测 FREQ/PER/PKPK/MAX/MIN；
          4. 据此选 VDIV（PKPK 占 ~6 格）、OFST（DC 居中）、
             TDIV（显示 target_cycles 个周期）、触发电平（信号中值）；
          5. 可选截图确认最终屏幕显示。

        参数:
            channel: 目标通道。
            target_cycles: 最终时基期望显示的完整周期数。
            settle_s: 每次配置变更后等待采集稳定的时间（秒）。
            screenshot_path: 若提供则在完成后截图保存到该路径。
        """
        ch = _channel(channel)
        steps: list[dict[str, Any]] = []

        def _meas(param: MeasureParameter) -> float | None:
            return _parse_meas_value(self.measure(ch, param)["value"])

        # --- Step 1: 宽量程粗测 DC 与 PKPK ---
        self.configure_channel(ch, vdiv="1V", offset="0V", coupling="D1M", trace=True)
        self.transport.write("TRDL 0S")  # 清零触发延迟，避免采集窗口偏移
        self.configure_acquisition(
            command="run", trigger_mode="AUTO",
            trigger_source=ch, trigger_level="0.0000E+00", trigger_slope="POS",
        )
        time.sleep(settle_s)
        dc_v = _meas("MEAN") or 0.0
        coarse_pkpk = _meas("PKPK") or 0.0
        steps.append({"stage": "coarse", "dc_v": dc_v, "pkpk_v": coarse_pkpk})

        # --- Step 2: 时基扫描定位 AC 分量 ---
        # 先放大 VDIV 到合适量程（DC 居中），再逐档扫描时基测 PKPK。
        probe_vdiv = _pick_vdiv(max(coarse_pkpk, 0.05))
        self.configure_channel(ch, vdiv=_fmt_sci(probe_vdiv), offset=_fmt_sci(-dc_v))
        best_tdiv: float | None = None
        scan: dict[float, float] = {}
        for tdiv in _TDIV_SCAN_S:
            self.configure_acquisition(timebase=_fmt_sci(tdiv), command="run", trigger_mode="AUTO")
            time.sleep(settle_s * 0.7)
            pk = _meas("PKPK") or 0.0
            scan[tdiv] = pk
            if pk > probe_vdiv * _AUTOSET_SIGNAL_FRAC:  # 超过设定阈值视为命中
                best_tdiv = tdiv
                break
        if best_tdiv is None:
            best_tdiv = max(scan, key=lambda k: scan[k]) if scan else 5e-6
        steps.append({
            "stage": "tdiv_scan",
            "hit_tdiv_s": best_tdiv,
            "scan": {f"{k:.2e}": v for k, v in scan.items()},
        })

        # --- Step 3: 命中时基精测 ---
        self.configure_acquisition(timebase=_fmt_sci(best_tdiv), command="run", trigger_mode="AUTO")
        time.sleep(settle_s)
        freq = _meas("FREQ")
        per = _meas("PER")
        pkpk = _meas("PKPK") or coarse_pkpk
        vmax = _meas("MAX")
        vmin = _meas("MIN")
        vmean = _meas("MEAN")
        if vmean is None:
            vmean = dc_v
        steps.append({
            "stage": "measure",
            "freq_hz": freq, "period_s": per, "pkpk_v": pkpk,
            "max_v": vmax, "min_v": vmin, "mean_v": vmean,
        })

        # --- Step 4: 计算并应用最终设置 ---
        period_s: float | None = None
        if per is not None and per > 0:
            period_s = per
        elif freq is not None and freq > 0:
            period_s = 1.0 / freq

        final_tdiv = _pick_tdiv(period_s, cycles=target_cycles) if period_s else best_tdiv
        final_vdiv = _pick_vdiv(max(pkpk, 0.01))

        # 确保记录深度足够（≥ 100 点）。窄时基下 SARA 会自动降采样，
        # 实测 SDS824X HD：5ns/div→25点，10ns→50点，20ns→100点（500MSa/s）。
        sara_val = _parse_sample_rate(self.transport.query("SARA?"))
        while True:
            est_pts = int(sara_val * final_tdiv * _AUTOSET_DIVISIONS_H)
            if est_pts >= 100:
                break
            idx = _TDIV_STEPS_S.index(final_tdiv)
            if idx + 1 >= len(_TDIV_STEPS_S):
                break
            final_tdiv = _TDIV_STEPS_S[idx + 1]
        # OFST 居中（钳位 ±6 格，避免超出有效偏移范围）
        final_ofst = max(min(-vmean, final_vdiv * 6), -final_vdiv * 6)
        # 触发电平：优先 (max+min)/2 中值，否则用均值
        trig_level = (vmax + vmin) / 2.0 if (vmax is not None and vmin is not None) else vmean

        self.configure_channel(ch, vdiv=_fmt_sci(final_vdiv), offset=_fmt_sci(final_ofst))
        self.configure_acquisition(
            timebase=_fmt_sci(final_tdiv),
            trigger_source=ch,
            trigger_level=_fmt_sci(trig_level),
            trigger_slope="POS",
            trigger_mode="AUTO",
            command="run",
        )
        time.sleep(settle_s)

        # --- Step 5: 可选截图确认屏幕显示 ---
        shot: dict[str, Any] | None = None
        if screenshot_path is not None:
            shot = self.screenshot(screenshot_path)

        signal_detected = period_s is not None and pkpk > final_vdiv * 0.2
        return {
            "channel": ch,
            "signal_detected": signal_detected,
            "final_settings": {
                "vdiv_v": final_vdiv,
                "offset_v": final_ofst,
                "tdiv_s": final_tdiv,
                "trigger_level_v": trig_level,
                "trigger_slope": "POS",
            },
            "measurements": {
                "frequency_hz": freq,
                "period_s": period_s,
                "pkpk_v": pkpk,
                "max_v": vmax,
                "min_v": vmin,
                "mean_v": vmean,
            },
            "probe_steps": steps,
            "screenshot": shot,
        }

    def screenshot(
        self,
        output_path: str | Path | None = None,
        *,
        include_base64: bool = False,
    ) -> dict[str, Any]:
        block = self.transport.query_binary("SCDP", timeout_s=30.0)
        if output_path is None:
            output_path = default_artifact_paths("screenshot")["screenshot_raw"]
        path = ensure_parent(output_path)
        path.write_bytes(block.data)
        result: dict[str, Any] = {
            "path": str(path),
            "bytes": len(block.data),
            "framing": block.framing,
            "command": "SCDP",
        }
        if block.data.startswith(b"BM"):
            result.update(_inspect_bmp(block.data))
        if include_base64:
            result["base64"] = base64.b64encode(block.data).decode("ascii")
        return result

    def get_waveform(
        self,
        channel: Channel,
        csv_path: str | Path | None = None,
        metadata_path: str | Path | None = None,
        max_points: int = 5000,
        *,
        restore_trmd: bool = True,
    ) -> WaveformResult:
        ch = _channel(channel)
        paths = default_artifact_paths(f"waveform_{ch.lower()}")
        csv_out = ensure_parent(csv_path or paths["waveform_csv"])
        metadata_out = ensure_parent(metadata_path or paths["metadata_json"])

        # --- 1. 辅助查询（用于 fallback 解码及元数据记录）---
        vdiv_raw = self.transport.query(f"{ch}:VDIV?")
        ofst_raw = self.transport.query(f"{ch}:OFST?")
        attn_raw = self.transport.query(f"{ch}:ATTN?")
        tdiv_raw = self.transport.query("TDIV?")
        sara_raw = self.transport.query("SARA?")

        vdiv = _parse_voltage(vdiv_raw)
        offset = _parse_voltage(ofst_raw)
        tdiv = _parse_time(tdiv_raw)
        sample_rate = _parse_sample_rate(sara_raw)

        # --- 2. 确保波形内存与当前 VDIV/OFST/TDIV 匹配 ---
        # 仅 STOP 可能捕获到旧设置下的波形数据（WAVEDESC 内嵌 gain 与 VDIV?
        # 不一致）。不能使用 ARM——ARM 会重置采集到"待触发"状态，在 AUTO 模式
        # 下不保证立即触发完成。正确做法：利用 AUTO 模式的自动触发，等待至少
        # 一帧完整采集后 STOP。
        prev_trmd = self.transport.query("TRMD?")
        # 确保完成至少一帧在当前设置下的采集。
        # 策略：切 SINGLE → ARM 强制触发 → 等待 sweep 时间 → STOP。
        # 避免 AUTO 模式下 ARM 使仪器进入 Ready 但未触发即被 STOP 打断（DAT2=0）。
        self.transport.write("TRMD SINGLE")
        time.sleep(0.05)
        self.transport.write("ARM")
        sweep_estimate = max(tdiv * 20.0, 0.2)  # 至少 200ms
        time.sleep(sweep_estimate)
        self.transport.write("STOP")

        # --- 3. 下载原始波形数据（必须在 DESC 之前，否则 DAT2 返回 0 字节）---
        # WFSU SP,1：SP=0 会被 SDS824X HD scope 拒绝（scope 保持 SP=1），必须设为 >=1。
        self.transport.write("WFSU SP,1,NP,0,FP,0")
        block = self.transport.query_binary(f"{ch}:WF? DAT2", timeout_s=30.0)

        # --- 4. 尝试获取 WAVEDESC 描述符（自适应解码的关键数据源）---
        # DAT2 读取不会消耗 WAVEDESC 数据，DESC 仍可正常获取。
        # SIGLENT 响应格式为：<ch>:WF DESC,#<n><len><descriptor_bytes>
        wavedesc: WaveDescriptor | None = None
        desc_error: str | None = None
        try:
            desc_block = self.transport.query_binary(f"{ch}:WF? DESC", timeout_s=10.0)
            wavedesc = _parse_wavedesc(desc_block.data)
            if wavedesc is None:
                desc_error = "parse_failed: WAVEDESC signature not found or sanity check failed"
        except Exception as exc:  # noqa: BLE001 - WAVEDESC 不可用时安全降级
            desc_error = f"query_failed: {exc!r}"
        raw = block.data
        total_points = len(raw)

        # --- 5. 电压解码 ---
        # 策略：codes_per_div 从 WAVEDESC MAX_VALUE 自适应推导（型号无关），
        # gain/offset 使用面板实时查询值（VDIV? / OFST?），避免 WAVEDESC
        # VERTICAL_GAIN/VERTICAL_OFFSET 滞后于面板设置导致的解码偏差。
        # 实测 SDS824X HD：切换 VDIV/OFST 后 WAVEDESC 缓存需额外 1~2 帧才更新。
        codes_per_div = (
            wavedesc.codes_per_div
            if wavedesc is not None and wavedesc.codes_per_div > 0
            else CODES_PER_DIV
        )
        gain_v_per_code = vdiv / codes_per_div  # 面板 VDIV（已含探头衰减）
        offset_v = offset  # 面板 OFST（已含探头衰减）
        voltages = [
            _siglent_byte_to_voltage(byte, gain_v_per_code, offset_v)
            for byte in raw
        ]
        decode_source = (
            "wavedesc_cpd__panel_vdiv_ofst"
            if wavedesc is not None
            else "fallback_codes_per_div"
        )
        gain_used = gain_v_per_code
        offset_used = offset_v

        # --- 6. 时间轴定标：优先 WAVEDESC，fallback 到 SARA/触发居中 ---
        # WAVEDESC 提供精确的 HORIZ_INTERVAL 和 HORIZ_OFFSET。
        # HORIZ_OFFSET：触发点相对于首采样点的时间偏移（s）。
        #   首点时间 = -HORIZ_OFFSET（即触发前记录长度，符号与示波器惯例一致）。
        if wavedesc is not None and wavedesc.horiz_interval > 0.0:
            time_interval = wavedesc.horiz_interval
            start_time = -wavedesc.horiz_offset
            time_source = "wavedesc"
        elif sample_rate > 0:
            # 触发居中：首点时间 = -(N/2)·dt
            time_interval = 1.0 / sample_rate
            start_time = -(total_points / 2.0) * time_interval
            time_source = "fallback_sara_centered"
        else:
            time_interval = 0.0
            start_time = -(tdiv * 14) / 2 if tdiv > 0 else 0.0
            time_source = "fallback_tdiv"

        # --- 7. min/max 包络抽样输出 ---
        # 每桶保留最小值与最大值（按真实采样时刻），避免跨步抽样丢失毛刺/峰值。
        returned_points = 0
        with csv_out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time_s", "voltage_v"])
            if max_points <= 0 or total_points <= max_points:
                for i in range(total_points):
                    writer.writerow([start_time + i * time_interval, voltages[i]])
                    returned_points += 1
            else:
                # 每桶输出最多 2 点（min/max），故桶数取 max_points/2。
                bucket = max(1, (2 * total_points + max_points - 1) // max_points)
                for base in range(0, total_points, bucket):
                    end = min(base + bucket, total_points)
                    i_min = base
                    i_max = base
                    for i in range(base, end):
                        if voltages[i] < voltages[i_min]:
                            i_min = i
                        if voltages[i] > voltages[i_max]:
                            i_max = i
                    lo, hi = (i_min, i_max) if i_min <= i_max else (i_max, i_min)
                    writer.writerow([start_time + lo * time_interval, voltages[lo]])
                    returned_points += 1
                    if hi != lo:
                        writer.writerow([start_time + hi * time_interval, voltages[hi]])
                        returned_points += 1

        # --- 8. 恢复采集状态 ---
        # 波形读取完成后恢复之前的触发模式，避免 scope 一直停在 STOP。
        if restore_trmd:
            try:
                self.transport.write(f"TRMD {prev_trmd}")
            except Exception:  # noqa: BLE001 - 尽力恢复，失败不影响波形数据
                pass

        # --- 9. 元数据 ---
        wavedesc_info: dict[str, Any] = (
            {
                "vertical_gain_vdiv": wavedesc.vertical_gain_vdiv,
                "max_value": wavedesc.max_value,
                "codes_per_div": wavedesc.codes_per_div,
                "gain_v_per_code": wavedesc.gain_v_per_code,
                "vertical_offset": wavedesc.vertical_offset,
                "horiz_interval": wavedesc.horiz_interval,
                "horiz_offset": wavedesc.horiz_offset,
                "wave_array_count": wavedesc.wave_array_count,
                "raw_bytes": wavedesc.raw_bytes,
                "source": wavedesc.source,
            }
            if wavedesc is not None
            else {"source": "unavailable", "error": desc_error}
        )
        metadata: dict[str, Any] = {
            "channel": ch,
            "commands": {
                "vdiv": f"{ch}:VDIV?",
                "offset": f"{ch}:OFST?",
                "timebase": "TDIV?",
                "sample_rate": "SARA?",
                "waveform_setup": "WFSU SP,1,NP,0,FP,0",
                "waveform_desc": f"{ch}:WF? DESC",
                "waveform_query": f"{ch}:WF? DAT2",
            },
            "raw_responses": {
                "vdiv": vdiv_raw,
                "offset": ofst_raw,
                "probe_attenuation": attn_raw,
                "timebase": tdiv_raw,
                "sample_rate": sara_raw,
            },
            "parsed": {
                "vdiv_v": vdiv,
                "offset_v": offset,
                "timebase_s_per_div": tdiv,
                "sample_rate_sps": sample_rate,
                "time_interval_s": time_interval,
                "start_time_s": start_time,
            },
            "wavedesc": wavedesc_info,
            "decode": {
                "source": decode_source,
                "vertical_gain_v_per_code": gain_used,
                "vertical_offset_v": offset_used,
                "time_source": time_source,
                "codes_per_div_fallback": CODES_PER_DIV,
            },
            "binary": {"bytes": len(raw), "framing": block.framing},
            "points": {
                "total": total_points,
                "returned": returned_points,
                "decimation": "minmax_envelope",
            },
            "status": "candidate_implementation_requires_sds824xhd_validation",
        }
        write_json(metadata_out, metadata)
        return WaveformResult(csv_path=str(csv_out), metadata_path=str(metadata_out), metadata=metadata)

    def capture_uart_2mbps(
        self,
        channel: Channel = "C1",
        logic_level: Literal["3.3V TTL", "5V TTL"] = "3.3V TTL",
        max_points: int = 5000,
    ) -> dict[str, Any]:
        ch = _channel(channel)
        trigger_level = "1.5V" if logic_level == "3.3V TTL" else "2.5V"
        setup = self.configure_channel(ch, vdiv="1V", offset="0V", coupling="D1M", trace=True, probe=10)
        acq = self.configure_acquisition(
            command="single",
            timebase="1US",
            trigger_mode="SINGLE",
            trigger_source=ch,
            trigger_level=trigger_level,
            trigger_slope="NEG",
        )
        time.sleep(0.5)
        shot = self.screenshot(default_artifact_paths("uart_2mbps")["screenshot_raw"])
        wf = self.get_waveform(ch, max_points=max_points)
        analysis = analyze_uart_csv(wf.csv_path, baudrate=2_000_000).to_dict()
        analysis_path = write_json(default_artifact_paths("uart_2mbps")["analysis_json"], analysis)
        return {
            "channel_setup": setup,
            "acquisition_setup": acq,
            "screenshot": shot,
            "waveform": {"csv_path": wf.csv_path, "metadata_path": wf.metadata_path, "metadata": wf.metadata},
            "analysis": analysis,
            "analysis_path": analysis_path,
            "status": "candidate_implementation_requires_sds824xhd_validation",
        }

    def _query_or_error(self, command: str) -> str:
        try:
            return self.transport.query(command)
        except Exception as exc:  # noqa: BLE001 - diagnostic surface
            return f"ERROR: {exc!r}"


def _channel(channel: str) -> Channel:
    channel = channel.upper()
    if channel not in {"C1", "C2", "C3", "C4"}:
        raise ValueError("channel must be C1, C2, C3, or C4")
    return channel  # type: ignore[return-value]


def _pick_vdiv(pkpk_v: float, *, divisions: float = _AUTOSET_DIVISIONS_V) -> float:
    """选最小的、能在 divisions 格内容纳 pkpk 幅度的 VDIV 档。"""
    if pkpk_v <= 0:
        return _VDIV_STEPS_V[2]  # 默认 20mV/div
    needed = pkpk_v / divisions
    for v in _VDIV_STEPS_V:
        if v >= needed * 0.9:
            return v
    return _VDIV_STEPS_V[-1]


def _pick_tdiv(period_s: float, *, cycles: float = 4.0, divisions: float = _AUTOSET_DIVISIONS_H) -> float:
    """选最小的、能显示 cycles 个完整周期（divisions 格）的 TDIV 档。"""
    if period_s <= 0:
        return _TDIV_STEPS_S[11]  # 默认 5µs/div
    needed = period_s * cycles / divisions
    for t in _TDIV_STEPS_S:
        if t >= needed * 0.9:
            return t
    return _TDIV_STEPS_S[-1]


def _parse_meas_value(raw: str) -> float | None:
    """从 measure() 返回值解析数值。无效测量（含 '****'）返回 None。

    measure() 返回形如 {"value": "PKPK,2.04E-02"}，取逗号后数值。
    """
    if "****" in raw:
        return None
    try:
        return float(raw.split(",")[-1])
    except (ValueError, IndexError):
        return None


def _fmt_sci(value: float) -> str:
    """格式化为示波器接受的科学计数法（4 位有效数字）。"""
    return f"{value:.4E}"


def _parse_voltage(value: str) -> float:
    """Parse voltage value with SI prefixes (case-sensitive: mV≠MV).

    Scope SCPI returns bare scientific notation (1.00E-01), but user-facing
    inputs and stored metadata may use prefixed forms like "500mV", "1KV".
    Case-sensitive matching ensures "mV" (milli, 1e-3) is not confused with
    "MV" (mega, 1e6).
    """
    text = value.strip().replace(" ", "")
    try:
        return float(text)
    except ValueError:
        pass

    suffixes = [
        ("GV", 1e9),
        ("MV", 1e6),   # megavolt — must come before "mV"
        ("KV", 1e3),
        ("V", 1.0),
        ("mV", 1e-3),  # millivolt — case-sensitive, after "MV"
        ("uV", 1e-6),
        ("μV", 1e-6),
        ("nV", 1e-9),
    ]
    for suffix, multiplier in sorted(suffixes, key=lambda kv: len(kv[0]), reverse=True):
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            return float(number) * multiplier
    raise ValueError(f"cannot parse voltage: {value!r}")


def _parse_time(value: str) -> float:
    """Parse time value with SI prefixes.

    Scope convention: "MS" = milliseconds (1e-3), NOT megaseconds.
    Scope SCPI returns bare scientific notation (5.00E-06 for 5µs),
    but user inputs like "--coarse-timebase 1MS" arrive prefixed.
    """
    text = value.strip().replace(" ", "")
    try:
        return float(text)
    except ValueError:
        pass

    suffixes = [
        ("GS", 1e9),
        ("MS", 1e-3),  # milliseconds — scope convention, NOT megaseconds
        ("KS", 1e3),
        ("S", 1.0),
        ("US", 1e-6),
        ("μS", 1e-6),
        ("NS", 1e-9),
        ("PS", 1e-12),
    ]
    for suffix, multiplier in sorted(suffixes, key=lambda kv: len(kv[0]), reverse=True):
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            return float(number) * multiplier
    raise ValueError(f"cannot parse time: {value!r}")


def _parse_sample_rate(value: str) -> float:
    """Parse sample rate value (Sa/s).

    Scope SCPI returns bare scientific notation (2.00E+09 for 2GSa/s),
    but user-facing display uses prefixed forms like "500MSa/s", "2GSa/s".
    Strips "Sa/s" suffix then delegates to SI prefix parsing.
    """
    text = value.strip().replace(" ", "").replace("Sa/s", "").replace("SA/S", "")
    try:
        return float(text)
    except ValueError:
        pass

    suffixes = [
        ("G", 1e9),
        ("M", 1e6),
        ("K", 1e3),
        ("T", 1e12),
    ]
    for suffix, multiplier in sorted(suffixes, key=lambda kv: len(kv[0]), reverse=True):
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            return float(number) * multiplier
    raise ValueError(f"cannot parse sample rate: {value!r}")


def _parse_number_with_units(value: str) -> float:
    """Legacy generic unit parser — prefer context-specific functions.

    Use _parse_voltage(), _parse_time(), or _parse_sample_rate() for
    correct handling of ambiguous prefixes (mV vs MV, MS for time vs
    sample rate). This function remains as a fallback for cases where
    the unit type is genuinely unknown at parse time.
    """
    text = value.strip().replace(" ", "")
    try:
        return float(text)
    except ValueError:
        pass

    upper = text.upper().replace("μ", "U")
    # Generic suffixes sorted longest-first.
    suffixes = [
        ("MSA", 1e6),
        ("GSA", 1e9),
        ("KSA", 1e3),
        ("GS", 1e9),
        ("MS", 1e-3),  # milliseconds (assume time context in generic parser)
        ("KS", 1e3),
        ("NS", 1e-9),
        ("US", 1e-6),
        ("S", 1.0),
        ("GV", 1e9),
        ("MV", 1e6),
        ("KV", 1e3),
        ("V", 1.0),
        # NOTE: "mV" (millivolt) cannot be distinguished from "MV" (megavolt)
        # after upper() — use _parse_voltage() instead.
        ("G", 1e9),
        ("M", 1e6),
        ("K", 1e3),
    ]
    for suffix, multiplier in sorted(suffixes, key=lambda kv: len(kv[0]), reverse=True):
        if upper.endswith(suffix):
            number = upper[: -len(suffix)]
            return float(number) * multiplier
    # Last resort: parse leading numeric part.
    numeric_chars = []
    for char in upper:
        if char.isdigit() or char in ".-+Ee":
            numeric_chars.append(char)
        else:
            break
    if numeric_chars:
        return float("".join(numeric_chars))
    raise ValueError(f"cannot parse numeric value: {value!r}")


def _siglent_byte_to_voltage(byte: int, gain_v_per_code: float, offset_v: float) -> float:
    """将原始 byte 解码为电压。

    参数:
        byte: 原始采样值 (0~255)
        gain_v_per_code: 每码电压 (V/code)，= VDIV / codes_per_div
        offset_v: 垂直偏移 (V)，= 面板 OFST

    编码模式:
        OFST=0V: 原始 ADC 有符号编码，code_signed × gain 即得电压
        OFST≠0V: 数据中心化，byte 128 对应 OFST 电压
    """
    if offset_v == 0.0:
        code = byte if byte <= 127 else byte - 256
        return code * gain_v_per_code
    else:
        return (byte - 128) * gain_v_per_code + offset_v


def _siglent_byte_to_voltage_gain(
    byte: int, vertical_gain: float, vertical_offset: float, probe_attn: float = 1.0
) -> float:
    """WAVEDESC 解码。

    WAVEDESC 内 VERTICAL_GAIN/VERTICAL_OFFSET 为 scope 输入端电平（已含探头衰减
    补偿前的原始值）。为与面板读数（探头端）一致，结果整体 × probe_attn。
    """
    if vertical_offset == 0.0:
        code = byte if byte <= 127 else byte - 256
        return code * vertical_gain * probe_attn
    else:
        return ((byte - 128) * vertical_gain + vertical_offset) * probe_attn


def _inspect_bmp(data: bytes) -> dict[str, Any]:
    if len(data) < 54 or not data.startswith(b"BM"):
        return {}
    return {
        "format": "BMP",
        "bmp_file_size": int.from_bytes(data[2:6], byteorder="little", signed=False),
        "pixel_offset": int.from_bytes(data[10:14], byteorder="little", signed=False),
        "width": int.from_bytes(data[18:22], byteorder="little", signed=True),
        "height": int.from_bytes(data[22:26], byteorder="little", signed=True),
        "bits_per_pixel": int.from_bytes(data[28:30], byteorder="little", signed=False),
        "compression": int.from_bytes(data[30:34], byteorder="little", signed=False),
    }
