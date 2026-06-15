from __future__ import annotations

import sys

from siglent_sds_mcp.scope_driver import SiglentSDSDriver


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python examples/idn_test.py <VISA_RESOURCE>")
        print("Example: python examples/idn_test.py TCPIP0::192.168.1.100::INSTR")
        return 2

    resource = sys.argv[1]
    scope = SiglentSDSDriver.connect(resource)
    try:
        print(scope.idn())
    finally:
        scope.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
