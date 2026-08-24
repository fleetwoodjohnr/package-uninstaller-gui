"""Flatseal-style Flatpak sandbox permission editor.

Left: list of installed Flatpak apps. Right: an Adw.PreferencesPage built
from the merged (baseline + on-disk override) permission context. Edits are
staged in memory and written with a single `flatpak override` call on Apply,
emitting only the flags that actually differ from the app's baseline.
"""
from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..backends.flatpak import FlatpakBackend
from ..command_runner import CommandResult
from ..models import FlatpakApp, PermissionContext
from ..permissions.permission_diff import build_override_argv, merge_baseline_and_delta
from .widgets.busy_overlay import ToastReporter
from .widgets.confirm_dialog import confirm_destructive
from .widgets.list_editor_row import KeyValueListEditorRow, StringListEditorRow
from .widgets.permission_group import (
    KNOWN_DEVICES,
    KNOWN_FEATURES,
    KNOWN_SHARED,
    KNOWN_SOCKETS,
    build_toggle_group,
)

FILESYSTEM_PRESETS = ["home", "host", "xdg-download", "xdg-documents", "xdg-pictures"]


class PermissionsPage(Gtk.Box):
    def __init__(self, backend: FlatpakBackend, toaster: ToastReporter) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._backend = backend
        self._toaster = toaster
        self._apps: list[FlatpakApp] = []
        self._current_app: Optional[FlatpakApp] = None
        self._baseline: Optional[PermissionContext] = None
        self._edited: Optional[PermissionContext] = None
        self._dirty = False

        self._app_list = Gtk.ListBox()
        self._app_list.add_css_class("navigation-sidebar")
        self._app_list.connect("row-selected", self._on_app_selected)

        sidebar_scroller = Gtk.ScrolledWindow(vexpand=True)
        sidebar_scroller.set_child(self._app_list)
        sidebar_scroller.set_size_request(260, -1)
        self.append(sidebar_scroller)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right.set_hexpand(True)

        self._header = Adw.HeaderBar()
        self._header.set_show_end_title_buttons(False)
        self._header.set_show_start_title_buttons(False)
        self._title_widget = Adw.WindowTitle(title="Flatpak Permissions", subtitle="Select an app")
        self._header.set_title_widget(self._title_widget)

        self._reset_btn = Gtk.Button(label="Reset to Defaults")
        self._reset_btn.add_css_class("destructive-action")
        self._reset_btn.set_sensitive(False)
        self._reset_btn.connect("clicked", self._on_reset_clicked)
        self._header.pack_start(self._reset_btn)

        self._apply_btn = Gtk.Button(label="Apply")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.connect("clicked", self._on_apply_clicked)
        self._header.pack_end(self._apply_btn)

        right.append(self._header)

        self._editor_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self._placeholder = Adw.StatusPage(
            title="Flatpak Sandbox Permissions",
            description=(
                "Select an app to review and edit what it can reach outside its sandbox — "
                "display server, devices, filesystem paths, and D-Bus services."
            ),
            icon_name="security-high-symbolic",
        )
        self._editor_container.append(self._placeholder)
        right.append(self._editor_container)

        self.append(right)

    def refresh(self) -> None:
        def _on_apps(apps: list[FlatpakApp]) -> None:
            self._apps = apps
            child = self._app_list.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self._app_list.remove(child)
                child = nxt
            for app in apps:
                row = Adw.ActionRow(title=app.label, subtitle=app.app_id)
                row.set_subtitle_lines(1)
                row.app = app
                self._app_list.append(row)

        self._backend.list_installed(_on_apps)

    def select_app(self, app_id: str) -> None:
        """Jump straight to one app's permissions (used by the Permissions
        button on an app row elsewhere in the UI).
        """
        index = 0
        while True:
            row = self._app_list.get_row_at_index(index)
            if row is None:
                return
            if getattr(row, "app", None) is not None and row.app.app_id == app_id:
                self._app_list.select_row(row)
                return
            index += 1

    def _on_app_selected(self, _list_box: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        if row is None:
            return
        app: FlatpakApp = row.app
        self._current_app = app
        self._title_widget.set_title(app.label)
        self._title_widget.set_subtitle(app.app_id)

        def _on_baseline(baseline: PermissionContext) -> None:
            delta = self._backend.get_delta(app.app_id, scope="user")
            self._baseline = baseline
            self._edited = merge_baseline_and_delta(baseline, delta)
            self._dirty = False
            self._apply_btn.set_sensitive(False)
            self._reset_btn.set_sensitive(True)
            self._build_editor()

        self._backend.get_baseline(app.app_id, _on_baseline)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._apply_btn.set_sensitive(True)

    def _build_editor(self) -> None:
        child = self._editor_container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._editor_container.remove(child)
            child = nxt

        edited = self._edited
        baseline = self._baseline
        if edited is None or baseline is None:
            return

        page = Adw.PreferencesPage()

        group = Adw.PreferencesGroup(
            title="Sandbox Access",
            description="What this app may reach outside its sandbox.",
        )
        group.add(
            build_toggle_group(
                "Sockets", "video-display-symbolic", KNOWN_SOCKETS,
                edited, baseline, "sockets", "nosockets", self._mark_dirty,
            )
        )
        group.add(
            build_toggle_group(
                "Devices", "drive-harddisk-symbolic", KNOWN_DEVICES,
                edited, baseline, "devices", "nodevices", self._mark_dirty,
            )
        )
        group.add(
            build_toggle_group(
                "Shared", "network-wireless-symbolic", KNOWN_SHARED,
                edited, baseline, "shared", "unshared", self._mark_dirty,
            )
        )
        group.add(
            build_toggle_group(
                "Features", "applications-engineering-symbolic", KNOWN_FEATURES,
                edited, baseline, "features", "disallowed_features", self._mark_dirty,
            )
        )
        page.add(group)

        # Group titles are parsed as Pango markup -- a literal "&" here
        # silently blanks the whole label, so avoid it entirely.
        fs_group = Adw.PreferencesGroup(
            title="Filesystem and Persistence",
            description="Host paths this app may read or write.",
        )

        def _fs_add(path: str) -> None:
            suffix = None
            clean = path
            if path.endswith(":ro"):
                clean, suffix = path[:-3], "ro"
            elif path.endswith(":create"):
                clean, suffix = path[:-7], "create"
            edited.filesystems[clean] = suffix
            edited.nofilesystems.discard(clean)
            self._mark_dirty()

        def _fs_remove(path: str) -> None:
            clean = path.split(":")[0]
            edited.filesystems.pop(clean, None)
            if clean in baseline.filesystems:
                edited.nofilesystems.add(clean)
            self._mark_dirty()

        fs_items = [
            f"{path}:{suffix}" if suffix else path
            for path, suffix in edited.filesystems.items()
        ]
        fs_group.add(
            StringListEditorRow(
                "Filesystem Paths", "folder-symbolic", fs_items,
                _fs_add, _fs_remove,
                presets=FILESYSTEM_PRESETS,
                entry_placeholder="Add path (append :ro or :create)",
            )
        )

        def _persist_add(name: str) -> None:
            if name not in edited.persistent:
                edited.persistent.append(name)
            self._mark_dirty()

        def _persist_remove(name: str) -> None:
            if name in edited.persistent:
                edited.persistent.remove(name)
            self._mark_dirty()

        fs_group.add(
            StringListEditorRow(
                "Persistent Directories", "document-save-symbolic",
                list(edited.persistent), _persist_add, _persist_remove,
                entry_placeholder="Add home-relative subpath…",
            )
        )
        page.add(fs_group)

        bus_group = Adw.PreferencesGroup(
            title="D-Bus Services",
            description="Services on the session and system buses this app may talk to.",
        )

        def _session_add(name: str) -> None:
            edited.session_bus[name] = "talk"
            edited.session_bus_no_talk.discard(name)
            self._mark_dirty()

        def _session_remove(name: str) -> None:
            edited.session_bus.pop(name, None)
            if name in baseline.session_bus:
                edited.session_bus_no_talk.add(name)
            self._mark_dirty()

        bus_group.add(
            StringListEditorRow(
                "Session Bus", "network-transmit-receive-symbolic",
                list(edited.session_bus.keys()), _session_add, _session_remove,
                entry_placeholder="Add D-Bus name…",
            )
        )

        def _system_add(name: str) -> None:
            edited.system_bus[name] = "talk"
            edited.system_bus_no_talk.discard(name)
            self._mark_dirty()

        def _system_remove(name: str) -> None:
            edited.system_bus.pop(name, None)
            if name in baseline.system_bus:
                edited.system_bus_no_talk.add(name)
            self._mark_dirty()

        bus_group.add(
            StringListEditorRow(
                "System Bus", "system-run-symbolic",
                list(edited.system_bus.keys()), _system_add, _system_remove,
                entry_placeholder="Add D-Bus name…",
            )
        )
        page.add(bus_group)

        env_group = Adw.PreferencesGroup(title="Environment")

        def _env_add(key: str, value: str) -> None:
            edited.environment[key] = value
            edited.unset_environment.discard(key)
            self._mark_dirty()

        def _env_remove(key: str) -> None:
            edited.environment.pop(key, None)
            if key in baseline.environment:
                edited.unset_environment.add(key)
            self._mark_dirty()

        env_group.add(
            KeyValueListEditorRow(
                "Variables", "utilities-terminal-symbolic",
                dict(edited.environment), _env_add, _env_remove,
            )
        )
        page.add(env_group)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(page)
        self._editor_container.append(scroller)

    def _on_apply_clicked(self, _button: Gtk.Button) -> None:
        if self._baseline is None or self._edited is None or self._current_app is None:
            return
        argv = build_override_argv(self._baseline, self._edited, scope="user")
        if argv is None:
            self._toaster.info("No changes to apply.")
            self._apply_btn.set_sensitive(False)
            return

        def _on_done(result: CommandResult) -> None:
            self._toaster.report(
                result,
                f"Permissions updated for {self._current_app.label}.",
                "Could not update permissions",
            )
            if result.ok:
                self._dirty = False
                self._apply_btn.set_sensitive(False)

        self._backend.apply_permissions(self._baseline, self._edited, _on_done, scope="user")

    def _on_reset_clicked(self, _button: Gtk.Button) -> None:
        app = self._current_app
        if app is None:
            return

        def _do_reset() -> None:
            def _on_done(result: CommandResult) -> None:
                self._toaster.report(
                    result,
                    f"{app.label} reset to its default permissions.",
                    "Could not reset permissions",
                )
                if result.ok:
                    row = self._app_list.get_selected_row()
                    if row is not None:
                        self._on_app_selected(self._app_list, row)

            self._backend.reset_permissions(app.app_id, _on_done, scope="user")

        confirm_destructive(
            self,
            f"Reset {app.label} permissions?",
            "All of your permission overrides for this app will be discarded, "
            "returning it to the sandbox settings it shipped with.",
            _do_reset,
            confirm_label="Reset",
        )
