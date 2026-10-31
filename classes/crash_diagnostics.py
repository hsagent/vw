import faulthandler
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO


class CrashDiagnostics:
    """Writes fatal-error and unhandled-thread diagnostics to a separate file."""

    def __init__(self) -> None:
        self.report_path: Optional[Path] = None
        self._report_file: Optional[TextIO] = None
        self._previous_threading_hook = None
        self._threading_hook = None
        self._owns_faulthandler = False
        self._lock = threading.RLock()

    def enable(self, log_directory: str, version: str = "unknown") -> Optional[Path]:
        """Enables diagnostics and returns the report path, or None on failure."""
        with self._lock:
            if self._report_file is not None:
                return self.report_path

            try:
                directory = Path(log_directory)
                directory.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                self.report_path = directory / f"crash-{timestamp}-{os.getpid()}.log"
                self._report_file = self.report_path.open(
                    "w",
                    encoding="utf-8",
                    buffering=1,
                )
                self._write_header(version)

                self._previous_threading_hook = threading.excepthook
                previous_hook = self._previous_threading_hook

                def thread_hook(args):
                    self._write_thread_exception(args)
                    try:
                        previous_hook(args)
                    except Exception:
                        pass

                self._threading_hook = thread_hook
                threading.excepthook = thread_hook

                # Do not replace a faulthandler installed by an embedding host or
                # test runner because Python cannot restore its original file.
                if not faulthandler.is_enabled():
                    faulthandler.enable(file=self._report_file, all_threads=True)
                    self._owns_faulthandler = True
                else:
                    self._report_file.write(
                        "Faulthandler was already enabled; the existing handler was preserved.\n\n"
                    )
                self._report_file.flush()
                return self.report_path
            except Exception as exc:
                self.close()
                self.report_path = None
                print(
                    f"Warning: failed to enable crash diagnostics: {exc}",
                    file=sys.stderr,
                )
                return None

    def _write_header(self, version: str) -> None:
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._report_file.write(
            "My Project crash diagnostics\n"
            f"Started: {started_at}\n"
            f"Version: {version}\n"
            f"Python: {sys.version}\n"
            f"Executable: {sys.executable}\n"
            f"Platform: {platform.platform()}\n"
            f"PID: {os.getpid()}\n\n"
        )

    def _write_thread_exception(self, args) -> None:
        with self._lock:
            if self._report_file is None:
                return
            try:
                thread = getattr(args, "thread", None)
                thread_name = getattr(thread, "name", "unknown")
                self._report_file.write(
                    f"Unhandled exception in thread {thread_name}:\n"
                )
                traceback.print_exception(
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                    file=self._report_file,
                )
                self._report_file.write("\n")
                self._report_file.flush()
            except Exception:
                pass

    def _restore_threading_hook(self) -> None:
        if (
            self._threading_hook is not None
            and threading.excepthook is self._threading_hook
            and self._previous_threading_hook is not None
        ):
            threading.excepthook = self._previous_threading_hook
        self._threading_hook = None
        self._previous_threading_hook = None

    def _close_report_file(self) -> None:
        report_file = self._report_file
        self._report_file = None
        if report_file is not None:
            try:
                report_file.close()
            except Exception:
                pass

    def close(self) -> None:
        """Disables owned handlers and marks a normal application shutdown."""
        with self._lock:
            if self._report_file is None:
                return

            if self._owns_faulthandler:
                try:
                    faulthandler.disable()
                except Exception:
                    pass
                self._owns_faulthandler = False

            self._restore_threading_hook()
            try:
                self._report_file.write(
                    f"Diagnostics closed cleanly: "
                    f"{datetime.now().astimezone().isoformat(timespec='seconds')}\n"
                )
                self._report_file.flush()
            except Exception:
                pass
            self._close_report_file()
