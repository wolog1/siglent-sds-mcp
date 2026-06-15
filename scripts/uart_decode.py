#!/usr/bin/env python3
"""从示波器波形CSV解码UART (8N1)。"""
import csv
import sys

BAUD = 1_500_000


def load(path):
    t, v = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            t.append(float(row["time_s"]))
            v.append(float(row["voltage_v"]))
    return t, v


def decode(path, baud=BAUD, vth=None):
    t, v = load(path)
    n = len(v)
    dt = (t[-1] - t[0]) / (n - 1)
    vmin, vmax = min(v), max(v)
    if vth is None:
        vth = (vmin + vmax) / 2
    print(f"样点={n} dt={dt*1e9:.2f}ns  Vmin={vmin:.3f} Vmax={vmax:.3f} Vpp={vmax-vmin:.3f} 门限={vth:.3f}V")

    # 数字化：高电平=1（UART空闲为高）
    bits = [1 if x > vth else 0 for x in v]
    bit_samples = (1.0 / baud) / dt
    print(f"每位采样数={bit_samples:.1f}")

    # 找下降沿（起始位）逐帧解码
    chars = []
    i = 1
    while i < n - int(10 * bit_samples):
        if bits[i - 1] == 1 and bits[i] == 0:  # 起始位下降沿
            start = i
            # 在每位中心采样
            byte = 0
            ok = True
            # 校验起始位中心为0
            c0 = int(start + 0.5 * bit_samples)
            if bits[c0] != 0:
                i += 1
                continue
            for b in range(8):
                center = int(start + (1.5 + b) * bit_samples)
                if center >= n:
                    ok = False
                    break
                byte |= (bits[center] << b)  # LSB先
            # 停止位
            stop_c = int(start + 9.5 * bit_samples)
            if ok and stop_c < n and bits[stop_c] == 1:
                chars.append(byte)
                i = int(start + 10 * bit_samples)
                continue
        i += 1

    print(f"\n解码字节数={len(chars)}")
    hexs = " ".join(f"{c:02X}" for c in chars)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chars)
    print("HEX:", hexs)
    print("ASCII:", asc)
    return chars, asc


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/book/siglent-sds-mcp/uart_capture.csv"
    decode(path)
