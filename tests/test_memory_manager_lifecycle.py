import unittest
from unittest.mock import patch

from classes.memory_manager import MemoryManager


class FakePymem:
    def __init__(self):
        self.close_calls = 0

    def close_process(self):
        self.close_calls += 1


class SequencedPymem(FakePymem):
    def __init__(self, values):
        super().__init__()
        self.values = iter(values)
        self.read_addresses = []

    def read_longlong(self, address):
        self.read_addresses.append(address)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class MemoryManagerLifecycleTests(unittest.TestCase):
    def test_close_is_idempotent_and_resets_process_state(self):
        manager = MemoryManager()
        fake_pm = FakePymem()
        manager.pm = fake_pm
        manager.client_base = 0x1000
        manager.ent_list = 0x2000
        manager._ent_list_ts = 123.0
        manager._stride_detected = True

        manager.close()
        manager.close()

        self.assertEqual(fake_pm.close_calls, 1)
        self.assertIsNone(manager.pm)
        self.assertIsNone(manager.client_base)
        self.assertIsNone(manager.ent_list)
        self.assertEqual(manager._ent_list_ts, 0.0)
        self.assertFalse(manager._stride_detected)
        self.assertIsNone(manager._last_entity_list_error)

    def test_entity_list_pointer_retries_until_available(self):
        manager = MemoryManager()
        manager.pm = SequencedPymem([0, OSError("not ready"), 0xABCDEF])
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200

        with patch("classes.memory_manager.time.sleep") as sleep_mock:
            pointer = manager._read_entity_list_pointer()

        self.assertEqual(pointer, 0xABCDEF)
        self.assertEqual(
            manager.pm.read_addresses,
            [0x100200, 0x100200, 0x100200],
        )
        self.assertEqual(sleep_mock.call_count, 2)
        self.assertIsInstance(manager._last_entity_list_error, OSError)

    def test_initialize_force_refreshes_a2x_after_entity_list_failure(self):
        manager = MemoryManager()
        manager.pm = FakePymem()
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.dwLocalPlayerPawn = 0x300
        manager.dwLocalPlayerController = 0x400
        manager.dwViewMatrix = 0x500

        with patch(
            "classes.memory_manager.updater.load_configured_offsets",
            side_effect=[True, True],
        ) as load_mock, patch.object(
            manager,
            "initialize_pymem",
            return_value=True,
        ), patch.object(
            manager,
            "get_client_module",
            return_value=True,
        ), patch.object(
            manager,
            "load_offsets",
        ), patch.object(
            manager,
            "_read_entity_list_pointer",
            side_effect=[0, 0xABCDEF],
        ), patch.object(
            manager,
            "detect_entity_entry_size",
        ), patch.object(
            __import__("classes.memory_manager", fromlist=["updater"]).updater,
            "_loaded_source",
            "a2x",
        ):
            self.assertTrue(manager.initialize())

        self.assertEqual(load_mock.call_args_list[1].kwargs, {"force_reload": True})
        self.assertEqual(manager.ent_list, 0xABCDEF)

    def test_entity_list_pointer_preserves_last_read_error(self):
        manager = MemoryManager()
        manager.pm = SequencedPymem([OSError("denied")] * 5)
        manager.client_base = 0x200000
        manager.dwEntityList = 0x300

        with patch("classes.memory_manager.time.sleep"):
            pointer = manager._read_entity_list_pointer()

        self.assertEqual(pointer, 0)
        self.assertEqual(str(manager._last_entity_list_error), "denied")


if __name__ == "__main__":
    unittest.main()
