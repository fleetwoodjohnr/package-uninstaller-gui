"""Builds the installed-RPM dependency graph and derives a criticality
rating from how much would break downstream if a package were removed.

The whole graph comes from two `rpm -qa` calls (~1.3s each, purely local),
never per-package queries -- 2500+ individual `rpm -q --whatrequires` calls
would take minutes.

RPM dependencies are expressed against *capabilities* ("libc.so.6()(64bit)",
"config(bash)"), not package names, so resolving the graph means joining
what each package REQUIRES against what each package PROVIDES.

Note the `%{=NAME}` scalar modifier in the query formats: inside rpm's
`[...]` array iterator a bare `%{NAME}` does not repeat per array element
and silently collapses the output (129602 rows vs 183).
"""
from __future__ import annotations

import collections
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

RPM = "/usr/bin/rpm"
_PROTECTED_DIR = Path("/etc/dnf/protected.d")

# rpmlib(...) entries are constraints on the rpm format itself, not real
# inter-package edges.
_RPMLIB_RE = re.compile(r"^rpmlib\(")

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# Calibrated against this machine's actual distribution (median 5, p75 22,
# p90 121, p99 895, max 2182).
_CRITICAL_THRESHOLD = 500
_HIGH_THRESHOLD = 50
_MEDIUM_THRESHOLD = 5

CRITICALITY_LABEL = {
    CRITICAL: "Critical",
    HIGH: "High",
    MEDIUM: "Medium",
    LOW: "Low",
}

CRITICALITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}


@dataclass
class PackageInfo:
    name: str
    summary: str = ""
    protected: bool = False
    direct_dependents: set[str] = field(default_factory=set)
    dependencies: set[str] = field(default_factory=set)
    downstream_count: int = 0

    @property
    def criticality(self) -> str:
        if self.protected:
            return CRITICAL
        if self.downstream_count >= _CRITICAL_THRESHOLD:
            return CRITICAL
        if self.downstream_count >= _HIGH_THRESHOLD:
            return HIGH
        if self.downstream_count >= _MEDIUM_THRESHOLD:
            return MEDIUM
        return LOW

    @property
    def criticality_label(self) -> str:
        return CRITICALITY_LABEL[self.criticality]

    def explain(self) -> str:
        if self.protected:
            return (
                "Protected by the system: removing it can leave the machine "
                "unbootable or unusable."
            )
        n = self.downstream_count
        if n == 0:
            return "Nothing else installed depends on this. Safe to remove."
        if n == 1:
            return "1 other installed package depends on this."
        return f"{n} other installed packages depend on this, directly or indirectly."


class DependencyGraph:
    def __init__(self) -> None:
        self._packages: dict[str, PackageInfo] = {}
        self.ready = False

    def get(self, name: str) -> Optional[PackageInfo]:
        return self._packages.get(name)

    def build_async(self, on_done: Callable[[], None]) -> None:
        def _worker() -> None:
            try:
                self.build()
            finally:
                GLib.idle_add(on_done)

        threading.Thread(target=_worker, daemon=True).start()

    def build(self) -> None:
        summaries = self._query_summaries()
        provides = self._query_pairs("[%{=NAME}\t%{PROVIDENAME}\n]")
        requires = self._query_pairs("[%{=NAME}\t%{REQUIRENAME}\n]")
        protected = self._read_protected()

        packages = {
            name: PackageInfo(
                name=name, summary=summaries.get(name, ""), protected=name in protected
            )
            for name in summaries
        }

        # capability -> packages providing it
        providers: dict[str, set[str]] = collections.defaultdict(set)
        for pkg, capability in provides:
            providers[capability].add(pkg)

        for pkg, capability in requires:
            if _RPMLIB_RE.match(capability):
                continue
            info = packages.get(pkg)
            if info is None:
                continue
            for provider in providers.get(capability, ()):
                if provider == pkg:
                    continue
                info.dependencies.add(provider)
                dependent = packages.get(provider)
                if dependent is not None:
                    dependent.direct_dependents.add(pkg)

        self._compute_downstream(packages)
        self._packages = packages
        self.ready = True

    @staticmethod
    def _compute_downstream(packages: dict[str, PackageInfo]) -> None:
        """Transitive closure of "who breaks if this goes away", computed
        iteratively with an explicit stack: the graph contains dependency
        cycles and is deep enough that recursion risks a stack overflow.
        """
        memo: dict[str, set[str]] = {}

        for start in packages:
            if start in memo:
                continue
            stack = [(start, iter(packages[start].direct_dependents))]
            on_stack = {start}
            memo[start] = set()
            while stack:
                node, children = stack[-1]
                advanced = False
                for child in children:
                    if child in on_stack:
                        continue  # cycle: contributions folded in by the outer frame
                    if child not in memo:
                        memo[child] = set()
                        on_stack.add(child)
                        stack.append((child, iter(packages[child].direct_dependents)))
                        advanced = True
                        break
                if advanced:
                    continue
                stack.pop()
                on_stack.discard(node)
                acc = set()
                for child in packages[node].direct_dependents:
                    acc.add(child)
                    acc |= memo.get(child, set())
                acc.discard(node)
                memo[node] = acc

        for name, info in packages.items():
            info.downstream_count = len(memo.get(name, ()))

    @staticmethod
    def _query_summaries() -> dict[str, str]:
        out = _run_rpm("%{NAME}\t%{SUMMARY}\n")
        summaries: dict[str, str] = {}
        for line in out.splitlines():
            if "\t" in line:
                name, summary = line.split("\t", 1)
                summaries[name] = summary
            elif line.strip():
                summaries.setdefault(line.strip(), "")
        return summaries

    @staticmethod
    def _query_pairs(fmt: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for line in _run_rpm(fmt).splitlines():
            if "\t" in line:
                left, right = line.split("\t", 1)
                if right:
                    pairs.append((left, right))
        return pairs

    @staticmethod
    def _read_protected() -> set[str]:
        protected: set[str] = set()
        if not _PROTECTED_DIR.is_dir():
            return protected
        for conf in _PROTECTED_DIR.glob("*.conf"):
            try:
                for line in conf.read_text(encoding="utf-8").splitlines():
                    entry = line.strip()
                    if entry and not entry.startswith("#"):
                        protected.add(entry)
            except OSError:
                continue
        return protected


def _run_rpm(fmt: str) -> str:
    try:
        proc = subprocess.run(
            [RPM, "-qa", "--qf", fmt], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout
