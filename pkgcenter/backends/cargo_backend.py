"""Cargo-installed binaries. Not installed on this machine at plan time.
`cargo install --list` output (documented format):

    ripgrep v13.0.0:
        rg
    some-crate v0.1.0 (https://github.com/foo/bar#abc123):
        some-binary

Unindented lines ending in ':' are package headers ("name vVERSION[...]:");
indented lines below are the binaries they installed (not needed for our
purposes beyond confirming the package exists). Installs go to
~/.cargo/bin -- no elevation.
"""
from __future__ import annotations

import re
import shutil
from typing import Callable

from ..command_runner import CommandResult, CommandRunner
from ..models import InstalledPackage
from .base import PackageBackend

CARGO = "cargo"
_HEADER_RE = re.compile(r"^(\S+) v(\S+)(?:\s+\(.*\))?:$")


def _parse_list(stdout: str) -> list[InstalledPackage]:
    packages: list[InstalledPackage] = []
    for line in stdout.splitlines():
        if not line or line[0].isspace():
            continue
        match = _HEADER_RE.match(line.strip())
        if not match:
            continue
        name, version = match.groups()
        packages.append(
            InstalledPackage(
                name=name,
                version=version,
                size_bytes=0,
                source="cargo",
                user_installed=True,
            )
        )
    return packages


class CargoBackend(PackageBackend):
    name = "cargo"
    label = "Cargo"

    def is_available(self) -> bool:
        return shutil.which(CARGO) is not None

    def list_installed(self, on_done: Callable[[list[InstalledPackage]], None]) -> None:
        argv = [CARGO, "install", "--list"]

        def _on_result(result: CommandResult) -> None:
            on_done(_parse_list(result.stdout) if result.ok else [])

        CommandRunner.run_async(argv, _on_result)

    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        argv = [CARGO, "uninstall", identifier]
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)
