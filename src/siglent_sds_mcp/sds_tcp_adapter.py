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
# 每格对应的码值（code-per-div）经真机 SDS824X HD 实测确认为 30，而非
# 旧 SDS1000X-E 的 25：
#   - 原始码值范围 [-68, +41]，VDIV=0.2V，OFST=-0.24V；
#   - 取 30 码/格解码得 [-0.213V, +0.513V]，与面板实测 [-0.204V, +0.515V] 吻合；
#   - 取 25 码/格解码得 [-0.304V, +0.568V]，系统性偏大约 20%（错误）；
#   - WAVEDESC.MAX_VALUE = 7680 = 30 × 256，再次佐证 30 码/格。
# 优先从 WAVEDESC 读取 VERTICAL_GAIN 进行自适应解码（见 _parse_wavedesc）；
# 仅当描述符不可用或解析失败时，回退到本硬编码常量。
CODES_PER_DIV = 30

# ---------------------------------------------------------------------------
# WAVEDESC 二进制描述符字段偏移（Siglent SDS 系列，little-endian）
# 参考：Siglent SDS Programming Guide EN11D / LeCroy WAVEDESC 规范。
# 解码公式：voltage(code) = code * VERTICAL_GAIN - VERTICAL_OFFSET
# ---------------------------------------------------------------------------
_WAVEDESC_SIGNATURE = b"WAVEDESC"   # 描述符起始标记，位于 offset 0
_OFF_WAVE_ARRAY_COUNT: int = 116    # int32  — 采样点数
_OFF_VERTICAL_GAIN: int    = 156    # float32 — 码值→伏特缩放系数 (V/code)
_OFF_VERTICAL_OFFSET: int  = 160    # float32 — 垂直偏移 (V)
_OFF_HORIZ_INTERVAL: int   = 176    # float32 — 水平采样间隔 (s/sample)
_OFF_HORIZ_OFFSET: int     = 180    # float64 — 触发偏移 (s)，首点 = -HORIZ_OFFSET


@dataclass(slots=True)
class WaveDescriptor:
    """从 WAVEDESC 二进制块解析出的关键定标参数。"""

    vertical_gain: float    # V/code
    vertical_offset: float  # V（解码公式：v = code * gain - offset）
    horiz_interval: float   # s/sample（0 → 不可用）
    horiz_offset: float     # s，触发点相对首采样点的偏移（0 → 不可用）
    wave_array_count: int   # 描述符中记录的点数（0 → 不可用）
    raw_bytes: int          # 描述符总字节数（用于诊断）
    source: str             # "wavedesc" | "fallback"


