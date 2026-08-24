"""Common interface every package-source backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from ..command_runner import CommandResult
from ..models import SearchResult


class PackageBackend(ABC):
    """One backend per package source (rpm, flatpak, pip, pipx, cargo, npm).

    Read methods return data through a callback (async, never blocks).
    Mutating methods (install/remove) also report through a callback and
    are expected to be safe to call only when `is_available()` is True.
    """

    #: short machine name, e.g. "pip", "cargo" -- used for UI tab ids
    name: str = ""
    #: human label for tabs/headers, e.g. "Pip (user)"
    label: str = ""

    def is_available(self) -> bool:
        """Cheap, synchronous presence check (e.g. shutil.which). Backends
        that are always available (rpm, flatpak) simply return True.
        """
        return True

    @abstractmethod
    def list_installed(self, on_done: Callable[[list], None]) -> None:
        """Fetch the installed list asynchronously; calls on_done(items)."""

    def search(self, term: str, on_done: Callable[[list[SearchResult]], None]) -> None:
        """Optional: query a remote catalog. Default: unsupported."""
        on_done([])

    def supports_search(self) -> bool:
        return False

    @abstractmethod
    def remove(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        """Uninstall the named package/app."""

    def install(self, identifier: str, on_done: Callable[[CommandResult], None]) -> None:
        raise NotImplementedError(f"{self.name} backend does not support install")
