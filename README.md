# Package Center

One native GTK4/libadwaita window for everything installed on this Fedora
machine: RPM packages, Flatpak apps, Flatpak sandbox permissions, and
user-level developer tooling — replacing the usual juggling of `dnf`,
`flatpak`, GNOME Software, and Flatseal.

## Install

```bash
./install.sh
```

Then launch **Package Center** from the app grid (or the dash, once pinned),
or run `pkgcenter` from a terminal.

The installer drops a desktop entry in `~/.local/share/applications`, the app
icon in `~/.local/share/icons/hicolor`, and a `pkgcenter` launcher in
`~/.local/bin` — all pointing back at this checkout, which stays where it is.
Edits to the source take effect on the next launch; **moving or renaming the
checkout means re-running `./install.sh`**. To remove the launcher again:

```bash
./install.sh --uninstall
```

During development you can still run it straight from the checkout:

```bash
python3 main.py
```

No virtualenv and no `pip install` step. The app uses the system Python's
PyGObject bindings (GTK 4 + libadwaita), which are already present on
Fedora Workstation; a plain venv would hide them — which is why the desktop
entry names `/usr/bin/python3` explicitly rather than whatever `python3` the
session PATH resolves to.

## What it does

| Section | Contents |
|---|---|
| **Applications** | Explicitly-installed RPM packages merged with installed Flatpak apps. Search, uninstall, or jump to an app's sandbox permissions. |
| **System Packages** | Every RPM package, with a toggle to include dependencies pulled in automatically. |
| **Sandbox Permissions** | Flatseal-style editor for what a Flatpak app may reach outside its sandbox: sockets (Wayland/X11/audio), devices, network/IPC, filesystem paths, D-Bus services, environment variables. |
| **Developer Tools** | Packages installed via `pip --user`, pipx, cargo, or `npm -g`. Only tools actually present on the machine get a tab. |

The toolbar's install button searches Fedora's DNF repositories and Flathub
at once and installs from either.

## Criticality and relationships

Every row carries a colour-coded criticality badge, a one-line description
of what the thing does, and a count of how many other installed packages
depend on it. The ⓘ button opens a detail view listing what requires it and
what it requires.

Criticality is about **downstream impact** — what else breaks if this is
removed — not about how important the software feels:

| Tier | Meaning |
|---|---|
| **Critical** | Protected by DNF (removal can make the machine unbootable), or 500+ packages depend on it |
| **High** | 50+ packages depend on it |
| **Medium** | 5+ packages depend on it |
| **Low** | Little or nothing depends on it — safe to remove |

So `glibc` is Critical (2169 downstream), `systemd` is Critical (protected),
while `firefox` is Low (1 downstream) and `ffmpeg` is Low (0) — removing a
browser breaks nothing else, however much you use it.

The dependency graph is derived from two `rpm -qa` queries joining what each
package REQUIRES against what each package PROVIDES, since RPM dependencies
name capabilities rather than packages. It resolves transitively, so an
indirect dependent still counts. Uninstall confirmations spell out the
impact before you commit.

Flatpak apps are always Low: they are sandboxed, so nothing else links
against them. Their detail view instead shows which runtime they use and
which other installed apps share that runtime.

## How permissions are handled

Flatpak permissions come from three places, and the editor keeps them
distinct:

- **Baseline** — what the app shipped with (`flatpak info --show-metadata`).
- **Delta** — your overrides (`~/.local/share/flatpak/overrides/<app-id>`).
- **Effective** — the merged result (`flatpak info --show-permissions`).

Applying a change writes only what actually differs from the baseline, so
the override file stays minimal. "Reset to Defaults" removes the override
file entirely, returning the app to its shipped sandbox.

Permission edits are written at `--user` scope and need no authentication,
even for system-installed apps.

## Privileges

| Operation | Elevation |
|---|---|
| Listing / searching anything | none |
| Flatpak permission edits | none (`--user` overrides) |
| Flatpak install / uninstall | handled by flatpak's own system helper, which prompts if needed — never wrapped in `pkexec` |
| RPM install / remove | `pkexec /usr/bin/dnf5 …`, one operation at a time |
| pip / pipx / cargo uninstall | none |
| `npm -g` uninstall | only if npm's prefix is outside your home directory |

Flatpak installs go to whichever scope the remote is configured in. On a
stock Fedora Workstation both `fedora` and `flathub` are system-scope, so a
`--user` install would fail with "No remote refs found".

## Layout

```
main.py                     launcher
install.sh                  installs/removes the desktop entry, icon, launcher
bin/pkgcenter               terminal entry point
data/
  *.desktop.in              desktop entry template (@SRC_DIR@ filled at install)
  icons/                    app icon, installed into hicolor
pkgcenter/
  app.py, window.py         Adw.Application and the main window
  models.py                 dataclasses shared across layers
  command_runner.py         async Gio.Subprocess wrapper (never blocks the UI)
  task_queue.py             serializes dnf5 mutations against the RPM lock
  desktop_index.py          package/app-id -> display name + icon
  backends/                 one module per package source
  permissions/              flatpak keyfile parsing and override diffing
  ui/                       pages and reusable widgets
```
