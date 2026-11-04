import time
import struct
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


class EntityLayoutPymem(FakePymem):
    def __init__(self):
        super().__init__()
        self.ent_list = 0x200000
        self.chunk = 0x300000
        self.controller = 0x400000
        self.pawn = 0x500000
        self.controller_index = 1
        self.pawn_index = 317
        self.entry_size = 120
        self.name_offset = 0x6FC
        self.handle_offset = 0x92C
        self.team_offset = 0x3E7
        self.health_offset = 0x34C
        self.handle_value = self.pawn_index

    def read_longlong(self, address):
        if address == self.ent_list + 0x10:
            return self.chunk
        if address == self.chunk + self.entry_size * self.controller_index:
            return self.controller
        if address == self.chunk + self.entry_size * self.pawn_index:
            return self.pawn
        return 0

    def read_int(self, address):
        if address == self.controller + self.handle_offset:
            return self.handle_value
        if address == self.pawn + self.health_offset:
            return 100
        if address == self.pawn + self.team_offset:
            # The following uint32 m_spawnflags pollutes an int32 team read.
            return 0x12000003
        return 0

    def read_bytes(self, address, size):
        if address == self.controller + self.name_offset:
            return b"Enemy\x00".ljust(size, b"\x00")
        if address == self.pawn + self.team_offset and size == 1:
            return b"\x03"
        return b"\x00" * size


class IdentityAnchoredPymem(FakePymem):
    def __init__(self, entry_size=112):
        super().__init__()
        self.client_base = 0x100000
        self.ent_list = 0x200000
        self.chunk = 0x300008
        self.entry_size = entry_size
        self.controller_index = 1
        self.pawn_index = 303
        self.target_index = 329
        self.controller = 0x400000
        self.pawn = 0x500000
        self.target = 0x600000
        self.controller_identity = (
            self.chunk + self.controller_index * self.entry_size
        )
        self.pawn_identity = self.chunk + self.pawn_index * self.entry_size
        self.dw_entity_list = 0x200
        self.dw_controller = 0x300
        self.dw_pawn = 0x400
        self.m_p_entity = 0x10
        self.old_root_reads = 0

    def read_longlong(self, address):
        values = {
            self.client_base + self.dw_entity_list: self.ent_list,
            self.client_base + self.dw_controller: self.controller,
            self.client_base + self.dw_pawn: self.pawn,
            self.controller + self.m_p_entity: self.controller_identity,
            self.pawn + self.m_p_entity: self.pawn_identity,
            self.target + self.m_p_entity: self.chunk + self.target_index * self.entry_size,
            self.controller_identity: self.controller,
            self.pawn_identity: self.pawn,
            self.chunk + self.target_index * self.entry_size: self.target,
        }
        if address == self.ent_list + 0x10:
            self.old_root_reads += 1
            return 0xDEADBEEF
        return values.get(address, 0)

    def read_int(self, address):
        if address == self.controller_identity + 0x10:
            return 0x01A38001
        if address == self.pawn_identity + 0x10:
            return 0x01E5012F
        if address == self.chunk + self.target_index * self.entry_size + 0x10:
            return 0x01000000 | self.target_index
        return 0


