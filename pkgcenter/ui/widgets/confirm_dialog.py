"""Thin wrapper around Adw.AlertDialog for destructive-action confirmation."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402


def confirm_destructive(
    parent: Gtk.Widget,
    heading: str,
    body: str,
    on_confirm: Callable[[], None],
    confirm_label: str = "Uninstall",
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", confirm_label)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def _on_response(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "confirm":
            on_confirm()

    dialog.connect("response", _on_response)
    dialog.present(parent)
