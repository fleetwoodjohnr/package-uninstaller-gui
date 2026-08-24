"""Resolves package/app-id -> friendly display name + icon using desktop
entries, built once at startup (never per-row -- 2500+ individual lookups
would be unusably slow).

Uses Gio.AppInfo.get_all() rather than hand-globbing/parsing .desktop files:
it already merges every XDG_DATA_DIRS location (verified live: this
session's XDG_DATA_DIRS includes both the system applications dir and both
flatpak export dirs), handles desktop-entry localization, and hands back a
ready-to-use Gio.Icon per entry.

For Flatpak apps the exported .desktop basename already equals the app ID,
so that side is a direct dict lookup. For RPM packages there's no such
shortcut -- ownership has to be resolved via `rpm -qf`, and it's done with
ONE batched call across every system .desktop path rather than one call per
file. `rpm -qf` doesn't echo back which input path a given output line
belongs to when some paths error out (e.g. entries with no owning package,
or ones already resolved via the flatpak-export shortcut) -- but it does
preserve input order for the paths that *do* resolve, and reports the exact
failed paths on stderr, so the two can be zipped back together correctly by
subtracting the reported failures from the ordered input list.
"""
from __future__ import annotations

import re
import subprocess
import threading
from typing import Callable, Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .models import DesktopEntry

RPM = "/usr/bin/rpm"
_STDERR_FAILED_FILE_RE = re.compile(r"^error: file (.+?): ")


class DesktopIndex:
    def __init__(self) -> None:
        self._by_app_id: dict[str, DesktopEntry] = {}
        self._by_package: dict[str, DesktopEntry] = {}

    def entry_for_flatpak(self, app_id: str) -> Optional[DesktopEntry]:
        return self._by_app_id.get(app_id)

    def entry_for_package(self, package_name: str) -> Optional[DesktopEntry]:
        return self._by_package.get(package_name)

    def build_async(self, on_done: Callable[[], None]) -> None:
        """Runs the (mostly rpm -qf subprocess) work on a worker thread and
        marshals completion back onto the GTK main loop via GLib.idle_add,
        so app startup never blocks on it.
        """

        def _worker() -> None:
            self.build()
            GLib.idle_add(on_done)

        threading.Thread(target=_worker, daemon=True).start()

    def build(self) -> None:
        infos = Gio.AppInfo.get_all()

        rpm_candidates: list[tuple[str, DesktopEntry]] = []  # (filename, entry)

        for info in infos:
            if not isinstance(info, Gio.DesktopAppInfo):
                continue
            desktop_id = info.get_id() or ""
            filename = info.get_filename() or ""
            icon = info.get_icon()
            entry = DesktopEntry(
                id=desktop_id,
                name=info.get_display_name() or desktop_id,
                icon=icon.to_string() if icon else None,
            )

            if "/flatpak/exports/share/applications/" in filename and desktop_id.endswith(
                ".desktop"
            ):
                app_id = desktop_id[: -len(".desktop")]
                self._by_app_id[app_id] = entry
                continue

            if filename:
                rpm_candidates.append((filename, entry))

        if rpm_candidates:
            self._resolve_rpm_owners(rpm_candidates)

    def _resolve_rpm_owners(self, candidates: list[tuple[str, DesktopEntry]]) -> None:
        paths = [path for path, _entry in candidates]
        try:
            proc = subprocess.run(
                [RPM, "-qf", "--queryformat", "%{NAME}\n", *paths],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return

        failed_paths: set[str] = set()
        for line in proc.stderr.splitlines():
            match = _STDERR_FAILED_FILE_RE.match(line)
            if match:
                failed_paths.add(match.group(1))

        resolved_paths = [p for p in paths if p not in failed_paths]
        names = [n for n in proc.stdout.splitlines() if n]

        if len(resolved_paths) != len(names):
            return  # defensive: don't guess at a mismatched correlation

        path_to_entry = dict(candidates)
        for path, package_name in zip(resolved_paths, names):
            self._by_package[package_name] = path_to_entry[path]
