"""Plain data models shared across backends and UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class InstalledPackage:
    name: str
    version: str
    size_bytes: int
    source: Literal["rpm", "pip", "pipx", "cargo", "npm"] = "rpm"
    user_installed: bool = False
    from_repo: Optional[str] = None
    install_time: Optional[int] = None
    display_name: Optional[str] = None
    icon_name: Optional[str] = None

    @property
    def label(self) -> str:
        return self.display_name or self.name


@dataclass
class FlatpakApp:
    app_id: str
    name: str
    version: str
    branch: str
    origin: str
    install_scope: Literal["user", "system"]
    runtime: Optional[str] = None
    display_name: Optional[str] = None
    icon_name: Optional[str] = None

    @property
    def label(self) -> str:
        return self.display_name or self.name or self.app_id


@dataclass
class SearchResult:
    source: Literal["rpm", "flatpak"]
    id: str
    display_name: str
    summary: Optional[str] = None
    origin: Optional[str] = None


@dataclass
class DesktopEntry:
    id: str
    name: str
    icon: Optional[str] = None


@dataclass
class PermissionContext:
    """A Flatpak sandbox permission set, split into positive/negative pairs
    per category so explicit negation (revoking something the baseline
    grants) can be represented and diffed correctly.
    """

    app_id: str

    shared: set[str] = field(default_factory=set)
    unshared: set[str] = field(default_factory=set)

    sockets: set[str] = field(default_factory=set)
    nosockets: set[str] = field(default_factory=set)

    devices: set[str] = field(default_factory=set)
    nodevices: set[str] = field(default_factory=set)

    features: set[str] = field(default_factory=set)
    disallowed_features: set[str] = field(default_factory=set)

    # path -> "ro" | "create" | None (read-write)
    filesystems: dict[str, Optional[str]] = field(default_factory=dict)
    nofilesystems: set[str] = field(default_factory=set)

    persistent: list[str] = field(default_factory=list)

    # dbus name -> "talk" | "own"
    session_bus: dict[str, str] = field(default_factory=dict)
    session_bus_no_talk: set[str] = field(default_factory=set)

    system_bus: dict[str, str] = field(default_factory=dict)
    system_bus_no_talk: set[str] = field(default_factory=set)

    environment: dict[str, str] = field(default_factory=dict)
    unset_environment: set[str] = field(default_factory=set)

    def clone(self) -> "PermissionContext":
        return PermissionContext(
            app_id=self.app_id,
            shared=set(self.shared),
            unshared=set(self.unshared),
            sockets=set(self.sockets),
            nosockets=set(self.nosockets),
            devices=set(self.devices),
            nodevices=set(self.nodevices),
            features=set(self.features),
            disallowed_features=set(self.disallowed_features),
            filesystems=dict(self.filesystems),
            nofilesystems=set(self.nofilesystems),
            persistent=list(self.persistent),
            session_bus=dict(self.session_bus),
            session_bus_no_talk=set(self.session_bus_no_talk),
            system_bus=dict(self.system_bus),
            system_bus_no_talk=set(self.system_bus_no_talk),
            environment=dict(self.environment),
            unset_environment=set(self.unset_environment),
        )
