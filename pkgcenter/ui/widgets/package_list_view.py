"""Shared, virtualized list widget for anything package-shaped.

Uses Gtk.ListView + Gio.ListStore + Gtk.FilterListModel rather than
Gtk.ListBox, which creates one real widget per row with no virtualization
and would not scale to the full ~2530-row system package list.
"""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GObject", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import GLib, GObject, Gio, Gtk  # noqa: E402

from ...dependency_graph import CRITICAL, HIGH, LOW, MEDIUM

CRITICALITY_CSS = {
    CRITICAL: "error",
    HIGH: "warning",
    MEDIUM: "accent",
    LOW: "success",
}

CRITICALITY_TOOLTIP = {
    CRITICAL: "Critical — many things depend on this, or it is system protected",
    HIGH: "High — a lot of other packages depend on this",
    MEDIUM: "Medium — some other packages depend on this",
    LOW: "Low — little or nothing depends on this",
}


class PackageRow(GObject.Object):
    """GObject wrapper around one list entry -- Gio.ListStore requires
    GObject items, so plain dataclasses (InstalledPackage/FlatpakApp/...)
    are wrapped rather than stored directly.
    """

    def __init__(
        self,
        payload,
        kind: str,
        uninstall_id: str,
        display_name: str,
        subtitle: str = "",
        icon_name: Optional[str] = None,
        show_permissions: bool = False,
        criticality: Optional[str] = None,
        criticality_label: str = "",
        sort_rank: int = 0,
    ) -> None:
        super().__init__()
        self.payload = payload
        self.kind = kind
        self.uninstall_id = uninstall_id
        self.display_name = display_name
        self.subtitle = subtitle
        self.icon_name = icon_name
        self.show_permissions = show_permissions
        self.criticality = criticality
        self.criticality_label = criticality_label
        self.sort_rank = sort_rank


