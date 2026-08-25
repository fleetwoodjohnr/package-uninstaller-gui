#!/usr/bin/env bash
# Installs Package Center's desktop entry, icon, and terminal launcher into
# ~/.local, pointing at this checkout. The app runs in place: edits here take
# effect on the next launch, and moving the checkout means re-running this.
#
#   ./install.sh              install (or refresh) the launcher
#   ./install.sh --uninstall  remove it again
set -euo pipefail

APP_ID="io.github.jfleets17.PkgCenter"
APPS_DIR="$HOME/.local/share/applications"
ICON_ROOT="$HOME/.local/share/icons/hicolor"
ICON_DIR="$ICON_ROOT/scalable/apps"
BIN_DIR="$HOME/.local/bin"

DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.svg"
LAUNCHER="$BIN_DIR/pkgcenter"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_cmd() {
    command -v "$1" >/dev/null 2>&1
}

check_deps() {
    local missing=()
    require_cmd python3 || missing+=("python3")
    if ! /usr/bin/python3 -c "
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
" >/dev/null 2>&1; then
        missing+=("python3-gobject / gtk4 / libadwaita bindings")
    fi

    if ((${#missing[@]})); then
        echo "Missing required dependencies:" >&2
        printf '  - %s\n' "${missing[@]}" >&2
        echo >&2
        echo "On Fedora, install everything needed with:" >&2
        echo "  sudo dnf install -y python3-gobject gtk4 libadwaita" >&2
        exit 1
    fi
}

# The desktop entry has to name an absolute path to this checkout, so it is
# generated from the tracked template rather than tracked with a path baked in.
install_app() {
    mkdir -p "$APPS_DIR" "$ICON_DIR" "$BIN_DIR"

    sed "s#@SRC_DIR@#$SRC_DIR#g" \
        "$SRC_DIR/data/$APP_ID.desktop.in" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"

    ln -sfn "$SRC_DIR/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON_FILE"

    chmod +x "$SRC_DIR/bin/pkgcenter"
    ln -sfn "$SRC_DIR/bin/pkgcenter" "$LAUNCHER"

    refresh_caches

    # Only surfaced on a real failure. desktop-file-validate also emits style
    # hints at exit 0 -- including one suggesting Settings alongside
    # PackageManager, which would then trip its own "more than one main
    # category" hint (the app listed twice in the menu). System already
    # satisfies PackageManager's requirement, so the pairing stays as is.
    local report
    if require_cmd desktop-file-validate && ! report="$(desktop-file-validate "$DESKTOP_FILE" 2>&1)"; then
        echo "warning: the installed desktop entry did not validate cleanly" >&2
        echo "$report" >&2
    fi
}

uninstall_app() {
    rm -f "$DESKTOP_FILE" "$ICON_FILE" "$LAUNCHER"
    refresh_caches
    echo "Removed:"
    echo "  $DESKTOP_FILE"
    echo "  $ICON_FILE"
    echo "  $LAUNCHER"
    echo
    echo "The checkout at $SRC_DIR is untouched; re-run ./install.sh to restore the launcher."
}

refresh_caches() {
    require_cmd update-desktop-database && update-desktop-database "$APPS_DIR" || true
    require_cmd gtk-update-icon-cache && gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
}

print_summary() {
    echo "Installed:"
    echo "  Desktop entry: $DESKTOP_FILE"
    echo "  Icon:          $ICON_FILE"
    echo "  Launcher:      $LAUNCHER"
    echo "  App source:    $SRC_DIR (run in place -- re-run ./install.sh if you move it)"
    echo
    echo "Launch 'Package Center' from the app grid, or run 'pkgcenter'"
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        echo "  (note: $BIN_DIR is not on your PATH, so the 'pkgcenter' command won't resolve yet)"
    fi
}

main() {
    case "${1:-}" in
        --uninstall)
            uninstall_app
            ;;
        "")
            check_deps
            install_app
            print_summary
            ;;
        *)
            echo "usage: $0 [--uninstall]" >&2
            exit 2
            ;;
    esac
}

main "$@"
