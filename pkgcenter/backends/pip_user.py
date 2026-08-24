"""User-site pip packages. `pip3 uninstall` has no --user flag (verified via
`pip3 uninstall --help`) -- it removes whatever it finds on sys.path, which
for a --user install is the user site. No elevation needed either way.
"""
from __future__ import annotations

import json
from typing import Callable

from ..command_runner import CommandResult, CommandRunner
from ..models import InstalledPackage
from .base import PackageBackend

PIP = "pip3"


class PipUserBackend(PackageBackend):
    name = "pip"
    label = "Pip (user)"

    def is_available(self) -> bool:
        return True  # pip3 ships with the system Python on this machine

    def list_installed(self, on_done: Callable[[list[InstalledPackage]], None]) -> None:
        argv = [PIP, "list", "--user", "--format=json"]

        def _on_result(result: CommandResult) -> None:
            if not result.ok:
                on_done([])
                return
            try:
                entries = json.loads(result.stdout)
            except json.JSONDecodeError:
                on_done([])
                return
            packages = [
                InstalledPackage(
                    name=entry["name"],
                    version=entry.get("version", ""),
                    size_bytes=0,
                    source="pip",
                    user_installed=True,
                )
                for entry in entries
            ]
            on_done(packages)

        CommandRunner.run_async(argv, _on_result)

    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        argv = [PIP, "uninstall", "-y", identifier]
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)
