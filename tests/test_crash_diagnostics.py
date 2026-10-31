import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

from classes.crash_diagnostics import CrashDiagnostics


class CrashDiagnosticsTests(unittest.TestCase):
    def test_enable_records_thread_exception_and_close_restores_hook(self):
        diagnostics = CrashDiagnostics()
        original_hook = threading.excepthook

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "classes.crash_diagnostics.faulthandler.is_enabled",
            return_value=False,
        ), patch(
            "classes.crash_diagnostics.faulthandler.enable"
        ) as enable_mock, patch(
            "classes.crash_diagnostics.faulthandler.disable"
        ) as disable_mock:
            report_path = diagnostics.enable(temp_dir, version="test-version")
            self.assertIsNotNone(report_path)
            self.assertTrue(report_path.is_file())
            self.assertIsNot(threading.excepthook, original_hook)
            enable_mock.assert_called_once()

            try:
                raise RuntimeError("worker failed")
            except RuntimeError:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                args = types.SimpleNamespace(
                    exc_type=exc_type,
                    exc_value=exc_value,
                    exc_traceback=exc_traceback,
                    thread=types.SimpleNamespace(name="TestWorker"),
                )
                diagnostics._write_thread_exception(args)

            diagnostics.close()
            diagnostics.close()

            self.assertIs(threading.excepthook, original_hook)
            disable_mock.assert_called_once()
            report = Path(report_path).read_text(encoding="utf-8")
            self.assertIn("Version: test-version", report)
            self.assertIn("Unhandled exception in thread TestWorker", report)
            self.assertIn("RuntimeError: worker failed", report)
            self.assertIn("Diagnostics closed cleanly", report)

    def test_enable_failure_rolls_back_only_owned_handlers(self):
        for already_enabled in (False, True):
            with self.subTest(already_enabled=already_enabled):
                diagnostics = CrashDiagnostics()
                original_hook = threading.excepthook
                report = mock_open()()
                report.flush.side_effect = OSError("flush failed")
                cleanup_order = []
                report.close.side_effect = lambda: cleanup_order.append("close")

                with tempfile.TemporaryDirectory() as temp_dir, patch(
                    "classes.crash_diagnostics.Path.open",
                    return_value=report,
                ), patch(
                    "classes.crash_diagnostics.faulthandler.is_enabled",
                    return_value=already_enabled,
                ), patch(
                    "classes.crash_diagnostics.faulthandler.enable",
                ) as enable_mock, patch(
                    "classes.crash_diagnostics.faulthandler.disable",
                    side_effect=lambda: cleanup_order.append("disable"),
                ) as disable_mock, patch("sys.stderr"):
                    self.assertIsNone(diagnostics.enable(temp_dir))
                    diagnostics.close()

                self.assertIs(threading.excepthook, original_hook)
                self.assertIsNone(diagnostics._report_file)
                self.assertIsNone(diagnostics.report_path)
                self.assertFalse(diagnostics._owns_faulthandler)
                if already_enabled:
                    enable_mock.assert_not_called()
                    disable_mock.assert_not_called()
                    self.assertEqual(cleanup_order, ["close"])
                else:
                    enable_mock.assert_called_once()
                    disable_mock.assert_called_once()
                    self.assertEqual(cleanup_order, ["disable", "close"])


if __name__ == "__main__":
    unittest.main()
