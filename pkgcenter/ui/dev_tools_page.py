"""Developer tooling installed outside the system package manager
(pip --user, pipx, cargo, npm -g).

Only backends actually present on the machine get a tab -- probing happens
at startup and again on Refresh, so installing pipx/cargo/npm later surfaces
its tab without restarting the app.
"""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..backends.base import PackageBackend
from ..command_runner import CommandResult
from ..models import InstalledPackage
from .widgets.busy_overlay import ToastReporter
from .widgets.confirm_dialog import confirm_destructive
from .widgets.package_list_view import PackageListView, PackageRow


class DevToolsPage(Gtk.Box):
    def __init__(self, backends: list[PackageBackend], toaster: ToastReporter) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._backends = backends
        self._toaster = toaster
        self._views: dict[str, PackageListView] = {}

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_top(12)
        header.set_margin_start(12)
        header.set_margin_end(12)

        self._switcher = Adw.ViewSwitcher()
        self._switcher.set_hexpand(True)
        header.append(self._switcher)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.add_css_class("flat")
        # Keeps the button right-aligned when the switcher is hidden
        # (a hidden widget claims no space in a GtkBox).
        refresh_btn.set_hexpand(True)
        refresh_btn.set_halign(Gtk.Align.END)
        refresh_btn.set_tooltip_text("Re-check which developer tools are installed")
        refresh_btn.connect("clicked", lambda _b: self.refresh())
        header.append(refresh_btn)
        self.append(header)

        self._stack = Adw.ViewStack(vexpand=True)
        self._switcher.set_stack(self._stack)
        self.append(self._stack)

        self._empty = Adw.StatusPage(
            title="No developer tools found",
            description=(
                "Nothing installed via pip --user, pipx, cargo, or npm -g was "
                "detected. Install one and press refresh."
            ),
            icon_name="applications-engineering-symbolic",
        )
        self._empty.set_vexpand(True)
        self.append(self._empty)

    def refresh(self) -> None:
        available = [b for b in self._backends if b.is_available()]

        child = self._stack.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._stack.remove(child)
            child = nxt
        self._views.clear()

        has_any = bool(available)
        self._stack.set_visible(has_any)
        # A switcher showing a single tab is just a confusing empty bar.
        self._switcher.set_visible(len(available) > 1)
        self._empty.set_visible(not has_any)
        if not has_any:
            return

        for backend in available:
            view = PackageListView(
                on_uninstall=lambda row, b=backend: self._on_uninstall(b, row),
                search_placeholder=f"Search {backend.label}…",
            )
            view.set_margin_top(12)
            view.set_margin_bottom(12)
            view.set_margin_start(12)
            view.set_margin_end(12)
            page = self._stack.add_titled(view, backend.name, backend.label)
            page.set_icon_name("application-x-addon-symbolic")
            self._views[backend.name] = view
            self._load_backend(backend, view)

    def _load_backend(self, backend: PackageBackend, view: PackageListView) -> None:
        def _on_packages(packages: list[InstalledPackage]) -> None:
            rows = [
                PackageRow(
                    payload=pkg,
                    kind=backend.name,
                    uninstall_id=pkg.name,
                    display_name=pkg.name,
                    subtitle=f"{backend.label} · {pkg.version}" if pkg.version else backend.label,
                    icon_name="application-x-addon-symbolic",
                    show_permissions=False,
                )
                for pkg in packages
            ]
            view.set_items(rows)

        backend.list_installed(_on_packages)

    def _on_uninstall(self, backend: PackageBackend, row: PackageRow) -> None:
        def _do() -> None:
            def _on_done(result: CommandResult) -> None:
                self._toaster.report(result, f"Uninstalled {row.display_name}.", "Uninstall failed")
                if result.ok:
                    view = self._views.get(backend.name)
                    if view is not None:
                        view.remove_by_uninstall_id(row.uninstall_id)

            backend.remove(row.uninstall_id, _on_done)

        confirm_destructive(
            self,
            f"Uninstall {row.display_name}?",
            f"This removes the package from your {backend.label} installation.",
            _do,
        )
