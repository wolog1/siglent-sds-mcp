#!/usr/bin/env python3
"""第二轮探测：确认BMP尾字节残留、PAVA测量、WF?波形读取。"""
import socket
import time

HOST, PORT = "192.168.0.170", 5025


def main():
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.settimeout(5)

    def w(c):
        s.sendall(c.encode() + b"\n")

    def rline():
        buf = b""
        while True:
            ch = s.recv(1)
            if not ch:
                return buf + b"<CLOSED>"
            if ch == b"\n":
                return buf
            buf += ch

    def q(c, wait=0.2):
        w(c)
        time.sleep(wait)
        return rline()

    def drain(t=0.3):
        s.settimeout(t)
        extra = b""
        try:
            while True:
                d = s.recv(4096)
                if not d:
                    break
                extra += d
        except socket.timeout:
            pass
        s.settimeout(5)
        return extra

    print("IDN:", q("*IDN?"))
    w("CHDR OFF"); time.sleep(0.2); drain()

    # ---- 干净采集 ----
    w("C1:TRA ON"); w("C1:VDIV 1"); w("C1:OFST -1.65"); w("C1:CPL D1M")
    w("TDIV 10US"); w("TRMD AUTO"); w("ARM")
    time.sleep(0.8)

    print("\n==== PAVA 各参数 ====")
    for p in ["MAX", "MIN", "PKPK", "MEAN", "AMPL", "TOP", "BASE", "FREQ", "PER"]:
        print(f"PAVA {p:5s}:", q(f"C1:PAVA? {p}"))

    # ---- 截图BMP尾字节探测 ----
    print("\n==== 截图BMP尾字节探测 ====")
    w("SCDP")
    time.sleep(0.5)
    first = s.recv(2)
    print("first2:", first)
    if first.startswith(b"BM"):
        header = first + recv_exact(s, 54 - len(first))
        file_size = int.from_bytes(header[2:6], "little")
        print("file_size:", file_size)
        body = recv_exact(s, file_size - len(header))
        print("read bytes total:", len(header) + len(body))
        trailing = drain(0.4)
        print("TRAILING after BMP:", repr(trailing[:20]), "len=", len(trailing))

    # ---- WF? DAT2 波形读取 ----
    print("\n==== 波形读取 WF? DAT2 ====")
    print("VDIV?:", q("C1:VDIV?"))
    print("OFST?:", q("C1:OFST?"))
    print("SARA?:", q("SARA?"))
    w("WFSU SP,0,NP,0,FP,0"); time.sleep(0.2)
    w("C1:WF? DAT2")
    time.sleep(0.5)
    first = s.recv(2)
    print("WF first2:", first)
    if first.startswith(b"#"):
        ndig = int(chr(first[1]))
        lens = recv_exact(s, ndig)
        dlen = int(lens.decode())
        print("WF data_len:", dlen)
        payload = recv_exact(s, dlen)
        print("WF payload bytes:", len(payload), "sample[0:8]:", list(payload[:8]))
        trailing = drain(0.3)
        print("WF trailing:", repr(trailing[:8]), "len=", len(trailing))
    else:
        rest = first + drain(0.3)
        print("WF non-block resp:", repr(rest[:40]))

    s.close()


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        d = s.recv(n - len(buf))
        if not d:
            break
        buf += d
    return buf


if __name__ == "__main__":
    main()
