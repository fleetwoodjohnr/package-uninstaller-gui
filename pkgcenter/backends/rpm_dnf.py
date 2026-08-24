"""RPM/DNF backend: local metadata via `dnf5 repoquery`, remote catalog
search via `dnf5 search`, mutations via `pkexec dnf5 install/remove`.

`dnf5 repoquery` has no combined "leaf packages, but full metadata for
everything" mode -- `--userinstalled` and `--installed` are mutually
exclusive (verified live), so leaf and full listings are two separate calls,
not one filtered call.
"""
from __future__ import annotations

import re
from typing import Callable

from ..command_runner import CommandResult, CommandRunner
from ..models import InstalledPackage, SearchResult
from ..task_queue import BusyError, SingleSlotQueue
from .base import PackageBackend

DNF5 = "/usr/bin/dnf5"
PKEXEC = "/usr/bin/pkexec"

_QUERYFORMAT = "%{name}\t%{version}\t%{installsize}\t%{from_repo}\t%{installtime}\n"

# Packages installed from the install media or a local rpm report a
# transaction-hash repo id rather than a real repo name -- meaningless to
# show in the UI.
_OPAQUE_REPO_RE = re.compile(r"^[0-9a-f]{32,}$")


def _clean_repo(value: str) -> str | None:
    if not value or value.startswith("@") or _OPAQUE_REPO_RE.match(value):
        return None
    return value


def _parse_repoquery(stdout: str, user_installed: bool) -> list[InstalledPackage]:
    packages: list[InstalledPackage] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name, version, size, from_repo, install_time = parts[:5]
        try:
            size_bytes = int(size)
        except ValueError:
            size_bytes = 0
        try:
            install_time_val = int(install_time) if install_time else None
        except ValueError:
            install_time_val = None
        packages.append(
            InstalledPackage(
                name=name,
                version=version,
                size_bytes=size_bytes,
                user_installed=user_installed,
                from_repo=_clean_repo(from_repo),
                install_time=install_time_val,
            )
        )
    return packages


def _parse_search(stdout: str) -> list[SearchResult]:
    """`dnf5 search` output is text, not structured:

        Matched fields: name (exact)
         gimp.x86_64	GNU Image Manipulation Program
        Matched fields: name, summary
         gimp-data-extras.noarch	Extra files for GIMP

    Header lines start with "Matched fields:" (no leading indent); result
    lines are indented and are "name.arch<TAB>summary".
    """
    results: list[SearchResult] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("Matched fields:"):
            continue
        stripped = line.strip()
        if "\t" not in stripped:
            continue
        name_arch, summary = stripped.split("\t", 1)
        name = name_arch.rsplit(".", 1)[0] if "." in name_arch else name_arch
        if name in seen:
            continue
        seen.add(name)
        results.append(
            SearchResult(
                source="rpm",
                id=name,
                display_name=name,
                summary=summary.strip() or None,
            )
        )
    return results


class RpmDnfBackend(PackageBackend):
    name = "rpm"
    label = "System Packages (DNF)"

    def __init__(self) -> None:
        self._queue = SingleSlotQueue()

    def is_available(self) -> bool:
        return True

    def list_installed(
        self,
        on_done: Callable[[list[InstalledPackage]], None],
        leaves_only: bool = True,
    ) -> None:
        flag = "--userinstalled" if leaves_only else "--installed"
        argv = [DNF5, "repoquery", flag, "--queryformat", _QUERYFORMAT]

        def _on_result(result: CommandResult) -> None:
            if not result.ok:
                on_done([])
                return
            on_done(_parse_repoquery(result.stdout, user_installed=leaves_only))

        CommandRunner.run_async(argv, _on_result)

    def supports_search(self) -> bool:
        return True

    def search(self, term: str, on_done: Callable[[list[SearchResult]], None]) -> None:
        argv = [DNF5, "search", term]

        def _on_result(result: CommandResult) -> None:
            if not result.ok:
                on_done([])
                return
            on_done(_parse_search(result.stdout))

        CommandRunner.run_async(argv, _on_result)

    def install(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        self._mutate(["install", "-y", identifier], on_done)

    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        self._mutate(["remove", "-y", identifier], on_done)

    def _mutate(self, dnf_args: list[str], on_done: Callable[[CommandResult], None]) -> None:
        argv = [PKEXEC, DNF5, *dnf_args]

        def _start(release: Callable[[], None]) -> None:
            def _on_line(_line: str) -> None:
                pass  # UI layer can subclass/wrap for live progress if needed

            def _on_done(result: CommandResult) -> None:
                release()
                on_done(result)

            CommandRunner.run_streaming(argv, _on_line, _on_done)

        try:
            self._queue.run(f"dnf5 {dnf_args[0]} {dnf_args[-1]}", _start)
        except BusyError as exc:
            on_done(CommandResult(ok=False, returncode=-1, stdout="", stderr=str(exc)))
