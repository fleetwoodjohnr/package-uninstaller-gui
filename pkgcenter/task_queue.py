"""A single-slot mutation guard.

dnf5 takes an exclusive lock on the RPM database. Two concurrent `dnf5
install`/`remove` calls from this app (or a race with a background
`dnf-automatic` run) would otherwise hang on that lock with no feedback.
Rather than queueing and silently running the second job later, we simply
refuse a second mutation while one is in flight and tell the caller why.
"""
from __future__ import annotations

from typing import Callable, Optional


class BusyError(Exception):
    """Raised when a mutation is requested while another is in progress."""


class SingleSlotQueue:
    def __init__(self) -> None:
        self._busy = False
        self._current_label: Optional[str] = None

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, label: str, start: Callable[[Callable[[], None]], None]) -> None:
        """Run `start(release)` if free, else raise BusyError.

        `start` is handed a `release` callback that MUST be called exactly
        once when the underlying operation finishes (success or failure).
        """
        if self._busy:
            raise BusyError(
                f"Another operation ({self._current_label}) is already in progress."
            )
        self._busy = True
        self._current_label = label

        def release() -> None:
            self._busy = False
            self._current_label = None

        start(release)
