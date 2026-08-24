"""Detail view for one package or app: what it is, how risky removing it
is, and how it relates to everything else installed.
"""
from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..dependency_graph import CRITICAL, HIGH, LOW, MEDIUM, DependencyGraph, PackageInfo
from ..models import FlatpakApp

# Adw/GTK accent classes give the tiers a consistent colour language with
# the badges in the list rows.
CRITICALITY_CSS = {
    CRITICAL: "error",
    HIGH: "warning",
    MEDIUM: "accent",
    LOW: "success",
}

_MAX_LISTED = 60


def criticality_badge(level: str, label: str) -> Gtk.Label:
    badge = Gtk.Label(label=label)
    badge.add_css_class("caption-heading")
    badge.add_css_class(CRITICALITY_CSS.get(level, "dim-label"))
    badge.set_valign(Gtk.Align.CENTER)
    return badge


def _name_list_group(title: str, description: str, names: list[str]) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title=title, description=description)
    if not names:
        row = Adw.ActionRow(title="None")
        row.set_subtitle("Nothing to show.")
        group.add(row)
        return group

    shown = sorted(names)[:_MAX_LISTED]
    expander = Adw.ExpanderRow(title=f"{len(names)} package(s)")
    for name in shown:
        expander.add_row(Adw.ActionRow(title=name))
    if len(names) > _MAX_LISTED:
        more = Adw.ActionRow(title=f"…and {len(names) - _MAX_LISTED} more")
        more.set_subtitle("Truncated for readability")
        expander.add_row(more)
    group.add(expander)
    return group


class PackageDetailDialog(Adw.Dialog):
    def __init__(
        self,
        title: str,
        subtitle: str,
        summary: str,
        info: Optional[PackageInfo] = None,
        flatpak_app: Optional[FlatpakApp] = None,
        graph: Optional[DependencyGraph] = None,
        runtime_siblings: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self.set_title(title)
        self.set_content_width(640)
        self.set_content_height(680)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title, subtitle=subtitle))
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()

        about = Adw.PreferencesGroup(title="What this is")
        summary_row = Adw.ActionRow(title=summary or "No description available.")
        summary_row.set_title_lines(0)
        about.add(summary_row)
        page.add(about)

        if info is not None:
            impact = Adw.PreferencesGroup(
                title="Removal impact",
                description=info.explain(),
            )
            level_row = Adw.ActionRow(title="Criticality")
            level_row.add_suffix(criticality_badge(info.criticality, info.criticality_label))
            impact.add(level_row)

            direct_row = Adw.ActionRow(title="Directly required by")
            direct_row.set_subtitle(f"{len(info.direct_dependents)} installed package(s)")
            impact.add(direct_row)

            total_row = Adw.ActionRow(title="Total downstream impact")
            total_row.set_subtitle(
                f"{info.downstream_count} package(s) would lose a dependency, "
                "directly or indirectly"
            )
            impact.add(total_row)

            if info.protected:
                protected_row = Adw.ActionRow(title="System protected")
                protected_row.set_subtitle(
                    "Marked protected by DNF — removal is blocked or unsafe."
                )
                impact.add(protected_row)
            page.add(impact)

            page.add(
                _name_list_group(
                    "Required by",
                    "Installed packages that depend on this one directly.",
                    sorted(info.direct_dependents),
                )
            )
            page.add(
                _name_list_group(
                    "Depends on",
                    "Installed packages this one needs in order to work.",
                    sorted(info.dependencies),
                )
            )

        if flatpak_app is not None:
            rel = Adw.PreferencesGroup(
                title="Relationships",
                description="Flatpak apps are sandboxed and share runtimes rather than system libraries.",
            )
            scope_row = Adw.ActionRow(title="Installation")
            scope_row.set_subtitle(f"{flatpak_app.install_scope} · from {flatpak_app.origin}")
            rel.add(scope_row)

            runtime_row = Adw.ActionRow(title="Uses runtime")
            runtime_row.set_subtitle(flatpak_app.runtime or "Unknown")
            rel.add(runtime_row)

            impact_row = Adw.ActionRow(title="Removal impact")
            others = [n for n in (runtime_siblings or []) if n != flatpak_app.app_id]
            impact_row.set_subtitle(
                "No other app depends on this one — removing it affects nothing else."
            )
            impact_row.add_suffix(criticality_badge(LOW, "Low"))
            rel.add(impact_row)

            if others:
                shared_row = Adw.ActionRow(title="Shares its runtime with")
                shared_row.set_subtitle(", ".join(sorted(others)))
                shared_row.set_subtitle_lines(0)
                rel.add(shared_row)
            page.add(rel)

        toolbar.set_content(page)
        self.set_child(toolbar)
