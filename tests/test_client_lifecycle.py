import threading
import time
import unittest
from unittest.mock import patch

from classes.client_manager import ClientManager


class FakeMemoryManager:
    def __init__(self):
        self.pm = object()
        self.close_calls = 0
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        self.pm = object()
        return True

    def close(self):
        self.close_calls += 1
        self.pm = None


class FakeFeature:
    def __init__(self):
        self.is_running = False
        self.stop_event = threading.Event()
        self.started = threading.Event()
        self.start_calls = 0
        self.config = None

    def update_config(self, config):
        self.config = config

    def start(self):
        self.start_calls += 1
        self.started.set()
        self.stop_event.wait(5.0)
        self.is_running = False

    def stop(self):
        self.stop_event.set()


class DelayedStopFeature(FakeFeature):
    def start(self):
        self.start_calls += 1
        self.started.set()
        self.stop_event.wait(5.0)
        time.sleep(0.05)
        self.is_running = False


class FakeMainWindow:
    def __init__(self, feature):
        self.memory_manager = FakeMemoryManager()
        self.features = {
            "Overlay": {
                "name": "Overlay",
                "instance": feature,
            }
        }
        self.overlay_thread = None
        self.status_updates = []

    def update_client_status(self, status, color):
        self.status_updates.append((status, color))


class AlwaysAliveThread:
    def __init__(self):
        self.join_timeout = None

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_timeout = timeout


class ClientLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.feature = FakeFeature()
        self.window = FakeMainWindow(self.feature)
        self.manager = ClientManager(self.window)

    def tearDown(self):
        thread = self.window.overlay_thread
        if isinstance(thread, threading.Thread) and thread.is_alive():
            self.feature.stop()
            thread.join(timeout=1.0)

    def test_start_stop_start_creates_a_fresh_worker(self):
        config = {"Overlay": {"target_fps": 60}}

        self.assertTrue(
            self.manager._start_feature("Overlay", self.feature, config)
        )
        self.assertTrue(self.feature.started.wait(timeout=1.0))
        first_thread = self.window.overlay_thread

        self.assertTrue(self.manager._stop_feature("Overlay", self.feature))
        self.assertIsNone(self.window.overlay_thread)
        self.assertFalse(first_thread.is_alive())

        self.feature.started.clear()
        self.assertTrue(
            self.manager._start_feature("Overlay", self.feature, config)
        )
        self.assertTrue(self.feature.started.wait(timeout=1.0))
        second_thread = self.window.overlay_thread

        self.assertIsNot(first_thread, second_thread)
        self.assertEqual(self.feature.start_calls, 2)
        self.assertTrue(self.manager._stop_feature("Overlay", self.feature))

    def test_duplicate_start_is_blocked_while_worker_is_alive(self):
        config = {"Overlay": {}}
        self.assertTrue(
            self.manager._start_feature("Overlay", self.feature, config)
        )
        self.assertTrue(self.feature.started.wait(timeout=1.0))
        thread = self.window.overlay_thread

        self.assertFalse(
            self.manager._start_feature("Overlay", self.feature, config)
        )
        self.assertIs(self.window.overlay_thread, thread)
        self.assertEqual(self.feature.start_calls, 1)

    def test_stop_waits_for_delayed_worker_shutdown(self):
        feature = DelayedStopFeature()
        window = FakeMainWindow(feature)
        manager = ClientManager(window)

        self.assertTrue(manager._start_feature("Overlay", feature, {}))
        self.assertTrue(feature.started.wait(timeout=1.0))
        thread = window.overlay_thread

        self.assertTrue(manager._stop_feature("Overlay", feature))
        self.assertFalse(thread.is_alive())
        self.assertIsNone(window.overlay_thread)

    def test_stop_preserves_reference_to_unfinished_worker(self):
        thread = AlwaysAliveThread()
        self.feature.is_running = True
        self.window.overlay_thread = thread

        self.assertFalse(
            self.manager._stop_feature("Overlay", self.feature)
        )
        self.assertIs(self.window.overlay_thread, thread)
        self.assertEqual(thread.join_timeout, 1.5)

    def test_public_start_stop_start_reinitializes_memory(self):
        with patch(
            "classes.client_manager.Utility.is_game_running",
            return_value=True,
        ), patch(
            "classes.client_manager.ConfigManager.load_config",
            return_value={"General": {"Overlay": True}},
        ):
            self.manager.start_client()
            self.assertTrue(self.feature.started.wait(timeout=1.0))
            first_thread = self.window.overlay_thread
            self.assertTrue(self.manager.stop_client())
            self.assertIsNone(self.window.memory_manager.pm)

            self.feature.started.clear()
            self.manager.start_client()
            self.assertTrue(self.feature.started.wait(timeout=1.0))
            self.assertIsNot(self.window.overlay_thread, first_thread)
            self.assertTrue(self.manager.stop_client())

        self.assertEqual(self.window.memory_manager.initialize_calls, 2)
        self.assertEqual(self.window.memory_manager.close_calls, 2)
        self.assertEqual(
            [status for status, _ in self.window.status_updates],
            ["Active", "Inactive", "Active", "Inactive"],
        )

    def test_no_features_preserves_memory_until_previous_worker_stops(self):
        thread = AlwaysAliveThread()
        self.feature.is_running = True
        self.window.overlay_thread = thread

        with patch(
            "classes.client_manager.Utility.is_game_running",
            return_value=True,
        ), patch(
            "classes.client_manager.ConfigManager.load_config",
            return_value={"General": {"Overlay": False}},
        ), patch("classes.client_manager.messagebox"):
            self.manager.start_client()

        self.assertEqual(self.window.memory_manager.close_calls, 0)
        self.assertIs(self.window.overlay_thread, thread)
        self.assertTrue(self.feature.stop_event.is_set())
        self.assertEqual(thread.join_timeout, 1.5)

    def test_failed_start_preserves_memory_used_by_previous_worker(self):
        thread = AlwaysAliveThread()
        self.feature.is_running = True
        self.window.overlay_thread = thread
        self.window.features["Trigger"] = {
            "name": "Trigger",
            "instance": FakeFeature(),
        }

        with patch(
            "classes.client_manager.Utility.is_game_running",
            return_value=True,
        ), patch(
            "classes.client_manager.ConfigManager.load_config",
            return_value={"General": {"Overlay": False, "Trigger": True}},
        ), patch.object(
            self.manager,
            "_start_feature",
            return_value=False,
        ), patch("classes.client_manager.messagebox"):
            self.manager.start_client()

        self.assertEqual(self.window.memory_manager.close_calls, 0)
        self.assertIs(self.window.overlay_thread, thread)
        self.assertTrue(self.feature.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