def _parse_wavedesc(data: bytes) -> WaveDescriptor | None:
    """解析 WAVEDESC 二进制描述符，失败返回 None。

    SIGLENT SDS 返回的描述符数据开头可能附带 ASCII 前缀（如 "C1:WF DESC,"），
    本函数自动搜索 b"WAVEDESC" 标记并从其偏移处解析字段。
    """
    # 定位描述符起始签名
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
        (horiz_interval,)   = struct.unpack_from("<f", desc, _OFF_HORIZ_INTERVAL)
        (horiz_offset,)     = struct.unpack_from("<d", desc, _OFF_HORIZ_OFFSET)
    except struct.error:
        return None
    # 基本合理性检验：gain 为 0 或 NaN 时认为不可用
    import math
    if vertical_gain == 0.0 or not math.isfinite(vertical_gain):
        return None
    return WaveDescriptor(
        vertical_gain=float(vertical_gain),
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
    ) -> WaveformResult:
        ch = _channel(channel)
        paths = default_artifact_paths(f"waveform_{ch.lower()}")
        csv_out = ensure_parent(csv_path or paths["waveform_csv"])
        metadata_out = ensure_parent(metadata_path or paths["metadata_json"])

        # --- 1. 辅助查询（用于 fallback 解码及元数据记录）---
        vdiv_raw = self.transport.query(f"{ch}:VDIV?")
        ofst_raw = self.transport.query(f"{ch}:OFST?")
        tdiv_raw = self.transport.query("TDIV?")
        sara_raw = self.transport.query("SARA?")

        vdiv = _parse_number_with_units(vdiv_raw)
        offset = _parse_number_with_units(ofst_raw)
        tdiv = _parse_number_with_units(tdiv_raw)
        sample_rate = _parse_sample_rate(sara_raw)

        # --- 2. 尝试获取 WAVEDESC 描述符（自适应解码的关键数据源）---
        # SIGLENT 响应格式为：<ch>:WF DESC,#<n><len><descriptor_bytes>
        # 通过 query_binary 统一读取 IEEE 488.2 块，再搜索 WAVEDESC 标记解析。
        wavedesc: WaveDescriptor | None = None
        desc_error: str | None = None
        try:
            self.transport.write("WFSU SP,0,NP,0,FP,0")
            desc_block = self.transport.query_binary(f"{ch}:WF? DESC", timeout_s=10.0)
            wavedesc = _parse_wavedesc(desc_block.data)
            if wavedesc is None:
                desc_error = "parse_failed: WAVEDESC signature not found or sanity check failed"
        except Exception as exc:  # noqa: BLE001 - WAVEDESC 不可用时安全降级
            desc_error = f"query_failed: {exc!r}"

        # --- 3. 下载原始波形数据 ---
        self.transport.write("WFSU SP,0,NP,0,FP,0")
        block = self.transport.query_binary(f"{ch}:WF? DAT2", timeout_s=30.0)
        raw = block.data
        total_points = len(raw)

        # --- 4. 电压解码：优先 WAVEDESC，fallback 到 CODES_PER_DIV 常量 ---
        # WAVEDESC 公式：voltage = code * VERTICAL_GAIN - VERTICAL_OFFSET
        # Fallback 公式：voltage = code * (vdiv / CODES_PER_DIV) - offset
        if wavedesc is not None and wavedesc.vertical_gain != 0.0:
            voltages = [
                _siglent_byte_to_voltage_gain(byte, wavedesc.vertical_gain, wavedesc.vertical_offset)
                for byte in raw
            ]
            decode_source = "wavedesc"
            gain_used = wavedesc.vertical_gain
            offset_used = wavedesc.vertical_offset
        else:
            voltages = [_siglent_byte_to_voltage(byte, vdiv, offset) for byte in raw]
            decode_source = "fallback_codes_per_div"
            gain_used = vdiv / CODES_PER_DIV
            offset_used = offset

        # --- 5. 时间轴定标：优先 WAVEDESC，fallback 到 SARA/触发居中 ---
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

        # --- 6. min/max 包络抽样输出 ---
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

        # --- 7. 元数据 ---
        wavedesc_info: dict[str, Any] = (
            {
                "vertical_gain": wavedesc.vertical_gain,
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
                "waveform_setup": "WFSU SP,0,NP,0,FP,0",
                "waveform_desc": f"{ch}:WF? DESC",
                "waveform_query": f"{ch}:WF? DAT2",
            },
            "raw_responses": {
                "vdiv": vdiv_raw,
                "offset": ofst_raw,
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


def _parse_sample_rate(value: str) -> float:
    return _parse_number_with_units(value.replace("Sa/s", ""))


def _parse_number_with_units(value: str) -> float:
    text = value.strip().replace(" ", "")
    multipliers = {
        "GV": 1e9,
        "MV": 1e6,
        "KV": 1e3,
        "V": 1.0,
        "MVOLT": 1e-3,
        "UV": 1e-6,
        "GS": 1e9,
        "MS": 1e6,
        "KS": 1e3,
        "S": 1.0,
        "NS": 1e-9,
        "US": 1e-6,
        "MSA": 1e6,
        "GSA": 1e9,
        "KSA": 1e3,
        "M": 1e6,
        "G": 1e9,
        "K": 1e3,
    }
    try:
        return float(text)
    except ValueError:
        pass

    upper = text.upper().replace("μ", "U")
    # Longest suffix first so MS is checked before S.
    for suffix, multiplier in sorted(multipliers.items(), key=lambda item: len(item[0]), reverse=True):
        if upper.endswith(suffix):
            number = upper[: -len(suffix)]
            return float(number) * multiplier
    # Last resort: parse leading numeric part.
    numeric = []
    for char in upper:
        if char.isdigit() or char in ".-+Ee":
            numeric.append(char)
        else:
            break
    if numeric:
        return float("".join(numeric))
    raise ValueError(f"cannot parse numeric value: {value!r}")


def _siglent_byte_to_voltage(byte: int, vdiv: float, offset: float) -> float:
    # SIGLENT WF? DAT2 返回 8bit 有符号编码。无符号字节转有符号：>127 时减 256。
    # 每格码值由 CODES_PER_DIV 给出（SDS824X HD 实测为 30）。
    # 仅在无 WAVEDESC 可用时作为 fallback 使用。
    code = byte if byte <= 127 else byte - 256
    return code * (vdiv / CODES_PER_DIV) - offset


def _siglent_byte_to_voltage_gain(byte: int, vertical_gain: float, vertical_offset: float) -> float:
    # WAVEDESC 自适应解码：voltage = code * VERTICAL_GAIN - VERTICAL_OFFSET
    # VERTICAL_GAIN 和 VERTICAL_OFFSET 直接来自描述符，无需知道 CODES_PER_DIV。
    code = byte if byte <= 127 else byte - 256
    return code * vertical_gain - vertical_offset


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
