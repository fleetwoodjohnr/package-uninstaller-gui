"""Adw.ToastOverlay-based helpers for async operation feedback."""
from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ...command_runner import CommandResult


class ToastReporter:
    """Wraps an Adw.ToastOverlay to report async command results uniformly,
    including the "authentication cancelled" case (pkexec exit 126/127),
    which should read as calm, not as a package-manager error.
    """

    def __init__(self, overlay: Adw.ToastOverlay) -> None:
        self._overlay = overlay

    def busy(self, message: str) -> None:
        self._overlay.add_toast(Adw.Toast(title=message, timeout=0))

    def report(self, result: CommandResult, success_message: str, failure_prefix: str) -> None:
        if result.ok:
            self._overlay.add_toast(Adw.Toast(title=success_message, timeout=3))
            return
        if result.auth_cancelled:
            self._overlay.add_toast(Adw.Toast(title="Authentication cancelled.", timeout=3))
            return
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        detail_text = detail[-1] if detail else "Unknown error."
        self._overlay.add_toast(
            Adw.Toast(title=f"{failure_prefix}: {detail_text}", timeout=6)
        )

    def info(self, message: str, timeout: int = 3) -> None:
        self._overlay.add_toast(Adw.Toast(title=message, timeout=timeout))
