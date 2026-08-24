"""Main window: sidebar navigation across the four sections."""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from .backends.cargo_backend import CargoBackend
from .backends.flatpak import FlatpakBackend
from .backends.npm_global import NpmGlobalBackend
from .backends.pip_user import PipUserBackend
from .backends.pipx_backend import PipxBackend
from .backends.rpm_dnf import RpmDnfBackend
from .dependency_graph import DependencyGraph
from .desktop_index import DesktopIndex
from .models import FlatpakApp
from .ui.applications_page import ApplicationsPage
from .ui.dev_tools_page import DevToolsPage
from .ui.install_search_dialog import InstallSearchDialog
from .ui.permissions_page import PermissionsPage
from .ui.system_packages_page import SystemPackagesPage
from .ui.widgets.busy_overlay import ToastReporter

_SECTIONS = [
    ("applications", "Applications", "view-grid-symbolic"),
    ("system", "System Packages", "package-x-generic-symbolic"),
    ("permissions", "Sandbox Permissions", "security-high-symbolic"),
    ("devtools", "Developer Tools", "applications-engineering-symbolic"),
]


class PkgCenterWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Package Center")
        self.set_default_size(1100, 760)

        self._rpm = RpmDnfBackend()
        self._flatpak = FlatpakBackend()
        self._dev_backends = [
            PipUserBackend(),
            PipxBackend(),
            CargoBackend(),
            NpmGlobalBackend(),
        ]
        self._index = DesktopIndex()
        self._graph = DependencyGraph()

        self._toast_overlay = Adw.ToastOverlay()
        self._toaster = ToastReporter(self._toast_overlay)

        self._applications_page = ApplicationsPage(
            self._rpm,
            self._flatpak,
            self._index,
            self._toaster,
            self._show_permissions_for,
            self._graph,
        )
        self._system_page = SystemPackagesPage(
            self._rpm, self._index, self._toaster, self._graph
        )
        self._permissions_page = PermissionsPage(self._flatpak, self._toaster)
        self._devtools_page = DevToolsPage(self._dev_backends, self._toaster)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._applications_page, "applications")
        self._stack.add_named(self._system_page, "system")
        self._stack.add_named(self._permissions_page, "permissions")
        self._stack.add_named(self._devtools_page, "devtools")

        sidebar_list = Gtk.ListBox()
        sidebar_list.add_css_class("navigation-sidebar")
        sidebar_list.connect("row-selected", self._on_section_selected)
        for key, label, icon in _SECTIONS:
            row = Adw.ActionRow(title=label)
            row.set_icon_name(icon)
            row.section_key = key
            sidebar_list.append(row)
        self._sidebar_list = sidebar_list

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Adw.WindowTitle(title="Package Center"))
        install_btn = Gtk.Button(icon_name="system-software-install-symbolic")
        install_btn.set_tooltip_text("Install new software")
        install_btn.connect("clicked", self._on_install_clicked)
        sidebar_header.pack_end(install_btn)

        sidebar_toolbar = Adw.ToolbarView()
        sidebar_toolbar.add_top_bar(sidebar_header)
        sidebar_scroller = Gtk.ScrolledWindow(vexpand=True)
        sidebar_scroller.set_child(sidebar_list)
        sidebar_toolbar.set_content(sidebar_scroller)

        content_header = Adw.HeaderBar()
        self._content_title = Adw.WindowTitle(title="Applications")
        content_header.set_title_widget(self._content_title)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh")
        refresh_btn.connect("clicked", lambda _b: self.refresh_all())
        content_header.pack_end(refresh_btn)

        content_toolbar = Adw.ToolbarView()
        content_toolbar.add_top_bar(content_header)
        content_toolbar.set_content(self._stack)

        split = Adw.NavigationSplitView()
        split.set_sidebar(Adw.NavigationPage(child=sidebar_toolbar, title="Package Center"))
        split.set_content(Adw.NavigationPage(child=content_toolbar, title="Applications"))
        split.set_min_sidebar_width(240)
        split.set_max_sidebar_width(280)

        self._toast_overlay.set_child(split)
        self.set_content(self._toast_overlay)

        sidebar_list.select_row(sidebar_list.get_row_at_index(0))

        # Package lists load immediately. Two enrichment passes land later
        # and re-render the RPM rows: the desktop-entry index (friendly
        # names and icons) and the dependency graph (descriptions and
        # criticality). Both shell out to rpm and take a few seconds.
        self.refresh_all()
        self._index.build_async(self._on_enrichment_ready)
        self._graph.build_async(self._on_enrichment_ready)

    def _on_enrichment_ready(self) -> None:
        self._applications_page.refresh()
        self._system_page.refresh()
        return False

    def _on_section_selected(self, _list_box: Gtk.ListBox, row) -> None:
        if row is None:
            return
        self._stack.set_visible_child_name(row.section_key)
        self._content_title.set_title(row.get_title())

    def _show_permissions_for(self, app: FlatpakApp) -> None:
        self._sidebar_list.select_row(self._sidebar_list.get_row_at_index(2))
        self._permissions_page.select_app(app.app_id)

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        dialog = InstallSearchDialog(
            self._rpm, self._flatpak, self._toaster, self.refresh_all
        )
        dialog.present(self)

    def refresh_all(self) -> None:
        self._applications_page.refresh()
        self._system_page.refresh()
        self._permissions_page.refresh()
        self._devtools_page.refresh()
