"""Globally-installed npm packages. Not installed on this machine at plan
time, so elevation needs can't be verified against a real default prefix
here. Rather than assume, this backend checks `npm config get prefix` at
mutate time and only wraps the uninstall in pkexec if that prefix falls
outside the user's home directory (a system-wide install, e.g.
/usr/lib/node_modules) -- a user-configured prefix under $HOME needs none.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from ..command_runner import CommandResult, CommandRunner
from ..models import InstalledPackage
from .base import PackageBackend

NPM = "npm"
PKEXEC = "/usr/bin/pkexec"


class NpmGlobalBackend(PackageBackend):
    name = "npm"
    label = "Npm (global)"

    def is_available(self) -> bool:
        return shutil.which(NPM) is not None

    def list_installed(self, on_done: Callable[[list[InstalledPackage]], None]) -> None:
        argv = [NPM, "ls", "-g", "--json", "--depth=0"]

        def _on_result(result: CommandResult) -> None:
            if not result.stdout:
                on_done([])
                return
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                on_done([])
                return
            packages = [
                InstalledPackage(
                    name=pkg_name,
                    version=info.get("version", ""),
                    size_bytes=0,
                    source="npm",
                    user_installed=True,
                )
                for pkg_name, info in data.get("dependencies", {}).items()
            ]
            on_done(packages)

        CommandRunner.run_async(argv, _on_result)

    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        def _on_prefix(result: CommandResult) -> None:
            prefix = result.stdout.strip()
            needs_root = bool(prefix) and not prefix.startswith(str(Path.home()))
            argv = [NPM, "uninstall", "-g", identifier]
            if needs_root:
                argv = [PKEXEC, shutil.which(NPM) or NPM, "uninstall", "-g", identifier]
            CommandRunner.run_streaming(argv, lambda _line: None, on_done)

        CommandRunner.run_async([NPM, "config", "get", "prefix"], _on_prefix)
