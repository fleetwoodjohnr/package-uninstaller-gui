"""Builds the `flatpak override` argv needed to move from a baseline
PermissionContext to an edited one, emitting only the flags for what
actually changed.

Caveat (documented, not a bug): flatpak override edits are incremental --
there is no "clear this one override key back to unspecified" primitive
short of `--reset` (which clears everything). If a user toggles something
away from baseline and then back again, the emitted flag will make the
override file explicitly state the baseline value rather than removing the
override key outright. The *effective* permission is always correct either
way; only the override file's cleanliness differs in that revert case.
"""
from __future__ import annotations

from ..models import PermissionContext

OVERRIDE = "flatpak"


def build_override_argv(
    baseline: PermissionContext,
    edited: PermissionContext,
    scope: str = "user",
) -> list[str] | None:
    """Returns the full `flatpak override --user|--system <app-id> ...`
    argv, or None if nothing changed.
    """
    flags: list[str] = []

    def diff_flag_set(
        base_pos: set[str], base_neg: set[str],
        new_pos: set[str], new_neg: set[str],
        pos_flag: str, neg_flag: str,
    ) -> None:
        for item in new_pos - base_pos:
            flags.append(f"--{pos_flag}={item}")
        for item in new_neg - base_neg:
            flags.append(f"--{neg_flag}={item}")

    diff_flag_set(baseline.shared, baseline.unshared, edited.shared, edited.unshared, "share", "unshare")
    diff_flag_set(baseline.sockets, baseline.nosockets, edited.sockets, edited.nosockets, "socket", "nosocket")
    diff_flag_set(baseline.devices, baseline.nodevices, edited.devices, edited.nodevices, "device", "nodevice")

    diff_flag_set(
        baseline.features, baseline.disallowed_features,
        edited.features, edited.disallowed_features,
        "allow", "disallow",
    )

    for path, suffix in edited.filesystems.items():
        base_suffix = baseline.filesystems.get(path, "__absent__")
        if path not in baseline.filesystems or base_suffix != suffix:
            value = f"{path}:{suffix}" if suffix else path
            flags.append(f"--filesystem={value}")
    for path in edited.nofilesystems - baseline.nofilesystems:
        flags.append(f"--nofilesystem={path}")
    for path in baseline.filesystems.keys() - edited.filesystems.keys() - edited.nofilesystems:
        flags.append(f"--nofilesystem={path}")

    for item in set(edited.persistent) - set(baseline.persistent):
        flags.append(f"--persist={item}")

    for name, value in edited.session_bus.items():
        if baseline.session_bus.get(name) != value:
            flag = "own-name" if value == "own" else "talk-name"
            flags.append(f"--{flag}={name}")
    for name in edited.session_bus_no_talk - baseline.session_bus_no_talk:
        flags.append(f"--no-talk-name={name}")

    for name, value in edited.system_bus.items():
        if baseline.system_bus.get(name) != value:
            flag = "system-own-name" if value == "own" else "system-talk-name"
            flags.append(f"--{flag}={name}")
    for name in edited.system_bus_no_talk - baseline.system_bus_no_talk:
        flags.append(f"--system-no-talk-name={name}")

    for key, value in edited.environment.items():
        if baseline.environment.get(key) != value and key not in edited.unset_environment:
            flags.append(f"--env={key}={value}")
    for key in edited.unset_environment - baseline.unset_environment:
        flags.append(f"--unset-env={key}")

    if not flags:
        return None

    scope_flag = "--user" if scope == "user" else "--system"
    return [OVERRIDE, "override", scope_flag, edited.app_id, *flags]


def build_reset_argv(app_id: str, scope: str = "user") -> list[str]:
    scope_flag = "--user" if scope == "user" else "--system"
    return [OVERRIDE, "override", scope_flag, "--reset", app_id]


def merge_baseline_and_delta(baseline: PermissionContext, delta: PermissionContext) -> PermissionContext:
    """Produces the starting "edited" context the permissions UI mutates:
    the effective state (baseline with the on-disk override applied) laid
    out as plain positive/negative membership, so a switch's ON/OFF state
    is a simple set-membership check rather than three-way inheritance
    logic living in the UI layer.
    """
    merged = PermissionContext(app_id=baseline.app_id)

    def merge_pair(base_pos: set[str], delta_pos: set[str], delta_neg: set[str]) -> tuple[set[str], set[str]]:
        positive = (base_pos - delta_neg) | delta_pos
        negative = set(delta_neg)
        return positive, negative

    merged.shared, merged.unshared = merge_pair(baseline.shared, delta.shared, delta.unshared)
    merged.sockets, merged.nosockets = merge_pair(baseline.sockets, delta.sockets, delta.nosockets)
    merged.devices, merged.nodevices = merge_pair(baseline.devices, delta.devices, delta.nodevices)
    merged.features, merged.disallowed_features = merge_pair(
        baseline.features, delta.features, delta.disallowed_features
    )

    merged.filesystems = dict(baseline.filesystems)
    merged.filesystems.update(delta.filesystems)
    for denied in delta.nofilesystems:
        merged.filesystems.pop(denied, None)
    merged.nofilesystems = set(delta.nofilesystems)

    merged.persistent = list(dict.fromkeys([*baseline.persistent, *delta.persistent]))

    merged.session_bus = dict(baseline.session_bus)
    merged.session_bus.update(delta.session_bus)
    for denied in delta.session_bus_no_talk:
        merged.session_bus.pop(denied, None)
    merged.session_bus_no_talk = set(delta.session_bus_no_talk)

    merged.system_bus = dict(baseline.system_bus)
    merged.system_bus.update(delta.system_bus)
    for denied in delta.system_bus_no_talk:
        merged.system_bus.pop(denied, None)
    merged.system_bus_no_talk = set(delta.system_bus_no_talk)

    merged.environment = dict(baseline.environment)
    merged.environment.update(delta.environment)
    for unset in delta.unset_environment:
        merged.environment.pop(unset, None)
    merged.unset_environment = set(delta.unset_environment)

    return merged
