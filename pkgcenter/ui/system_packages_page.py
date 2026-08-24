"""Full RPM package view, with a toggle between explicitly-installed leaf
packages and the complete installed set (including dependencies).
"""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..backends.rpm_dnf import RpmDnfBackend
from ..command_runner import CommandResult
from ..dependency_graph import DependencyGraph
from ..desktop_index import DesktopIndex
from ..models import InstalledPackage
from .applications_page import _human_size, removal_warning
from .package_detail_dialog import PackageDetailDialog
from .widgets.busy_overlay import ToastReporter
from .widgets.confirm_dialog import confirm_destructive
from .widgets.package_list_view import PackageListView, PackageRow


class SystemPackagesPage(Gtk.Box):
    def __init__(
        self,
        rpm_backend: RpmDnfBackend,
        desktop_index: DesktopIndex,
        toaster: ToastReporter,
        graph: DependencyGraph,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._rpm = rpm_backend
        self._index = desktop_index
        self._toaster = toaster
        self._graph = graph
        self._leaves_only = True

        toggle_row = Adw.ActionRow(
            title="Show dependencies",
            subtitle="Include packages installed automatically to satisfy other packages",
        )
        self._toggle = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._toggle.connect("notify::active", self._on_toggle)
        toggle_row.add_suffix(self._toggle)

        toggle_group = Adw.PreferencesGroup()
        toggle_group.add(toggle_row)
        toggle_group.set_margin_top(12)
        toggle_group.set_margin_start(12)
        toggle_group.set_margin_end(12)
        self.append(toggle_group)

        self.list_view = PackageListView(
            on_uninstall=self._on_uninstall,
            search_placeholder="Search system packages…",
            on_details=self._on_details,
        )
        self.list_view.set_margin_top(12)
        self.list_view.set_margin_bottom(12)
        self.list_view.set_margin_start(12)
        self.list_view.set_margin_end(12)
        self.append(self.list_view)

    def _on_toggle(self, switch: Gtk.Switch, _pspec) -> None:
        self._leaves_only = not switch.get_active()
        self.refresh()

    def refresh(self) -> None:
        def _on_packages(packages: list[InstalledPackage]) -> None:
            rows = []
            for pkg in packages:
                entry = self._index.entry_for_package(pkg.name)
                size = _human_size(pkg.size_bytes)
                subtitle = pkg.version
                if pkg.from_repo:
                    subtitle += f" · {pkg.from_repo}"
                if size:
                    subtitle += f" · {size}"
                info = self._graph.get(pkg.name)
                if info is not None:
                    subtitle += f" · {info.downstream_count} depend on it"
                    if info.summary:
                        subtitle += f" · {info.summary}"
                rows.append(
                    PackageRow(
                        payload=pkg,
                        kind="rpm",
                        uninstall_id=pkg.name,
                        display_name=pkg.name,
                        subtitle=subtitle,
                        icon_name=entry.icon if entry else None,
                        show_permissions=False,
                        criticality=info.criticality if info else None,
                        criticality_label=info.criticality_label if info else "",
                    )
                )
            self.list_view.set_items(rows)

        self._rpm.list_installed(_on_packages, leaves_only=self._leaves_only)

    def _on_details(self, row: PackageRow) -> None:
        pkg: InstalledPackage = row.payload
        info = self._graph.get(pkg.name)
        PackageDetailDialog(
            title=pkg.name,
            subtitle=f"{pkg.version} · {pkg.from_repo or 'installed'}",
            summary=info.summary if info else "",
            info=info,
            graph=self._graph,
        ).present(self)

    def _on_uninstall(self, row: PackageRow) -> None:
        pkg: InstalledPackage = row.payload

        def _do() -> None:
            def _on_done(result: CommandResult) -> None:
                self._toaster.report(result, f"Uninstalled {pkg.name}.", "Uninstall failed")
                if result.ok:
                    self.list_view.remove_by_uninstall_id(row.uninstall_id)

            self._rpm.remove(pkg.name, _on_done)

        confirm_destructive(
            self,
            f"Uninstall {pkg.name}?",
            "Removing a system package may also remove anything that depends on "
            "it. You will be asked to authenticate."
            + removal_warning(self._graph.get(pkg.name)),
            _do,
        )
