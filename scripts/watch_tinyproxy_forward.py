"""Фоновый монитор прямого ADB forward (запускается автоматически)."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dto import OwnMobileProxyConfig
from utils.tinyproxy_forward import watch_forward


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="")
    parser.add_argument("--ports", nargs=2, type=int, required=True)
    args = parser.parse_args()
    config = OwnMobileProxyConfig(adb_forward=args.ports)
    watch_forward(args.serial, config.adb_forward)


if __name__ == "__main__":
    main()