class DeathmatchPymem(IdentityAnchoredPymem):
    def __init__(self, player_count=24):
        super().__init__()
        self.controller_indices = list(range(1, player_count + 1))
        self.pawn_indices = [512 + index for index in self.controller_indices]
        self.serials = [0x01000000] * player_count
        self.handle_offset = 0x92C
        self.rebuild()

    def rebuild(self):
        self.pointers = {
            self.client_base + self.dw_entity_list: self.ent_list,
        }
        self.ints = {}
        self.identities = {}
        groups = []
        for kind, indices in enumerate((self.controller_indices, self.pawn_indices)):
            entries = []
            for player, index in enumerate(indices):
                entity = (0x400000 if kind == 0 else 0x600000) + player * 0x1000
                chunk = 0x1000000 + (index >> 9) * 0x20000 + 8
                identity = chunk + (index & 0x1FF) * self.entry_size
                raw = self.serials[player] | index
                self.pointers[identity] = entity
                self.pointers[identity + 8] = 0x2000000 + kind * 0x1000
                self.pointers[entity + self.m_p_entity] = identity
                self.ints[identity + 0x10] = raw
                entries.append((entity, identity, raw))
            groups.append(entries)
        for kind, entries in enumerate(groups):
            for player, (entity, identity, raw) in enumerate(entries):
                data = bytearray(112)
                struct.pack_into("<QQI", data, 0, entity, 0x2000000 + kind * 0x1000, raw)
                previous = entries[player - 1][1] if player else 0
                following = entries[player + 1][1] if player + 1 < len(entries) else 0
                struct.pack_into("<QQ", data, 0x60, previous, following)
                self.identities[identity] = bytes(data)
        for player, (controller, _, _) in enumerate(groups[0]):
            self.ints[controller + self.handle_offset] = groups[1][player][2]
        self.controller, self.controller_identity, _ = groups[0][0]
        self.pawn, self.pawn_identity, _ = groups[1][0]
        self.pointers[self.client_base + self.dw_controller] = self.controller
        self.pointers[self.client_base + self.dw_pawn] = self.pawn

    def read_longlong(self, address):
        if address == self.ent_list + 0x10:
            self.old_root_reads += 1
            return 0xDEADBEEF
        return self.pointers.get(address, 0)

    def read_int(self, address):
        value = self.ints.get(address, 0)
        return value - 0x100000000 if value & 0x80000000 else value

    def read_bytes(self, address, size):
        return self.identities.get(address, b"\x00" * size)[:size]


