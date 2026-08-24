"""Generic add/remove editors for the free-form permission lists:
filesystem paths, persistent dirs, D-Bus talk-names, environment variables.
"""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402


class StringListEditorRow(Adw.ExpanderRow):
    """An Adw.ExpanderRow holding a set of plain strings, with an inline
    add field and per-item remove buttons. Optional `presets` render as
    quick-add chips above the add field.
    """

    def __init__(
        self,
        title: str,
        icon_name: str,
        items: list[str],
        on_add: Callable[[str], None],
        on_remove: Callable[[str], None],
        presets: Optional[list[str]] = None,
        entry_placeholder: str = "Add path…",
    ) -> None:
        super().__init__(title=title)
        self.set_icon_name(icon_name)
        self._on_add = on_add
        self._on_remove = on_remove
        self._items = list(items)
        self._item_rows: dict[str, Adw.ActionRow] = {}

        if presets:
            preset_row = Adw.ActionRow(title="Quick add")
            chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            chip_box.set_valign(Gtk.Align.CENTER)
            for preset in presets:
                btn = Gtk.Button(label=preset)
                btn.add_css_class("flat")
                btn.connect("clicked", lambda _b, p=preset: self._add(p))
                chip_box.append(btn)
            preset_row.add_suffix(chip_box)
            self.add_row(preset_row)

        entry_row = Adw.EntryRow(title=entry_placeholder)
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_valign(Gtk.Align.CENTER)

        def _submit(*_args) -> None:
            text = entry_row.get_text().strip()
            if text:
                self._add(text)
                entry_row.set_text("")

        add_btn.connect("clicked", _submit)
        entry_row.connect("entry-activated", _submit)
        entry_row.add_suffix(add_btn)
        self.add_row(entry_row)

        for item in self._items:
            self._add_row_widget(item)

    def _add(self, text: str) -> None:
        if text in self._items:
            return
        self._items.append(text)
        self._add_row_widget(text)
        self._on_add(text)

    def _add_row_widget(self, text: str) -> None:
        row = Adw.ActionRow(title=text)
        remove_btn = Gtk.Button(icon_name="user-trash-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", lambda _b, t=text: self._remove(t))
        row.add_suffix(remove_btn)
        self.add_row(row)
        self._item_rows[text] = row

    def _remove(self, text: str) -> None:
        row = self._item_rows.pop(text, None)
        if row is not None:
            self.remove(row)
        if text in self._items:
            self._items.remove(text)
        self._on_remove(text)


class KeyValueListEditorRow(Adw.ExpanderRow):
    """Like StringListEditorRow but for KEY=VALUE pairs (environment vars)."""

    def __init__(
        self,
        title: str,
        icon_name: str,
        items: dict[str, str],
        on_add: Callable[[str, str], None],
        on_remove: Callable[[str], None],
    ) -> None:
        super().__init__(title=title)
        self.set_icon_name(icon_name)
        self._on_add = on_add
        self._on_remove = on_remove
        self._item_rows: dict[str, Adw.ActionRow] = {}

        key_entry = Adw.EntryRow(title="Variable name")
        value_entry = Adw.EntryRow(title="Value")
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_valign(Gtk.Align.CENTER)

        def _submit(*_args) -> None:
            key = key_entry.get_text().strip()
            value = value_entry.get_text()
            if key:
                self._add(key, value)
                key_entry.set_text("")
                value_entry.set_text("")

        add_btn.connect("clicked", _submit)
        key_entry.connect("entry-activated", _submit)
        value_entry.connect("entry-activated", _submit)
        value_entry.add_suffix(add_btn)
        self.add_row(key_entry)
        self.add_row(value_entry)

        for key, value in items.items():
            self._add_row_widget(key, value)

    def _add(self, key: str, value: str) -> None:
        existing = self._item_rows.pop(key, None)
        if existing is not None:
            self.remove(existing)
        self._add_row_widget(key, value)
        self._on_add(key, value)

    def _add_row_widget(self, key: str, value: str) -> None:
        row = Adw.ActionRow(title=key, subtitle=value or "(empty)")
        remove_btn = Gtk.Button(icon_name="user-trash-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", lambda _b, k=key: self._remove(k))
        row.add_suffix(remove_btn)
        self.add_row(row)
        self._item_rows[key] = row

    def _remove(self, key: str) -> None:
        row = self._item_rows.pop(key, None)
        if row is not None:
            self.remove(row)
        self._on_remove(key)
