"""Merged view of user-installed RPM packages and Flatpak apps -- the
"everything I actually installed" list, as opposed to the full dependency
closure shown on the System Packages page.
"""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..backends.flatpak import FlatpakBackend
from ..backends.rpm_dnf import RpmDnfBackend
from ..command_runner import CommandResult
from ..dependency_graph import CRITICAL, HIGH, DependencyGraph
from ..desktop_index import DesktopIndex
from ..models import FlatpakApp, InstalledPackage
from .package_detail_dialog import PackageDetailDialog
from .widgets.busy_overlay import ToastReporter
from .widgets.confirm_dialog import confirm_destructive
from .widgets.package_list_view import PackageListView, PackageRow


def removal_warning(info) -> str:
    """Extra sentence appended to an uninstall confirmation, spelling out
    what else would be affected.
    """
    if info is None:
        return ""
    if info.protected:
        return (
            "\n\nThis package is marked PROTECTED by the system. Removing it "
            "can leave the machine unbootable."
        )
    if info.downstream_count == 0:
        return "\n\nNothing else installed depends on it."
    return (
        f"\n\n{info.downstream_count} other installed package(s) depend on it, "
        f"{len(info.direct_dependents)} of them directly."
    )


def _human_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


class ApplicationsPage(Gtk.Box):
    def __init__(
        self,
        rpm_backend: RpmDnfBackend,
        flatpak_backend: FlatpakBackend,
        desktop_index: DesktopIndex,
        toaster: ToastReporter,
        on_show_permissions: Callable[[FlatpakApp], None],
        graph: DependencyGraph,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._rpm = rpm_backend
        self._flatpak = flatpak_backend
        self._index = desktop_index
        self._toaster = toaster
        self._on_show_permissions = on_show_permissions
        self._graph = graph

        self._rpm_rows: list[PackageRow] = []
        self._flatpak_rows: list[PackageRow] = []
        self._rpm_loaded = False
        self._flatpak_loaded = False
        self._runtime_map: dict[str, list[str]] = {}

        self.list_view = PackageListView(
            on_uninstall=self._on_uninstall,
            on_permissions=self._on_permissions,
            search_placeholder="Search installed applications…",
            on_details=self._on_details,
        )
        self.list_view.set_margin_top(12)
        self.list_view.set_margin_bottom(12)
        self.list_view.set_margin_start(12)
        self.list_view.set_margin_end(12)
        self.append(self.list_view)

    def refresh(self) -> None:
        self._rpm_loaded = False
        self._flatpak_loaded = False

        def _on_rpm(packages: list[InstalledPackage]) -> None:
            rows = []
            for pkg in packages:
                entry = self._index.entry_for_package(pkg.name)
                display = entry.name if entry else pkg.name
                size = _human_size(pkg.size_bytes)
                # Distinct packages can share a .desktop display name
                # (several gnome-shell-extension-* packages all read
                # "Extensions"), so keep the package name visible whenever
                # it isn't already the title.
                subtitle = "RPM · " + (f"{pkg.name} · " if display != pkg.name else "")
                subtitle += pkg.version
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
                        display_name=display,
                        subtitle=subtitle,
                        icon_name=entry.icon if entry else None,
                        show_permissions=False,
                        criticality=info.criticality if info else None,
                        criticality_label=info.criticality_label if info else "",
                    )
                )
            self._rpm_rows = rows
            self._rpm_loaded = True
            self._publish()

        def _on_flatpak(apps: list[FlatpakApp]) -> None:
            runtime_map: dict[str, list[str]] = {}
            for app in apps:
                if app.runtime:
                    runtime_map.setdefault(app.runtime, []).append(app.app_id)
            self._runtime_map = runtime_map

            rows = []
            for app in apps:
                entry = self._index.entry_for_flatpak(app.app_id)
                display = entry.name if entry else app.label
                subtitle = f"Flatpak · {app.version or app.branch} · {app.install_scope}"
                if app.runtime:
                    subtitle += f" · uses {app.runtime.split('/')[0]}"
                rows.append(
                    PackageRow(
                        payload=app,
                        kind="flatpak",
                        uninstall_id=app.app_id,
                        display_name=display,
                        subtitle=subtitle,
                        icon_name=entry.icon if entry else app.app_id,
                        show_permissions=True,
                        # A Flatpak app is always a leaf: it is sandboxed and
                        # nothing else installed links against it.
                        criticality="low",
                        criticality_label="Low",
                    )
                )
            self._flatpak_rows = rows
            self._flatpak_loaded = True
            self._publish()

        self._rpm.list_installed(_on_rpm, leaves_only=True)
        self._flatpak.list_installed(_on_flatpak)

    def _publish(self) -> None:
        if not (self._rpm_loaded and self._flatpak_loaded):
            return
        self.list_view.set_items([*self._flatpak_rows, *self._rpm_rows])

    def _on_permissions(self, row: PackageRow) -> None:
        if row.kind == "flatpak":
            self._on_show_permissions(row.payload)

    def _on_details(self, row: PackageRow) -> None:
        if row.kind == "flatpak":
            app: FlatpakApp = row.payload
            siblings = self._runtime_map.get(app.runtime or "", [])
            dialog = PackageDetailDialog(
                title=row.display_name,
                subtitle=app.app_id,
                summary=f"Sandboxed Flatpak application from {app.origin}.",
                flatpak_app=app,
                runtime_siblings=siblings,
            )
        else:
            pkg: InstalledPackage = row.payload
            info = self._graph.get(pkg.name)
            dialog = PackageDetailDialog(
                title=row.display_name,
                subtitle=f"{pkg.name} · {pkg.version}",
                summary=info.summary if info else "",
                info=info,
                graph=self._graph,
            )
        dialog.present(self)

    def _on_uninstall(self, row: PackageRow) -> None:
        if row.kind == "flatpak":
            app: FlatpakApp = row.payload
            heading = f"Uninstall {row.display_name}?"
            body = (
                f"This removes the Flatpak app {app.app_id} "
                f"({app.install_scope} installation) and its data stays in "
                "~/.var/app unless you remove it separately."
            )

            def _do() -> None:
                def _on_done(result: CommandResult) -> None:
                    self._toaster.report(
                        result, f"Uninstalled {row.display_name}.", "Uninstall failed"
                    )
                    if result.ok:
                        self.list_view.remove_by_uninstall_id(row.uninstall_id)

                self._flatpak.remove(app.app_id, _on_done, scope=app.install_scope)

        else:
            pkg: InstalledPackage = row.payload
            info = self._graph.get(pkg.name)
            heading = f"Uninstall {pkg.name}?"
            body = (
                "This runs a system package removal, which may also remove "
                "packages that depend on it. You will be asked to authenticate."
                + removal_warning(info)
            )

            def _do() -> None:
                def _on_done(result: CommandResult) -> None:
                    self._toaster.report(
                        result, f"Uninstalled {pkg.name}.", "Uninstall failed"
                    )
                    if result.ok:
                        self.list_view.remove_by_uninstall_id(row.uninstall_id)

                self._rpm.remove(pkg.name, _on_done)

        confirm_destructive(self, heading, body, _do)