class PackageListView(Gtk.Box):
    def __init__(
        self,
        on_uninstall: Callable[[PackageRow], None],
        on_permissions: Optional[Callable[[PackageRow], None]] = None,
        search_placeholder: str = "Search…",
        on_details: Optional[Callable[[PackageRow], None]] = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._on_uninstall = on_uninstall
        self._on_permissions = on_permissions
        self._on_details = on_details
        self._search_text = ""

        self.search_entry = Gtk.SearchEntry(placeholder_text=search_placeholder)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.append(self.search_entry)

        self._store = Gio.ListStore.new(PackageRow)
        self._filter = Gtk.CustomFilter.new(self._filter_func)
        filter_model = Gtk.FilterListModel.new(self._store, self._filter)
        sorter = Gtk.CustomSorter.new(self._sort_func)
        sort_model = Gtk.SortListModel.new(filter_model, sorter)
        selection = Gtk.NoSelection.new(sort_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)

        self.list_view = Gtk.ListView.new(selection, factory)
        self.list_view.add_css_class("boxed-list")

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.list_view)
        self.append(scroller)

        self.empty_label = Gtk.Label(label="Nothing here yet.")
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_margin_top(24)
        self.empty_label.set_visible(False)
        self.append(self.empty_label)

    def set_items(self, rows: list[PackageRow]) -> None:
        self._store.remove_all()
        for row in rows:
            self._store.append(row)
        self.empty_label.set_visible(len(rows) == 0)

    def remove_by_uninstall_id(self, uninstall_id: str) -> None:
        for index in range(self._store.get_n_items()):
            item = self._store.get_item(index)
            if item.uninstall_id == uninstall_id:
                self._store.remove(index)
                return

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_text = entry.get_text().strip().lower()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _filter_func(self, item: PackageRow, *_args) -> bool:
        if not self._search_text:
            return True
        haystack = f"{item.display_name} {item.subtitle}".lower()
        return self._search_text in haystack

    def _sort_func(self, a: PackageRow, b: PackageRow, *_args) -> int:
        name_a, name_b = a.display_name.lower(), b.display_name.lower()
        return (name_a > name_b) - (name_a < name_b)

    def _on_factory_setup(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        icon = Gtk.Image()
        icon.set_pixel_size(32)
        box.append(icon)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        label_box.set_hexpand(True)
        label_box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(xalign=0.0)
        title.add_css_class("heading")
        title.set_ellipsize(3)  # Pango.EllipsizeMode.END
        subtitle = Gtk.Label(xalign=0.0)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")
        subtitle.set_ellipsize(3)
        label_box.append(title)
        label_box.append(subtitle)
        box.append(label_box)

        crit_badge = Gtk.Label()
        crit_badge.add_css_class("caption-heading")
        crit_badge.set_valign(Gtk.Align.CENTER)
        box.append(crit_badge)

        details_btn = Gtk.Button(icon_name="info-outline-symbolic")
        details_btn.add_css_class("flat")
        details_btn.set_tooltip_text("What this is, and what depends on it")
        box.append(details_btn)

        perm_btn = Gtk.Button(label="Permissions")
        perm_btn.add_css_class("flat")
        box.append(perm_btn)

        uninstall_btn = Gtk.Button(label="Uninstall")
        uninstall_btn.add_css_class("destructive-action")
        box.append(uninstall_btn)

        list_item.set_child(box)
        list_item.icon_widget = icon
        list_item.title_widget = title
        list_item.subtitle_widget = subtitle
        list_item.crit_badge = crit_badge
        list_item.details_button = details_btn
        list_item.perm_button = perm_btn
        list_item.uninstall_button = uninstall_btn
        list_item.perm_handler_id = None
        list_item.uninstall_handler_id = None
        list_item.details_handler_id = None

    def _on_factory_bind(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row: PackageRow = list_item.get_item()
        list_item.title_widget.set_label(row.display_name)
        list_item.subtitle_widget.set_label(row.subtitle)
        list_item.subtitle_widget.set_visible(bool(row.subtitle))

        if row.icon_name:
            try:
                gicon = Gio.Icon.new_for_string(row.icon_name)
                list_item.icon_widget.set_from_gicon(gicon)
            except GLib.Error:
                list_item.icon_widget.set_from_icon_name("application-x-executable-symbolic")
        else:
            list_item.icon_widget.set_from_icon_name("application-x-executable-symbolic")

        badge = list_item.crit_badge
        for css in ("error", "warning", "accent", "success"):
            badge.remove_css_class(css)
        if row.criticality:
            badge.set_label(row.criticality_label)
            badge.add_css_class(CRITICALITY_CSS.get(row.criticality, "dim-label"))
            badge.set_tooltip_text(CRITICALITY_TOOLTIP.get(row.criticality, ""))
            badge.set_visible(True)
        else:
            badge.set_visible(False)

        show_perm = row.show_permissions and self._on_permissions is not None
        list_item.perm_button.set_visible(show_perm)
        list_item.details_button.set_visible(self._on_details is not None)

        list_item.details_handler_id = list_item.details_button.connect(
            "clicked", lambda _b: self._on_details(row) if self._on_details else None
        )
        list_item.perm_handler_id = list_item.perm_button.connect(
            "clicked", lambda _b: self._on_permissions(row) if self._on_permissions else None
        )
        list_item.uninstall_handler_id = list_item.uninstall_button.connect(
            "clicked", lambda _b: self._on_uninstall(row)
        )

    def _on_factory_unbind(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        if list_item.details_handler_id is not None:
            list_item.details_button.disconnect(list_item.details_handler_id)
            list_item.details_handler_id = None
        if list_item.perm_handler_id is not None:
            list_item.perm_button.disconnect(list_item.perm_handler_id)
            list_item.perm_handler_id = None
        if list_item.uninstall_handler_id is not None:
            list_item.uninstall_button.disconnect(list_item.uninstall_handler_id)
            list_item.uninstall_handler_id = None
