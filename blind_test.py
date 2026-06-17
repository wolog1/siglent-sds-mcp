#!/usr/bin/env python3
"""Blind test: capture and decode any UART signal without prior knowledge."""
from __future__ import annotations

import sys
sys.path.insert(0, "src")

from siglent_sds_mcp.tcp_transport import RawTcpTransport
from siglent_sds_mcp.uart_capture import capture_uart_auto

HOST = "192.168.0.170"
PORT = 5025


def main() -> int:
    print(f"Connecting to {HOST}:{PORT}...")
    transport = RawTcpTransport(HOST, PORT, timeout_s=30.0)
    transport.connect()
    print("Connected. Running blind capture (baudrate=0 auto-detect)...")
    print("-" * 60)

    result = capture_uart_auto(
        transport,
        channel="C1",
        baudrate=0,          # auto-detect
        probe_attn=10.0,     # 10x probe
        max_bytes=64,
        timeout_s=60.0,
        min_pkpk_v=0.5,      # lower threshold for 3.3V signals
        max_trigger_attempts=8,
    )

    print("\n=== BLIND TEST RESULT ===\n")
    print(f"OK: {result.ok}")
    print(f"Detected baud: {result.detected_baud} (confidence: {result.baud_confidence})")
    print(f"Measured baud: {result.measured_baud}")
    print(f"Vpp: {result.vpp_v:.3f} V" if result.vpp_v else "Vpp: N/A")
    print(f"TDIV: {result.tdiv_s*1e3:.3g} ms/div" if result.tdiv_s else "TDIV: N/A")
    print(f"Frames: {result.frame_count} total, {result.valid_frame_count} valid")
    print(f"Stop-ok rate: {result.stop_ok_rate:.2%}")
    print(f"\nDecoded ASCII: {repr(result.decoded_ascii)}")
    print(f"Decoded HEX:   {result.decoded_hex}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  - {w}")

    if result.notes:
        print(f"\nNotes ({len(result.notes)}):")
        for n in result.notes:
            print(f"  • {n}")

    print("-" * 60)
    transport.close()

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
