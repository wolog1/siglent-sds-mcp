#!/usr/bin/env python3
"""SDS824X HD 命令支持探测脚本（直连，绕开MCP封装）。

用于审计哪些SCPI命令在本机型可用、响应格式如何，为修复MCP适配器提供依据。
"""
import socket
import time
import sys

HOST = "192.168.0.170"
PORT = 5025


class Scope:
    def __init__(self, host=HOST, port=PORT, timeout=5.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)

    def write(self, cmd):
        self.s.sendall(cmd.encode() + b"\n")

    def read(self, n=8192):
        try:
            return self.s.recv(n)
        except socket.timeout:
            return b"<TIMEOUT>"

    def query(self, cmd, wait=0.2):
        self.write(cmd)
        time.sleep(wait)
        return self.read()

    def close(self):
        self.s.close()


def main():
    sc = Scope()
    print("IDN:", sc.query("*IDN?"))
    print("CHDR OFF:", sc.write("CHDR OFF") or "(sent)")
    time.sleep(0.2)

    tests_query = [
        "C1:VDIV?",
        "C1:OFST?",
        "C1:CPL?",
        "C1:TRA?",
        "TDIV?",
        "SARA?",          # legacy sample rate
        "SANU? C1",       # legacy sample number
        "ACQUIRE:SRATE?", # new sample rate
        "ACQ:MDEP?",      # memory depth
        "TRMD?",
        "C1:TRLV?",
        "C1:TRSL?",
        "TRSE?",
    ]
    print("\n==== 查询命令探测 ====")
    for c in tests_query:
        print(f"{c:20s} -> {sc.query(c)!r}")

    # VDIV 单位解析行为测试
    print("\n==== VDIV 单位写入行为 ====")
    for val in ["1", "1V", "2V", "0.5", "500MV"]:
        sc.write(f"C1:VDIV {val}")
        time.sleep(0.25)
        rb = sc.query("C1:VDIV?")
        print(f"写 'C1:VDIV {val:6s}' -> 读回 {rb!r}")

    # OFST 单位
    print("\n==== OFST 单位写入行为 ====")
    for val in ["0", "-1.65", "-1.65V"]:
        sc.write(f"C1:OFST {val}")
        time.sleep(0.25)
        rb = sc.query("C1:OFST?")
        print(f"写 'C1:OFST {val:7s}' -> 读回 {rb!r}")

    # 测量命令: legacy PAVA vs new MEASure
    print("\n==== 测量命令探测 ====")
    sc.write("C1:VDIV 1"); sc.write("C1:OFST -1.65"); sc.write("TRMD AUTO"); sc.write("ARM")
    time.sleep(0.6)
    print("C1:PAVA? MAX ->", sc.query("C1:PAVA? MAX"))
    print("C1:PAVA? PKPK ->", sc.query("C1:PAVA? PKPK"))
    print("MEAS new MAX ->", sc.query("MEASure:ADVanced:P1:VALue?"))
    print("PACU? ->", sc.query("PACU?"))
    print("C1:PAVA? MEAN ->", sc.query("C1:PAVA? MEAN"))

    sc.close()


if __name__ == "__main__":
    main()
