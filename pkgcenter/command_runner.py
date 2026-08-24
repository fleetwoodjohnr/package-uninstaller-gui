"""Single choke point for spawning external commands (dnf5, flatpak, pip3, ...).

Every call goes through Gio.Subprocess asynchronously so the GTK main loop is
never blocked, whether the command finishes in 50ms (a repoquery) or 10s (a
dnf5 repo refresh) or waits on a polkit prompt the user hasn't answered yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

# pkexec's own exit codes for "dialog dismissed" / "not authorized" -- these
# must read as a calm "cancelled" state, not a scary package-manager error.
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORIZED = 127


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool = False

    @property
    def auth_cancelled(self) -> bool:
        return self.returncode in (PKEXEC_DISMISSED, PKEXEC_NOT_AUTHORIZED)


class CommandRunner:
    """Static helpers wrapping Gio.Subprocess. No instance state."""

    @staticmethod
    def run_async(
        argv: list[str],
        on_done: Callable[[CommandResult], None],
        cancellable: Optional[Gio.Cancellable] = None,
    ) -> None:
        try:
            proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as exc:
            on_done(CommandResult(ok=False, returncode=-1, stdout="", stderr=str(exc)))
            return

        def _on_communicate(source: Gio.Subprocess, res: Gio.AsyncResult) -> None:
            try:
                ok, stdout, stderr = source.communicate_utf8_finish(res)
            except GLib.Error as exc:
                on_done(CommandResult(ok=False, returncode=-1, stdout="", stderr=str(exc)))
                return
            rc = source.get_exit_status()
            result = CommandResult(
                ok=(rc == 0),
                returncode=rc,
                stdout=stdout or "",
                stderr=stderr or "",
            )
            on_done(result)

        proc.communicate_utf8_async(None, cancellable, _on_communicate)

    @staticmethod
    def run_streaming(
        argv: list[str],
        on_line: Callable[[str], None],
        on_done: Callable[[CommandResult], None],
        cancellable: Optional[Gio.Cancellable] = None,
    ) -> None:
        """For long-running mutations (install/remove/override): stream
        stdout line-by-line so the UI can show live progress instead of
        going silent until the process exits.
        """
        try:
            proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as exc:
            on_done(CommandResult(ok=False, returncode=-1, stdout="", stderr=str(exc)))
            return

        # Chunked reads rather than read_line_async: PyGObject's
        # read_line_finish returns b"" for BOTH a genuine blank line and
        # EOF (verified), so a line-based loop cannot detect the end of
        # the stream and spins forever. A zero-length read_bytes result is
        # an unambiguous EOF.
        stdout_stream = proc.get_stdout_pipe()
        collected: list[str] = []
        pending = [""]

        def _read_next() -> None:
            stdout_stream.read_bytes_async(
                8192, GLib.PRIORITY_DEFAULT, cancellable, _on_chunk_read
            )

        def _emit_lines(text: str, flush: bool = False) -> None:
            buffer = pending[0] + text
            lines = buffer.split("\n")
            trailing = lines.pop()
            if flush and trailing:
                lines.append(trailing)
                trailing = ""
            pending[0] = trailing
            for line in lines:
                collected.append(line + "\n")
                on_line(line)

        def _on_chunk_read(source: Gio.InputStream, res: Gio.AsyncResult) -> None:
            try:
                chunk = source.read_bytes_finish(res)
            except GLib.Error:
                chunk = None
            if chunk is None or chunk.get_size() == 0:
                if pending[0]:
                    _emit_lines("", flush=True)
                _wait_exit()
                return
            _emit_lines(chunk.get_data().decode("utf-8", errors="replace"))
            _read_next()

        def _wait_exit() -> None:
            proc.wait_check_async(cancellable, _on_exit)

        def _on_exit(source: Gio.Subprocess, res: Gio.AsyncResult) -> None:
            try:
                source.wait_check_finish(res)
                ok = True
            except GLib.Error:
                ok = source.get_exit_status() == 0
            stderr_text = ""
            stderr_pipe = source.get_stderr_pipe()
            if stderr_pipe is not None:
                try:
                    stderr_bytes = stderr_pipe.read_bytes(65536, cancellable)
                    stderr_text = stderr_bytes.get_data().decode("utf-8", errors="replace")
                except GLib.Error:
                    pass
            rc = source.get_exit_status()
            on_done(
                CommandResult(
                    ok=(rc == 0),
                    returncode=rc,
                    stdout="".join(collected),
                    stderr=stderr_text,
                )
            )

        _read_next()