class MemoryManagerLifecycleTests(unittest.TestCase):
    def _deathmatch_manager(self):
        manager = MemoryManager()
        manager.pm = DeathmatchPymem()
        manager.client_base = manager.pm.client_base
        manager.dwEntityList = manager.pm.dw_entity_list
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager.m_pPrevByClass = 0x60
        manager.m_pNextByClass = 0x68
        manager.m_hPlayerPawn = manager.pm.handle_offset
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        return manager

    def test_close_is_idempotent_and_resets_process_state(self):
        manager = MemoryManager()
        fake_pm = FakePymem()
        manager.pm = fake_pm
        manager.client_base = 0x1000
        manager.ent_list = 0x2000
        manager._ent_list_ts = 123.0
        manager._stride_detected = True
        manager._entity_chunks[0] = 0x300000

        manager.close()
        manager.close()

        self.assertEqual(fake_pm.close_calls, 1)
        self.assertIsNone(manager.pm)
        self.assertIsNone(manager.client_base)
        self.assertIsNone(manager.ent_list)
        self.assertEqual(manager._ent_list_ts, 0.0)
        self.assertFalse(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {})
        self.assertEqual(manager._layout_generation, 1)
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

    def test_initialize_force_refreshes_selected_network_source_after_entity_list_failure(self):
        for source in ("a2x", "ivtim", "hanstxx", "cesiumoq"):
            with self.subTest(source=source):
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
                    manager, "initialize_pymem", return_value=True,
                ), patch.object(
                    manager, "get_client_module", return_value=True,
                ), patch.object(
                    manager, "load_offsets",
                ), patch.object(
                    manager, "_read_entity_list_pointer", side_effect=[0, 0xABCDEF],
                ), patch.object(
                    manager, "detect_entity_entry_size",
                ), patch.object(
                    __import__("classes.memory_manager", fromlist=["updater"]).updater,
                    "_loaded_source", source,
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

    def test_stride_detection_reads_uint8_team_and_selects_valid_layout(self):
        manager = MemoryManager()
        manager.pm = EntityLayoutPymem()
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        manager.m_iszPlayerName = manager.pm.name_offset
        manager.m_hPlayerPawn = manager.pm.handle_offset
        manager.m_iTeamNum = manager.pm.team_offset
        manager.m_iHealth = manager.pm.health_offset

        selected_size = manager.detect_entity_entry_size()

        self.assertEqual(selected_size, 120)
        self.assertTrue(manager._stride_detected)
        self.assertEqual(
            manager.read_int(manager.pm.pawn + manager.m_iTeamNum),
            0x12000003,
        )
        self.assertEqual(manager.read_uint8(manager.pm.pawn + manager.m_iTeamNum), 3)

    def test_local_identities_derive_stride_and_bypass_stale_entity_root(self):
        manager = MemoryManager()
        manager.pm = IdentityAnchoredPymem()
        manager.client_base = manager.pm.client_base
        manager.dwEntityList = manager.pm.dw_entity_list
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()

        self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertTrue(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {0: manager.pm.chunk})
        self.assertEqual(manager.local_controller_index, 1)
        self.assertEqual(manager.local_pawn_index, 303)
        self.assertEqual(manager.get_entity(329), manager.pm.target)
        self.assertFalse(manager.get_entity(512))
        self.assertEqual(manager.pm.old_root_reads, 0)

    def test_identity_stride_below_schema_minimum_is_rejected(self):
        manager = MemoryManager()
        manager.pm = IdentityAnchoredPymem(entry_size=104)
        manager.client_base = manager.pm.client_base
        manager.dwEntityList = manager.pm.dw_entity_list
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()

        self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertFalse(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {})

    def test_identity_handle_mutation_prevents_chunk_publication(self):
        manager = MemoryManager()
        manager.pm = IdentityAnchoredPymem()
        manager.client_base = manager.pm.client_base
        manager.dwEntityList = manager.pm.dw_entity_list
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        original_read_int = manager.pm.read_int
        handle_reads = 0

        def mutate_handles(address):
            nonlocal handle_reads
            if address in (
                manager.pm.controller_identity + 0x10,
                manager.pm.pawn_identity + 0x10,
            ):
                handle_reads += 1
                if handle_reads > 2:
                    return -1
            return original_read_int(address)

        with patch.object(manager.pm, "read_int", side_effect=mutate_handles):
            self.assertEqual(manager.detect_entity_entry_size(), 112)

        self.assertFalse(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {})

    def test_more_than_sixteen_pawns_resolve_across_entity_chunks(self):
        manager = self._deathmatch_manager()
        self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertTrue(manager._stride_detected)
        self.assertEqual(set(manager._entity_chunks), {0, 1})
        self.assertEqual(len(manager.get_controller_indices(manager.pm.controller)), 24)
        for player, index in enumerate(manager.pm.pawn_indices):
            self.assertEqual(manager.get_entity(index), 0x600000 + player * 0x1000)
        self.assertEqual(manager.pm.old_root_reads, 0)

    def test_layout_validates_each_duplicate_candidate_only_once(self):
        manager = self._deathmatch_manager()
        with patch.object(
            manager, "_identity_anchor_matches", wraps=manager._identity_anchor_matches,
        ) as validate_mock:
            self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertTrue(manager._stride_detected)
        self.assertLessEqual(validate_mock.call_count, 2 * (len(manager.pm.controller_indices) + 1))

    def test_incomplete_class_read_is_not_an_authoritative_roster(self):
        manager = self._deathmatch_manager()
        manager.detect_entity_entry_size()
        original_read = manager.pm.read_bytes
        failed_identity = next(identity for identity in manager.pm.identities if identity != manager.pm.controller_identity)

        def read_bytes(address, size):
            if address == failed_identity:
                raise OSError("transient class identity read failure")
            return original_read(address, size)

        with patch.object(manager.pm, "read_bytes", side_effect=read_bytes):
            self.assertIsNone(manager.get_controller_indices(manager.pm.controller))

    def test_remote_respawn_discovers_new_chunk_without_legacy_root(self):
        manager = self._deathmatch_manager()
        manager.detect_entity_entry_size()
        manager.pm.pawn_indices[1] = 1027
        manager.pm.serials[1] = 0x02000000
        manager.pm.rebuild()
        handle = manager.pm.ints[0x401000 + manager.m_hPlayerPawn]
        self.assertEqual(manager.get_entity_by_handle(handle), 0x601000)
        self.assertIn(2, manager._entity_chunks)
        self.assertEqual(manager.pm.old_root_reads, 0)

    def test_local_respawn_rebuilds_layout_when_anchors_use_different_chunks(self):
        manager = self._deathmatch_manager()
        manager.detect_entity_entry_size()
        manager.pm.pawn_indices[0] = 1027
        manager.pm.rebuild()
        manager._ent_list_ts = 0.0
        manager._ensure_ent_list()
        self.assertTrue(manager._stride_detected)
        self.assertEqual(manager.local_pawn_index, 1027)
        self.assertEqual(manager.get_entity(1027), manager.pm.pawn)
        self.assertEqual(manager.get_entity(manager.pm.pawn_indices[1]), 0x601000)
        self.assertEqual(manager.pm.old_root_reads, 0)

    def test_recycled_index_rejects_stale_handle_serial(self):
        manager = self._deathmatch_manager()
        manager.detect_entity_entry_size()
        old_handle = manager.pm.ints[0x401000 + manager.m_hPlayerPawn]
        manager.pm.serials[1] = 0x02000000
        manager.pm.rebuild()
        new_handle = manager.pm.ints[0x401000 + manager.m_hPlayerPawn]
        self.assertIsNone(manager.get_entity_by_handle(old_handle))
        self.assertEqual(manager.get_entity_by_handle(new_handle), 0x601000)

    def test_stale_layout_generation_cannot_publish_identity_chunk(self):
        manager = MemoryManager()
        manager.pm = IdentityAnchoredPymem()
        manager.client_base = manager.pm.client_base
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager._layout_generation = 2

        self.assertFalse(
            manager._detect_layout_from_local_identities(
                manager.pm.controller,
                manager.pm.pawn,
                expected_generation=1,
            )
        )
        self.assertFalse(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {})

    def test_verified_identity_layout_is_not_overwritten_by_legacy_retry(self):
        manager = MemoryManager()
        manager.pm = IdentityAnchoredPymem()
        manager.client_base = manager.pm.client_base
        manager.dwEntityList = manager.pm.dw_entity_list
        manager.dwLocalPlayerController = manager.pm.dw_controller
        manager.dwLocalPlayerPawn = manager.pm.dw_pawn
        manager.m_pEntity = manager.pm.m_p_entity
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        manager.detect_entity_entry_size()
        original_chunks = dict(manager._entity_chunks)
        original_generation = manager._layout_generation

        with patch.object(
            manager,
            "_detect_layout_from_local_identities",
            return_value=False,
        ), patch.object(manager, "_read_entity_raw") as legacy_read:
            self.assertEqual(manager.detect_entity_entry_size(), 112)

        legacy_read.assert_not_called()
        self.assertTrue(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, original_chunks)
        self.assertEqual(manager._layout_generation, original_generation)

    def test_failed_stride_detection_remains_retryable(self):
        manager = MemoryManager()
        manager.pm = EntityLayoutPymem()
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        manager.m_iszPlayerName = manager.pm.name_offset
        manager.m_hPlayerPawn = manager.pm.handle_offset
        manager.m_iTeamNum = manager.pm.team_offset
        manager.m_iHealth = manager.pm.health_offset
        manager.pm.entry_size = 136

        self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertFalse(manager._stride_detected)

    def test_ambiguous_stride_scores_are_not_confirmed(self):
        manager = MemoryManager()
        manager.pm = EntityLayoutPymem()
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        manager.m_hPlayerPawn = manager.pm.handle_offset
        manager.m_iTeamNum = manager.pm.team_offset
        manager.m_iHealth = manager.pm.health_offset

        def read_entity(index, entry_size):
            if entry_size not in (112, 120):
                return 0
            if index == manager.pm.controller_index:
                return manager.pm.controller
            if index == manager.pm.pawn_index:
                return manager.pm.pawn
            return 0

        with patch.object(manager, "_read_entity_raw", side_effect=read_entity):
            self.assertEqual(manager.detect_entity_entry_size(), 112)

        self.assertFalse(manager._stride_detected)

    def test_handle_parser_rejects_invalid_and_preserves_signed_serial_bits(self):
        signed_handle = 0x8000013D - 0x100000000

        self.assertEqual(MemoryManager.handle_to_index(signed_handle), 317)
        self.assertIsNone(MemoryManager.handle_to_index(0))
        self.assertIsNone(MemoryManager.handle_to_index(-1))

    def test_stride_detection_ignores_invalid_all_ones_handle(self):
        manager = MemoryManager()
        manager.pm = EntityLayoutPymem()
        manager.pm.handle_value = -1
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.ent_list = manager.pm.ent_list
        manager._ent_list_ts = time.monotonic()
        manager.m_hPlayerPawn = manager.pm.handle_offset
        manager.m_iTeamNum = manager.pm.team_offset
        manager.m_iHealth = manager.pm.health_offset

        self.assertEqual(manager.detect_entity_entry_size(), 112)
        self.assertFalse(manager._stride_detected)

    def test_entity_list_replacement_invalidates_and_redetects_stride(self):
        manager = MemoryManager()
        manager.pm = FakePymem()
        manager.client_base = 0x100000
        manager.dwEntityList = 0x200
        manager.ent_list = 0xABC
        manager._ent_list_ts = 0.0
        manager._stride_detected = True
        manager._entity_chunks[0] = 0x123

        with patch.object(manager, "read_longlong", return_value=0xDEF), patch.object(
            manager,
            "detect_entity_entry_size",
        ) as detect_mock:
            manager._ensure_ent_list()

        self.assertEqual(manager.ent_list, 0xDEF)
        self.assertFalse(manager._stride_detected)
        self.assertEqual(manager._entity_chunks, {})
        detect_mock.assert_called_once_with()

    def test_fire_logic_reads_player_and_target_teams_as_uint8(self):
        manager = MemoryManager()
        manager.pm = FakePymem()
        manager.client_base = 0x100000
        manager.dwLocalPlayerPawn = 0x200
        manager.m_iIDEntIndex = 0x10
        manager.m_iHealth = 0x20
        manager.m_iTeamNum = 0x30
        player = 0x400000
        target = 0x500000

        def read_longlong(address):
            if address == manager.client_base + manager.dwLocalPlayerPawn:
                return player
            return 0

        def read_int(address):
            if address == player + manager.m_iIDEntIndex:
                return 317
            if address == target + manager.m_iHealth:
                return 100
            return 0

        def read_uint8(address):
            return {
                player + manager.m_iTeamNum: 2,
                target + manager.m_iTeamNum: 3,
            }.get(address, 0)

        with patch.object(
            manager,
            "read_longlong",
            side_effect=read_longlong,
        ), patch.object(
            manager,
            "read_int",
            side_effect=read_int,
        ), patch.object(
            manager,
            "read_uint8",
            side_effect=read_uint8,
        ) as uint8_mock, patch.object(
            manager,
            "get_entity",
            return_value=target,
        ), patch.object(
            manager,
            "get_weapon_type",
            return_value="Rifles",
        ):
            fire_data = manager.get_fire_logic_data()

        self.assertEqual(fire_data["player_team"], 2)
        self.assertEqual(fire_data["entity_team"], 3)
        self.assertEqual(uint8_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
