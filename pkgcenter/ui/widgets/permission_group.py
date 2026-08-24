"""Builds an Adw.ExpanderRow of Adw.SwitchRow toggles for one permission
category (sockets, devices, shared, features).

Switches reflect the *effective* state of the merged (baseline + delta)
edited context directly -- membership in `edited.<positive_attr>` is ON,
otherwise OFF. Toggling mutates the edited context in place:
  * turning ON: add to positive, drop from negative.
  * turning OFF: drop from positive; if the item was actually granted by
    the app's own baseline, add it to negative too (an explicit override is
    required to revoke something the baseline grants -- otherwise it's
    already off by omission and no override entry is needed).
"""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ...models import PermissionContext

# Known items per category, since Flatpak has no "list valid sockets" query --
# these are Flatpak's own documented enum values (flatpak-metadata(5)).
KNOWN_SOCKETS = [
    ("x11", "X11", "Direct X11 access (bypasses Wayland sandboxing)"),
    ("wayland", "Wayland", "Direct Wayland display access"),
    ("fallback-x11", "Fallback X11", "X11 only if Wayland is unavailable"),
    ("pulseaudio", "Audio (PulseAudio)", "Play/record audio"),
    ("session-bus", "Session Bus", "Full access to the D-Bus session bus"),
    ("system-bus", "System Bus", "Full access to the D-Bus system bus"),
    ("ssh-auth", "SSH Agent", "Access the running ssh-agent"),
    ("pcsc", "Smart Cards", "PC/SC smart-card access"),
    ("cups", "Printing (CUPS)", "Access to the printing system"),
]
KNOWN_DEVICES = [
    ("dri", "Graphics (DRI)", "GPU acceleration"),
    ("all", "All Devices", "Full /dev access"),
    ("kvm", "Virtualization (KVM)", "Hardware virtualization"),
    ("shm", "Shared Memory", "POSIX shared memory"),
    ("input", "Input Devices", "Raw input device access"),
]
KNOWN_SHARED = [
    ("network", "Network", "Internet and local network access"),
    ("ipc", "Inter-Process Comm.", "Share IPC namespace with the host"),
]
KNOWN_FEATURES = [
    ("devel", "Development", "ptrace/syscall debugging"),
    ("multiarch", "Multiarch", "Run binaries of other architectures"),
    ("bluetooth", "Bluetooth", "Bluetooth access"),
    ("canbus", "CAN Bus", "CAN bus access"),
]


def _is_effective(edited: PermissionContext, positive_attr: str, item: str) -> bool:
    return item in getattr(edited, positive_attr)


def build_toggle_group(
    title: str,
    icon_name: str,
    items: list[tuple[str, str, str]],
    edited: PermissionContext,
    baseline: PermissionContext,
    positive_attr: str,
    negative_attr: Optional[str],
    on_change: Callable[[], None],
) -> Adw.ExpanderRow:
    expander = Adw.ExpanderRow(title=title)
    expander.set_icon_name(icon_name)

    for item_id, item_label, item_desc in items:
        switch_row = Adw.SwitchRow(title=item_label, subtitle=item_desc)
        switch_row.set_active(_is_effective(edited, positive_attr, item_id))

        badge = Gtk.Label(label="Changed")
        badge.add_css_class("caption")
        badge.add_css_class("accent")
        badge.set_valign(Gtk.Align.CENTER)
        badge.set_visible(
            _is_effective(edited, positive_attr, item_id)
            != _is_effective(baseline, positive_attr, item_id)
        )
        switch_row.add_suffix(badge)

        def _on_toggled(
            row: Adw.SwitchRow, _pspec, item_id=item_id, badge=badge
        ) -> None:
            positive = getattr(edited, positive_attr)
            negative = getattr(edited, negative_attr) if negative_attr else None
            if row.get_active():
                positive.add(item_id)
                if negative is not None:
                    negative.discard(item_id)
            else:
                positive.discard(item_id)
                baseline_positive = getattr(baseline, positive_attr)
                if negative is not None and item_id in baseline_positive:
                    negative.add(item_id)
            badge.set_visible(
                row.get_active() != _is_effective(baseline, positive_attr, item_id)
            )
            on_change()

        switch_row.connect("notify::active", _on_toggled)
        expander.add_row(switch_row)

    return expander
