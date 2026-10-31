import importlib.util
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from classes.logger import LoggerConfig, SuppressErrorFilter


# Load the real worker without caching a stub-backed production module.
spec = importlib.util.spec_from_file_location(
    "overlay_under_test",
    Path(__file__).resolve().parents[1] / "classes" / "esp.py",
)
esp = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"pyMeow": types.ModuleType("pyMeow")}):
    spec.loader.exec_module(esp)


class OverlayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.native = self.patches.enter_context(patch.object(esp, "overlay"))
        self.patches.enter_context(
            patch.object(
                esp.ConfigManager,
                "load_config",
                return_value={"Overlay": dict(esp.ConfigManager.DEFAULT_CONFIG["Overlay"])},
            )
        )
        self.patches.enter_context(patch.object(esp.Colors, "init_colors"))
        self.patches.enter_context(
            patch.object(esp.Utility, "is_game_active", return_value=True)
        )
        self.native.get_screen_width.return_value = 800
        self.native.get_screen_height.return_value = 600
        self.native.overlay_loop.return_value = False
        self.memory = Mock(client_base=0, dwViewMatrix=0, dwLocalPlayerController=0)
        self.memory.read_floats.return_value = [0.0] * 16
        self.memory.read_longlong.return_value = 0
        self.instance = esp.CS2Overlay(self.memory)

    def test_constructor_does_not_call_native_overlay(self):
        self.assertEqual(self.native.mock_calls, [])

    def test_entity_reads_uint8_team_from_schema_field(self):
        memory = Mock(
            m_iHealth=0x34C,
            m_iTeamNum=0x3E7,
            m_vOldOrigin=0x14A4,
            m_pGameSceneNode=0x330,
            m_iszPlayerName=0x6FC,
        )
        memory.read_int.return_value = 100
        memory.read_uint8.return_value = 3
        memory.read_longlong.return_value = 0
        memory.read_vec3.return_value = {"x": 1.0, "y": 2.0, "z": 3.0}
        memory.read_string.return_value = "Enemy"
        entity = esp.Entity(0x100000, 0x200000, memory)

        self.assertTrue(entity.update(use_transliteration=False, skeleton_enabled=False))
        self.assertEqual(entity.team, 3)
        memory.read_uint8.assert_called_once_with(0x200000 + 0x3E7)

    def test_stop_before_worker_entry_is_not_cleared(self):
        self.instance.stop()
        self.instance.start()

        self.assertTrue(self.instance.stop_event.is_set())
        self.assertFalse(self.instance.is_running)
        self.native.overlay_init.assert_not_called()
        self.native.overlay_close.assert_not_called()

    def test_post_init_failure_closes_initialized_overlay(self):
        self.native.get_screen_height.side_effect = RuntimeError("screen query failed")

        with self.assertLogs(esp.logger, level="ERROR"):
            self.instance.start()

        self.native.overlay_init.assert_called_once()
        self.native.overlay_close.assert_called_once()
        self.assertFalse(self.instance.is_running)

    def test_init_failure_does_not_close_uninitialized_overlay(self):
        self.native.overlay_init.side_effect = RuntimeError("init failed")

        with self.assertLogs(esp.logger, level="ERROR"):
            self.instance.start()

        self.native.overlay_close.assert_not_called()
        self.assertFalse(self.instance.is_running)

    def test_loop_error_keeps_traceback_and_is_not_filtered(self):
        self.native.overlay_loop.side_effect = [
            RuntimeError("Could not read memory at 0x0"),
            False,
        ]

        with self.assertLogs(esp.logger, level="ERROR") as captured:
            self.instance.start()

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertIsNotNone(record.exc_info)
        self.assertTrue(SuppressErrorFilter(LoggerConfig().suppress_patterns).filter(record))
        self.native.overlay_close.assert_called_once()
        self.assertFalse(self.instance.is_running)

    def test_frame_error_keeps_traceback_and_closes_overlay(self):
        self.native.overlay_loop.side_effect = [True, False]
        self.native.begin_drawing.side_effect = RuntimeError("drawing failed")

        with patch.object(self.instance, "discover_extra_indices"), patch.object(
            self.instance,
            "iterate_entities",
            return_value=iter(()),
        ), self.assertLogs(esp.logger, level="ERROR") as captured:
            self.instance.start()

        self.assertEqual(len(captured.records), 1)
        self.assertIsNotNone(captured.records[0].exc_info)
        self.native.end_drawing.assert_not_called()
        self.native.overlay_close.assert_called_once()
        self.assertFalse(self.instance.is_running)


if __name__ == "__main__":
    unittest.main()
