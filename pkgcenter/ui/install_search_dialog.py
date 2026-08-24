"""Search-and-install across both catalogs at once.

dnf5 and flatpak searches fire concurrently and render independently: a
first-run `dnf5 search` pays a ~10s repo metadata refresh, while `flatpak
search` returns almost immediately, so waiting to show a combined result
set would make the fast half feel broken.
"""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..backends.flatpak import FlatpakBackend
from ..backends.rpm_dnf import RpmDnfBackend
from ..command_runner import CommandResult
from ..models import SearchResult
from .widgets.busy_overlay import ToastReporter


class InstallSearchDialog(Adw.Dialog):
    def __init__(
        self,
        rpm_backend: RpmDnfBackend,
        flatpak_backend: FlatpakBackend,
        toaster: ToastReporter,
        on_installed: Callable[[], None],
    ) -> None:
        super().__init__()
        self.set_title("Install Software")
        self.set_content_width(720)
        self.set_content_height(620)

        self._rpm = rpm_backend
        self._flatpak = flatpak_backend
        self._toaster = toaster
        self._on_installed = on_installed
        self._pending = 0

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        self._entry = Gtk.SearchEntry(placeholder_text="Search DNF repositories and Flathub…")
        self._entry.connect("activate", lambda _e: self._run_search())
        content.append(self._entry)

        self._spinner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._spinner = Gtk.Spinner()
        self._spinner_label = Gtk.Label(label="")
        self._spinner_label.add_css_class("dim-label")
        self._spinner_box.append(self._spinner)
        self._spinner_box.append(self._spinner_label)
        self._spinner_box.set_visible(False)
        content.append(self._spinner_box)

        self._results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self._results_box)
        content.append(scroller)

        self._status = Adw.StatusPage(
            title="Find new software",
            description="Search Fedora's repositories and Flathub in one place.",
            icon_name="system-software-install-symbolic",
        )
        self._results_box.append(self._status)

        toolbar.set_content(content)
        self.set_child(toolbar)

    def _clear_results(self) -> None:
        child = self._results_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._results_box.remove(child)
            child = nxt

    def _run_search(self) -> None:
        term = self._entry.get_text().strip()
        if not term:
            return
        self._clear_results()
        self._pending = 2
        self._spinner_box.set_visible(True)
        self._spinner.start()
        self._spinner_label.set_label("Searching Flathub and DNF repositories…")

        flatpak_group = Adw.PreferencesGroup(title="Flatpak")
        rpm_group = Adw.PreferencesGroup(title="System Packages (DNF)")
        self._results_box.append(flatpak_group)
        self._results_box.append(rpm_group)

        self._flatpak.search(term, lambda results: self._render(results, flatpak_group, "flatpak"))
        self._rpm.search(term, lambda results: self._render(results, rpm_group, "rpm"))

    def _render(self, results: list[SearchResult], group: Adw.PreferencesGroup, kind: str) -> None:
        self._pending -= 1
        if self._pending <= 0:
            self._spinner.stop()
            self._spinner_box.set_visible(False)

        if not results:
            group.add(Adw.ActionRow(title="No matches", subtitle="Nothing found here."))
            return

        for result in results[:40]:
            row = Adw.ActionRow(title=result.display_name)
            subtitle_parts = [p for p in (result.id, result.summary, result.origin) if p]
            row.set_subtitle(" · ".join(subtitle_parts))
            button = Gtk.Button(label="Install")
            button.add_css_class("suggested-action")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, r=result, btn=None: self._install(r))
            row.add_suffix(button)
            group.add(row)

    def _install(self, result: SearchResult) -> None:
        self._toaster.info(f"Installing {result.display_name}…", timeout=0)

        def _on_done(cmd_result: CommandResult) -> None:
            self._toaster.report(
                cmd_result,
                f"Installed {result.display_name}.",
                f"Could not install {result.display_name}",
            )
            if cmd_result.ok:
                self._on_installed()

        if result.source == "flatpak":
            self._flatpak.install(result.id, _on_done, remote=result.origin or "flathub")
        else:
            self._rpm.install(result.id, _on_done)
