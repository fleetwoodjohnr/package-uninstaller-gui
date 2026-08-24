"""Parses Flatpak's metadata/override keyfile dialect into a PermissionContext.

Verified live against this machine's flatpak (1.18.1) by writing a real test
override and inspecting the resulting file:

    [Context]
    sockets=!wayland;x11;
    filesystems=home;!xdg-download;
    unset-environment=SOME_VAR;

    [Session Bus Policy]
    org.example.Test=talk

    [Environment]
    TEST_VAR=hello
    SOME_VAR=

Findings that shape this parser:
  * Negation for shared/sockets/devices/filesystems/features is a `!`
    prefix on an individual entry *within* the single `;`-joined list --
    there is no separate `unshared=`/`nosockets=`/`nofilesystems=` key in
    the keyfile. (`--nosocket=X`, `--disallow=X` etc. on the CLI just add
    `!X` to the same list.) The negated half must be retained: dropping it
    makes a revoked permission read as still-granted on reload, because
    the baseline still lists it.
  * Revoking a D-Bus name (`--no-talk-name`, `--system-no-talk-name`)
    writes `name=none` in the relevant bus-policy section rather than a
    `!`-prefixed list entry.
  * `unset-environment=` is a plain (non-negated) `;`-list living inside
    `[Context]`, not its own section.
  * `flatpak override --unset-env=X` *also* writes a companion `X=` (empty
    value) line into `[Environment]` -- that's a by-product, not a second
    source of truth; `unset-environment` in `[Context]` is authoritative.
  * `[Application]`, `[Build]`, and `[Extension ...]` sections appear in
    `--show-metadata` output but carry no permission data and are ignored.
  * `filesystems=` entries may carry a `:ro` or `:create` suffix after the
    path (e.g. `xdg-run/gnupg:ro`).
"""
from __future__ import annotations

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from ..models import PermissionContext

_CONTEXT_GROUP = "Context"
_SESSION_BUS_GROUP = "Session Bus Policy"
_SYSTEM_BUS_GROUP = "System Bus Policy"
_ENVIRONMENT_GROUP = "Environment"


def _split_list(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _split_positive_negative(value: str) -> tuple[set[str], set[str]]:
    positive: set[str] = set()
    negative: set[str] = set()
    for item in _split_list(value):
        if item.startswith("!"):
            negative.add(item[1:])
        else:
            positive.add(item)
    return positive, negative


def _split_filesystems(value: str) -> tuple[dict[str, str | None], set[str]]:
    allowed: dict[str, str | None] = {}
    denied: set[str] = set()
    for item in _split_list(value):
        negated = item.startswith("!")
        entry = item[1:] if negated else item
        if ":" in entry:
            path, suffix = entry.rsplit(":", 1)
        else:
            path, suffix = entry, None
        if negated:
            denied.add(path)
        else:
            allowed[path] = suffix
    return allowed, denied


def parse_context_text(text: str, app_id: str) -> PermissionContext:
    """Parse a flatpak metadata/override/permissions keyfile blob.

    Works for `flatpak info --show-metadata`, `flatpak info
    --show-permissions`, and the raw `~/.local/share/flatpak/overrides/*`
    file -- all three use the same keyfile dialect for the parts we care
    about (`[Context]`, bus policy sections, `[Environment]`).
    """
    ctx = PermissionContext(app_id=app_id)
    if not text.strip():
        return ctx

    keyfile = GLib.KeyFile.new()
    try:
        keyfile.load_from_data(text, len(text.encode("utf-8")), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return ctx

    def get(group: str, key: str) -> str | None:
        try:
            return keyfile.get_string(group, key)
        except GLib.Error:
            return None

    if keyfile.has_group(_CONTEXT_GROUP):
        shared = get(_CONTEXT_GROUP, "shared")
        if shared:
            ctx.shared, ctx.unshared = _split_positive_negative(shared)

        sockets = get(_CONTEXT_GROUP, "sockets")
        if sockets:
            ctx.sockets, ctx.nosockets = _split_positive_negative(sockets)

        devices = get(_CONTEXT_GROUP, "devices")
        if devices:
            ctx.devices, ctx.nodevices = _split_positive_negative(devices)

        features = get(_CONTEXT_GROUP, "features")
        if features:
            ctx.features, ctx.disallowed_features = _split_positive_negative(features)

        filesystems = get(_CONTEXT_GROUP, "filesystems")
        if filesystems:
            ctx.filesystems, ctx.nofilesystems = _split_filesystems(filesystems)

        persistent = get(_CONTEXT_GROUP, "persistent")
        if persistent:
            ctx.persistent = _split_list(persistent)

        unset_env = get(_CONTEXT_GROUP, "unset-environment")
        if unset_env:
            ctx.unset_environment = set(_split_list(unset_env))

    if keyfile.has_group(_SESSION_BUS_GROUP):
        for key in keyfile.get_keys(_SESSION_BUS_GROUP)[0]:
            value = get(_SESSION_BUS_GROUP, key)
            if value == "none":
                ctx.session_bus_no_talk.add(key)
            elif value:
                ctx.session_bus[key] = value

    if keyfile.has_group(_SYSTEM_BUS_GROUP):
        for key in keyfile.get_keys(_SYSTEM_BUS_GROUP)[0]:
            value = get(_SYSTEM_BUS_GROUP, key)
            if value == "none":
                ctx.system_bus_no_talk.add(key)
            elif value:
                ctx.system_bus[key] = value

    if keyfile.has_group(_ENVIRONMENT_GROUP):
        for key in keyfile.get_keys(_ENVIRONMENT_GROUP)[0]:
            value = get(_ENVIRONMENT_GROUP, key)
            if value:
                ctx.environment[key] = value
            elif key not in ctx.unset_environment:
                # Empty value with no matching Context unset-environment
                # entry: treat as an intentional empty-string assignment.
                ctx.environment[key] = ""

    return ctx
