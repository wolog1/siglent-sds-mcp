#!/usr/bin/env python3
"""验证修复：直接使用仓库 RawTcpTransport + SDS800XHDTcpAdapter 跑全流程。

重点验证：
  1. 截图(二进制)后紧接查询不再错位
  2. get_channel / get_acquisition_status 字段对齐
  3. measure 返回有效值
  4. get_waveform 能正确解析 'DAT2,#9...' 波形块
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport

HOST, PORT = "192.168.0.170", 5025


def main():
    t = RawTcpTransport(HOST, PORT, timeout_s=5.0)
    t.connect()
    a = SDS800XHDTcpAdapter(t)
    a.try_header_off()

    print("IDN:", a.identify())

    # 基础配置
    a.configure_channel("C1", vdiv="1", offset="-1.65", coupling="D1M", trace=True, probe=1)
    a.configure_acquisition(timebase="10US", trigger_mode="AUTO", trigger_source="C1",
                            trigger_level="1.65", trigger_slope="NEG", command="run")
    import time
    time.sleep(0.8)

    # 1) 截图（二进制） —— 关键的错位诱因
    shot = a.screenshot(output_path="/home/book/siglent-sds-mcp/verify_shot.png")
    print("\nscreenshot:", {k: shot[k] for k in ("bytes", "framing", "format", "width", "height") if k in shot})

    # 2) 截图之后立即查询：若修复成功，应正确返回数值而非空/错位
    print("\n截图后紧接查询(验证不再错位):")
    print("  C1:VDIV? =", t.query("C1:VDIV?"))
    print("  C1:OFST? =", t.query("C1:OFST?"))
    print("  TDIV?    =", t.query("TDIV?"))

    # 3) get_channel 字段对齐
    print("\nget_channel:", a.get_channel("C1"))

    # 4) 采集状态
    print("\nget_acquisition_status:", a.get_acquisition_status())

    # 5) 测量
    for p in ("MAX", "MIN", "PKPK", "MEAN", "FREQ"):
        print(f"measure {p}:", a.measure("C1", p)["value"])

    # 6) 波形下载（DAT2 前缀解析）
    print("\nget_waveform ...")
    wf = a.get_waveform("C1", csv_path="/home/book/siglent-sds-mcp/verify_wave.csv",
                        metadata_path="/home/book/siglent-sds-mcp/verify_wave.json",
                        max_points=5000)
    md = wf.metadata
    print("  binary bytes:", md["binary"]["bytes"], "framing:", md["binary"]["framing"])
    print("  points total/returned:", md["points"]["total"], md["points"]["returned"])
    print("  parsed:", md["parsed"])

    # 读回CSV做基本统计
    import csv as _csv
    vs = []
    with open("/home/book/siglent-sds-mcp/verify_wave.csv") as f:
        for row in _csv.DictReader(f):
            vs.append(float(row["voltage_v"]))
    if vs:
        print(f"  CSV {len(vs)} 点  Vmin={min(vs):.3f} Vmax={max(vs):.3f} Vpp={max(vs)-min(vs):.3f}")

    t.close()
    print("\n[OK] 全流程完成")


if __name__ == "__main__":
    main()
