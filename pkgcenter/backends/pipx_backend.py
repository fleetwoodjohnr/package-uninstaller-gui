"""pipx-managed CLI tools. Not installed on this machine at plan time, so
this targets pipx's documented `--json` schema rather than a live-verified
one: {"venvs": {"<pkg>": {"metadata": {"main_package": {"package": ...,
"package_version": ...}}}}}. Installs go to ~/.local/pipx -- no elevation.
"""
from __future__ import annotations

import json
import shutil
from typing import Callable

from ..command_runner import CommandResult, CommandRunner
from ..models import InstalledPackage
from .base import PackageBackend

PIPX = "pipx"


class PipxBackend(PackageBackend):
    name = "pipx"
    label = "Pipx"

    def is_available(self) -> bool:
        return shutil.which(PIPX) is not None

    def list_installed(self, on_done: Callable[[list[InstalledPackage]], None]) -> None:
        argv = [PIPX, "list", "--json"]

        def _on_result(result: CommandResult) -> None:
            if not result.ok:
                on_done([])
                return
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                on_done([])
                return
            packages: list[InstalledPackage] = []
            for pkg_name, venv in data.get("venvs", {}).items():
                main = venv.get("metadata", {}).get("main_package", {})
                version = main.get("package_version", "")
                packages.append(
                    InstalledPackage(
                        name=pkg_name,
                        version=version,
                        size_bytes=0,
                        source="pipx",
                        user_installed=True,
                    )
                )
            on_done(packages)

        CommandRunner.run_async(argv, _on_result)

    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        argv = [PIPX, "uninstall", identifier]
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)
