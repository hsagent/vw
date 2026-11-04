import importlib.util
import os
import sys
import threading
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, call, patch

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
        self.patches.enter_context(patch.object(esp.CS2Overlay, "_configure_passive_window"))
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

    def test_inactive_frame_pumps_before_wait_without_reading_entities(self):
        self.native.overlay_loop.side_effect = [True, False]
        events = []
        self.native.begin_drawing.side_effect = lambda: events.append("begin")
        self.native.end_drawing.side_effect = lambda: events.append("end")
        self.instance.stop_event = Mock()
        self.instance.stop_event.is_set.return_value = False
        self.instance.stop_event.wait.side_effect = lambda timeout: events.append("wait") or False
        with patch.object(esp.Utility, "is_game_active", return_value=False):
            self.instance.start()
        self.assertEqual(events, ["begin", "end", "wait"])
        self.memory.read_floats.assert_not_called()
        self.memory.read_longlong.assert_not_called()

    def test_invalid_matrix_still_pumps_a_transparent_frame(self):
        self.native.overlay_loop.side_effect = [True, False]
        self.memory.read_floats.return_value = []
        self.instance.start()
        self.native.begin_drawing.assert_called_once()
        self.native.end_drawing.assert_called_once()
        self.memory.read_longlong.assert_not_called()

    def test_active_to_inactive_transition_presents_second_blank_frame(self):
        self.native.overlay_loop.side_effect = [True, True, False]
        with patch.object(esp.Utility, "is_game_active", side_effect=[True, False]), patch.object(
            self.instance, "discover_extra_indices",
        ), patch.object(self.instance, "iterate_entities", return_value=iter(())):
            self.instance.start()
        self.assertEqual(self.native.begin_drawing.call_count, 2)
        self.assertEqual(self.native.end_drawing.call_count, 2)
        self.memory.read_floats.assert_called_once()

    def test_controller_discovery_keeps_higher_slots_for_respawn(self):
        self.memory.get_controller_indices.return_value = (1, 64, 700)
        self.instance.discover_extra_indices(0x100000)
        self.assertEqual(self.instance._extra_indices, {700})
        self.memory.get_entity.assert_not_called()
        self.memory.read_int.assert_not_called()

    def test_incomplete_roster_keeps_verified_higher_controller_slots(self):
        self.instance._extra_indices = {65, 700}
        self.memory.get_controller_indices.return_value = None
        self.memory.get_entity.side_effect = lambda index: 0x100000 + index if index in (65, 700) else 0
        self.memory.handle_to_index.return_value = None
        self.instance.discover_extra_indices(0x100000)
        self.assertEqual(self.instance._extra_indices, {65, 700})

    def test_zero_pawn_origin_uses_available_scene_origin(self):
        memory = Mock(m_iHealth=0x34C, m_iTeamNum=0x3E7, m_vOldOrigin=0x14A4,
                      m_pGameSceneNode=0x330, m_vecAbsOrigin=0xC8, m_bDormant=0xEF,
                      m_iszPlayerName=0x6FC, m_pBoneArray=0x170)
        memory.read_int.return_value = 100
        memory.read_uint8.side_effect = [0, 3]
        memory.read_longlong.side_effect = [0x300000, 0]
        memory.read_vec3.side_effect = [
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 1.0, "y": 2.0, "z": 3.0},
        ]
        memory.read_string.return_value = "Player"
        entity = esp.Entity(0x100000, 0x200000, memory)
        self.assertTrue(entity.update(False, False))
        self.assertEqual(entity.pos, {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertEqual(memory.read_vec3.call_args_list[1], call(0x300000 + 0xC8))

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


@unittest.skipUnless(os.name == "nt", "Windows overlay styles")
class OverlayWindowTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.native = self.patches.enter_context(patch.object(esp, "overlay"))
        self.api = self.patches.enter_context(patch.object(esp, "win32gui"))
        self.process = self.patches.enter_context(patch.object(esp, "win32process"))
        self.hwnd = 0x1234567801
        self.native.get_window_handle.return_value = self.hwnd
        self.api.IsWindow.return_value = True
        self.process.GetWindowThreadProcessId.return_value = (threading.get_native_id(), os.getpid())
        self.style = (
            esp.win32con.WS_EX_LAYERED | esp.win32con.WS_EX_TRANSPARENT
            | esp.win32con.WS_EX_TOPMOST | esp.win32con.WS_EX_APPWINDOW
        )
        self.api.GetWindowLong.side_effect = lambda hwnd, key: self.style
        self.api.SetWindowLong.side_effect = lambda hwnd, key, value: setattr(self, "style", value)
        self.api.GetForegroundWindow.return_value = 0x7777
        self.instance = esp.CS2Overlay.__new__(esp.CS2Overlay)

    def test_owned_window_is_passive_and_existing_layering_is_preserved(self):
        self.instance._configure_passive_window()
        self.assertTrue(self.style & esp.win32con.WS_EX_NOACTIVATE)
        self.assertTrue(self.style & esp.win32con.WS_EX_TOOLWINDOW)
        self.assertTrue(self.style & esp.win32con.WS_EX_LAYERED)
        self.assertTrue(self.style & esp.win32con.WS_EX_TRANSPARENT)
        self.assertTrue(self.style & esp.win32con.WS_EX_TOPMOST)
        self.assertFalse(self.style & esp.win32con.WS_EX_APPWINDOW)
        flags = self.api.SetWindowPos.call_args.args[-1]
        self.assertTrue(flags & esp.win32con.SWP_NOACTIVATE)
        self.assertTrue(flags & esp.win32con.SWP_NOZORDER)
        self.api.ShowWindow.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()

    def test_foreign_or_wrong_thread_window_is_rejected_without_writes(self):
        for thread_id, process_id in (
            (threading.get_native_id(), os.getpid() + 1),
            (threading.get_native_id() + 1, os.getpid()),
        ):
            with self.subTest(thread_id=thread_id, process_id=process_id):
                self.process.GetWindowThreadProcessId.return_value = (thread_id, process_id)
                with self.assertRaises(RuntimeError):
                    self.instance._configure_passive_window()
        self.api.SetWindowLong.assert_not_called()
        self.api.SetWindowPos.assert_not_called()
        self.api.ShowWindow.assert_not_called()

    def test_initial_focus_is_relinquished_only_for_owned_overlay(self):
        self.api.GetForegroundWindow.return_value = self.hwnd
        self.instance._configure_passive_window()
        self.assertEqual(self.api.ShowWindow.call_args_list, [
            call(self.hwnd, esp.win32con.SW_HIDE),
            call(self.hwnd, esp.win32con.SW_SHOWNA),
        ])
        self.api.SetForegroundWindow.assert_not_called()

    def test_passive_window_configuration_is_idempotent(self):
        self.instance._configure_passive_window()
        self.instance._configure_passive_window()
        self.api.SetWindowLong.assert_called_once()

    def test_failed_style_write_is_detected_before_window_changes(self):
        self.api.SetWindowLong.side_effect = None
        with self.assertRaises(RuntimeError):
            self.instance._configure_passive_window()
        self.api.SetWindowPos.assert_not_called()
        self.api.ShowWindow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
