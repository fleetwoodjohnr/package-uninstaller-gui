"""Adw.Application entry point."""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from .window import PkgCenterWindow

APP_ID = "io.github.jfleets17.PkgCenter"


class PkgCenterApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = PkgCenterWindow(application=self)
        window.present()
