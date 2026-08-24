#!/usr/bin/env python3
"""Package Center -- manage RPM packages, Flatpak apps and their sandbox
permissions, and user-level developer tooling from one window.

Run with the system Python (which provides the GTK4/libadwaita bindings):
    python3 main.py
"""
import sys

from pkgcenter.app import PkgCenterApplication


def main() -> int:
    return PkgCenterApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
