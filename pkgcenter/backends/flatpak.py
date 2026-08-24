"""Flatpak backend: app list/search/install/uninstall plus the three-state
sandbox permission model (baseline / delta / effective).

Install defaults to --user scope (no polkit needed at all); uninstall and
system-scope installs let flatpak's own flatpak-system-helper show its
native polkit prompt -- these are never wrapped in pkexec ourselves, since
that would run flatpak as root with no session context and break its own
privilege model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal, Optional

from ..command_runner import CommandResult, CommandRunner
from ..models import FlatpakApp, PermissionContext, SearchResult
from ..permissions.override_parser import parse_context_text
from ..permissions.permission_diff import build_override_argv, build_reset_argv
from .base import PackageBackend

FLATPAK = "flatpak"

_LIST_COLUMNS = "application,name,version,branch,origin,installation,runtime"
_SEARCH_COLUMNS = "application,name,version,branch,remotes"

_USER_OVERRIDES_DIR = Path.home() / ".local/share/flatpak/overrides"
_SYSTEM_OVERRIDES_DIR = Path("/var/lib/flatpak/overrides")


def _parse_list(stdout: str) -> list[FlatpakApp]:
    apps: list[FlatpakApp] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        app_id, name, version, branch, origin, installation = parts[:6]
        runtime = parts[6] if len(parts) > 6 else ""
        scope: Literal["user", "system"] = "user" if installation == "user" else "system"
        apps.append(
            FlatpakApp(
                app_id=app_id,
                name=name,
                version=version,
                branch=branch,
                origin=origin,
                install_scope=scope,
                runtime=runtime or None,
            )
        )
    return apps


def _parse_search(stdout: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        app_id, name, _version, _branch, remotes = parts[:5]
        if app_id in seen:
            continue
        seen.add(app_id)
        origin = remotes.split(",")[0] if remotes else None
        results.append(
            SearchResult(
                source="flatpak",
                id=app_id,
                display_name=name or app_id,
                summary=None,
                origin=origin,
            )
        )
    return results


class FlatpakBackend(PackageBackend):
    name = "flatpak"
    label = "Flatpak Apps"

    def is_available(self) -> bool:
        return True

    def list_installed(self, on_done: Callable[[list[FlatpakApp]], None]) -> None:
        argv = [FLATPAK, "list", "--app", f"--columns={_LIST_COLUMNS}"]

        def _on_result(result: CommandResult) -> None:
            on_done(_parse_list(result.stdout) if result.ok else [])

        CommandRunner.run_async(argv, _on_result)

    def supports_search(self) -> bool:
        return True

    def search(self, term: str, on_done: Callable[[list[SearchResult]], None]) -> None:
        argv = [FLATPAK, "search", term, f"--columns={_SEARCH_COLUMNS}"]

        def _on_result(result: CommandResult) -> None:
            on_done(_parse_search(result.stdout) if result.ok else [])

        CommandRunner.run_async(argv, _on_result)

    def list_remotes(self, on_done: Callable[[dict[str, str]], None]) -> None:
        """Maps remote name -> the scope it is configured in."""
        argv = [FLATPAK, "remotes", "--columns=name,options"]

        def _on_result(result: CommandResult) -> None:
            remotes: dict[str, str] = {}
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                name, options = parts[0], parts[1]
                remotes[name] = "user" if "user" in options.split(",") else "system"
            on_done(remotes)

        CommandRunner.run_async(argv, _on_result)

    def install(
        self,
        identifier: str,
        on_done: Callable[[CommandResult], None],
        remote: str = "flathub",
        scope: Optional[Literal["user", "system"]] = None,
    ) -> None:
        """Installs from `remote`, defaulting to the scope that remote is
        actually configured in.

        A --user install cannot resolve a remote that only exists
        system-wide ("No remote refs found for 'flathub'"), which is the
        case for every remote on a stock Fedora Workstation -- so the
        remote's own scope decides, not a blanket --user preference.
        """

        def _do_install(resolved_scope: str) -> None:
            scope_flag = "--user" if resolved_scope == "user" else "--system"
            argv = [FLATPAK, "install", "-y", scope_flag, remote, identifier]
            CommandRunner.run_streaming(argv, lambda _line: None, on_done)

        if scope is not None:
            _do_install(scope)
            return

        self.list_remotes(lambda remotes: _do_install(remotes.get(remote, "system")))

    def remove(
        self,
        identifier: str,
        on_done: Callable[[CommandResult], None],
        scope: Literal["user", "system"] = "system",
    ) -> None:
        scope_flag = "--user" if scope == "user" else "--system"
        argv = [FLATPAK, "uninstall", "-y", scope_flag, identifier]
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)

    # -- Permissions -----------------------------------------------------

    def get_baseline(self, app_id: str, on_done: Callable[[PermissionContext], None]) -> None:
        argv = [FLATPAK, "info", "--show-metadata", app_id]

        def _on_result(result: CommandResult) -> None:
            text = result.stdout if result.ok else ""
            on_done(parse_context_text(text, app_id))

        CommandRunner.run_async(argv, _on_result)

    def get_effective(self, app_id: str, on_done: Callable[[PermissionContext], None]) -> None:
        argv = [FLATPAK, "info", "--show-permissions", app_id]

        def _on_result(result: CommandResult) -> None:
            text = result.stdout if result.ok else ""
            on_done(parse_context_text(text, app_id))

        CommandRunner.run_async(argv, _on_result)

    def get_delta(self, app_id: str, scope: Literal["user", "system"] = "user") -> PermissionContext:
        """Reads the local override file directly -- it's a few hundred
        bytes on local disk, cheap enough to read synchronously rather
        than round-tripping through a subprocess.
        """
        overrides_dir = _USER_OVERRIDES_DIR if scope == "user" else _SYSTEM_OVERRIDES_DIR
        path = overrides_dir / app_id
        if not path.exists():
            return PermissionContext(app_id=app_id)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return PermissionContext(app_id=app_id)
        return parse_context_text(text, app_id)

    def apply_permissions(
        self,
        baseline: PermissionContext,
        edited: PermissionContext,
        on_done: Callable[[CommandResult], None],
        scope: Literal["user", "system"] = "user",
    ) -> None:
        argv = build_override_argv(baseline, edited, scope=scope)
        if argv is None:
            on_done(CommandResult(ok=True, returncode=0, stdout="", stderr=""))
            return
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)

    def reset_permissions(
        self,
        app_id: str,
        on_done: Callable[[CommandResult], None],
        scope: Literal["user", "system"] = "user",
    ) -> None:
        argv = build_reset_argv(app_id, scope=scope)
        CommandRunner.run_streaming(argv, lambda _line: None, on_done)
