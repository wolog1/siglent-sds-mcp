#!/usr/bin/env python3
"""改进UART解码器：直方图双峰定门限 + 每帧起始沿重同步 + 自动测波特率。"""
import csv
import sys


def load(path):
    t, v = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            t.append(float(row["time_s"]))
            v.append(float(row["voltage_v"]))
    return t, v


def bimodal_threshold(v):
    lo, hi = min(v), max(v)
    nb = 50
    bins = [0] * nb
    for x in v:
        bins[min(nb - 1, int((x - lo) / (hi - lo) * nb))] += 1
    # 两个最高峰
    peaks = sorted(range(nb), key=lambda i: bins[i], reverse=True)
    p1 = peaks[0]
    p2 = next((p for p in peaks[1:] if abs(p - p1) > 5), peaks[1])
    lvl1 = lo + (p1 + 0.5) * (hi - lo) / nb
    lvl2 = lo + (p2 + 0.5) * (hi - lo) / nb
    return (lvl1 + lvl2) / 2, min(lvl1, lvl2), max(lvl1, lvl2)


def measure_baud(b, dt):
    edges = [i for i in range(1, len(b)) if b[i] != b[i - 1]]
    if len(edges) < 2:
        return None
    widths = sorted((edges[i + 1] - edges[i]) for i in range(len(edges) - 1))
    unit = widths[0]  # 最短脉宽 = 1 位
    return 1.0 / (unit * dt), edges


def decode(path, baud=1_500_000):
    t, v = load(path)
    n = len(v)
    dt = (t[-1] - t[0]) / (n - 1)
    vth, vlow, vhigh = bimodal_threshold(v)
    b = [1 if x > vth else 0 for x in v]
    meas = measure_baud(b, dt)
    mbaud = meas[0] if meas else 0
    print(f"样点={n} dt={dt*1e9:.3f}ns  低={vlow:.3f}V 高={vhigh:.3f}V 门限={vth:.3f}V")
    print(f"指定波特率={baud}  实测波特率≈{mbaud:,.0f}")

    bs = (1.0 / baud) / dt
    chars = []
    i = 1
    while i < n - int(10 * bs):
        if b[i - 1] == 1 and b[i] == 0:  # 起始位下降沿
            start = i
            if b[int(start + 0.5 * bs)] != 0:
                i += 1
                continue
            byte = 0
            for bit in range(8):
                c = int(round(start + (1.5 + bit) * bs))
                byte |= (b[c] << bit)
            stop = int(round(start + 9.5 * bs))
            if b[stop] == 1:  # 有效停止位
                chars.append(byte)
                i = start + int(round(9.5 * bs))  # 跳到停止位后再找下一个起始沿
                # 继续扫描下一个下降沿
                while i < n and b[i] == 1:
                    i += 1
                continue
        i += 1

    hexs = " ".join(f"{c:02X}" for c in chars)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chars)
    print(f"\n解码 {len(chars)} 字节:")
    print("HEX  :", hexs)
    print("ASCII:", asc)

    expect = "shijieheping"
    print(f"\n期望 : {expect}  HEX: " + " ".join(f"{ord(c):02X}" for c in expect))
    return chars, asc


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/book/siglent-sds-mcp/uart_msg.csv"
    decode(path)
