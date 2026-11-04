import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.offsets import OFFSET_SOURCES, OffsetManager


class LocalOffsetTests(unittest.TestCase):
    @staticmethod
    def _payloads(entity_list=1):
        return {
            "offsets.json": {
                "client.dll": {
                    "dwEntityList": entity_list,
                    "dwLocalPlayerPawn": 2,
                    "dwLocalPlayerController": 3,
                    "dwViewMatrix": 4,
                }
            },
            "client_dll.json": {
                "client.dll": {
                    "classes": {"C_BaseEntity": {"fields": {"m_iHealth": 844}}}
                }
            },
            "buttons.json": {"client.dll": {"jump": 5}},
        }

    def _write_payloads(self, directory, entity_list=1):
        paths = {
            "offsets": directory / "offsets.json",
            "client": directory / "client_dll.json",
            "buttons": directory / "buttons.json",
        }
        payloads = self._payloads(entity_list)
        for path in paths.values():
            path.write_text(json.dumps(payloads[path.name]), encoding="utf-8")
        return paths

    def _remote_response(self, url, **kwargs):
        entity_list = 100 if "/ivtim/" in url else 1
        payload = self._payloads(entity_list)[url.rsplit("/", 1)[-1]]
        return Mock(ok=True, json=Mock(return_value=payload))

    @staticmethod
    def _config(paths):
        return {
            "General": {
                "OffsetSource": "local",
                "OffsetsFile": str(paths["offsets"]),
                "ClientDLLFile": str(paths["client"]),
                "ButtonsFile": str(paths["buttons"]),
            }
        }

    def test_valid_local_offsets_are_loaded_from_configured_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_payloads(Path(temp_dir))
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))

            with patch(
                "src.offsets.ConfigManager.load_config",
                return_value=self._config(paths),
            ):
                self.assertTrue(manager.load_configured_offsets())

            self.assertEqual(manager._loaded_source, "local")
            self.assertEqual(
                manager.get_offset("client.dll", "dwEntityList"),
                1,
            )
            self.assertEqual(manager.get_button("jump"), 5)

    def test_invalid_local_offsets_clear_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_payloads(Path(temp_dir))
            paths["buttons"].write_text(
                json.dumps({"client.dll": {"jump": 0}}),
                encoding="utf-8",
            )
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))
            manager.offsets = {"stale": True}
            manager.client = {"stale": True}
            manager.buttons = {"stale": True}

            with patch(
                "src.offsets.ConfigManager.load_config",
                return_value=self._config(paths),
            ):
                self.assertFalse(manager.load_configured_offsets())

            self.assertEqual(manager.offsets, {})
            self.assertEqual(manager.client, {})
            self.assertEqual(manager.buttons, {})
            self.assertIsNone(manager._loaded_source)

    def test_all_network_sources_use_selected_urls_and_separate_caches(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            for source, metadata in OFFSET_SOURCES.items():
                with self.subTest(source=source), patch(
                    "src.offsets.ConfigManager.load_config",
                    return_value={"General": {"OffsetSource": source}},
                ), patch(
                    "src.offsets.requests.get", side_effect=self._remote_response,
                ) as get_mock:
                    manager = OffsetManager(config_path=str(root / "missing.json"))
                    self.assertTrue(manager.load_configured_offsets())

                self.assertEqual(manager.source_name, source)
                self.assertEqual(manager._loaded_source, source)
                self.assertCountEqual(
                    [call.args[0] for call in get_mock.call_args_list],
                    [metadata[key] for key in ("offsets_url", "client_dll_url", "buttons_url")],
                )
                cache_dir = root if source == "a2x" else root / source
                for filename in self._payloads():
                    self.assertTrue((cache_dir / filename).is_file())

    def test_switching_repository_reloads_data_and_keeps_a2x_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            config = {"General": {"OffsetSource": "a2x"}}
            manager = OffsetManager(config_path=str(root / "missing.json"))
            with patch("src.offsets.ConfigManager.load_config", return_value=config), patch(
                "src.offsets.requests.get", side_effect=self._remote_response,
            ) as get_mock:
                self.assertTrue(manager.load_configured_offsets())
                config["General"]["OffsetSource"] = "ivtim"
                self.assertTrue(manager.load_configured_offsets())

            self.assertEqual(get_mock.call_count, 6)
            self.assertEqual(manager.get_offset("client.dll", "dwEntityList"), 100)
            self.assertEqual(manager._loaded_source, "ivtim")
            config["General"]["OffsetSource"] = "a2x"
            with patch("src.offsets.ConfigManager.load_config", return_value=config), patch(
                "src.offsets.requests.get", return_value=Mock(ok=False, status_code=503),
            ):
                self.assertTrue(manager.load_configured_offsets())
            self.assertEqual(manager.get_offset("client.dll", "dwEntityList"), 1)
            self.assertEqual(manager._loaded_source, "a2x")

    def test_failed_new_source_does_not_reuse_a2x_cache_or_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            self._write_payloads(root)
            manager = OffsetManager(config_path=str(root / "missing.json"))
            manager.offsets, manager.client, manager.buttons = self._payloads().values()
            manager._loaded_source = "a2x"
            with patch(
                "src.offsets.ConfigManager.load_config",
                return_value={"General": {"OffsetSource": "ivtim"}},
            ), patch(
                "src.offsets.requests.get", return_value=Mock(ok=False, status_code=503),
            ):
                self.assertFalse(manager.load_configured_offsets())

            self.assertEqual(manager.offsets, {})
            self.assertEqual(manager.client, {})
            self.assertEqual(manager.buttons, {})
            self.assertIsNone(manager._loaded_source)

    def test_offline_source_uses_only_its_own_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            cache_dir = root / "hanstxx"
            cache_dir.mkdir()
            self._write_payloads(cache_dir, entity_list=200)
            manager = OffsetManager(config_path=str(root / "missing.json"))
            with patch(
                "src.offsets.ConfigManager.load_config",
                return_value={"General": {"OffsetSource": "hanstxx"}},
            ), patch(
                "src.offsets.requests.get", return_value=Mock(ok=False, status_code=503),
            ):
                self.assertTrue(manager.load_configured_offsets())

            self.assertEqual(manager.get_offset("client.dll", "dwEntityList"), 200)
            self.assertEqual(manager._loaded_source, "hanstxx")

    def test_unknown_source_clears_snapshot_without_download(self):
        manager = OffsetManager(config_path="missing-sources.json")
        manager.offsets, manager.client, manager.buttons = self._payloads().values()
        manager._loaded_source = "a2x"
        with patch(
            "src.offsets.ConfigManager.load_config",
            return_value={"General": {"OffsetSource": "../../unknown"}},
        ), patch("src.offsets.requests.get") as get_mock:
            self.assertFalse(manager.load_configured_offsets())
        get_mock.assert_not_called()
        self.assertEqual(manager.offsets, {})
        self.assertEqual(manager.client, {})
        self.assertEqual(manager.buttons, {})
        self.assertIsNone(manager._loaded_source)

    def test_memory_cache_and_force_reload_keep_selected_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ), patch(
            "src.offsets.ConfigManager.load_config",
            return_value={"General": {"OffsetSource": "ivtim"}},
        ), patch(
            "src.offsets.requests.get", side_effect=self._remote_response,
        ) as get_mock:
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))
            self.assertTrue(manager.load_configured_offsets())
            self.assertTrue(manager.load_configured_offsets())
            self.assertEqual(get_mock.call_count, 3)
            self.assertTrue(manager.load_configured_offsets(force_reload=True))
            self.assertEqual(get_mock.call_count, 6)
            self.assertTrue(all("/ivtim/" in call.args[0] for call in get_mock.call_args_list))

    def test_sources_json_override_is_applied_after_repository_switch(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            custom_urls = {
                "offsets_url": "https://example.invalid/custom/offsets.json",
                "client_dll_url": "https://example.invalid/custom/client_dll.json",
                "buttons_url": "https://example.invalid/custom/buttons.json",
            }
            config_path = root / "sources.json"
            config_path.write_text(json.dumps({"ivtim": custom_urls}), encoding="utf-8")
            manager = OffsetManager(config_path=str(config_path))
            with patch(
                "src.offsets.ConfigManager.load_config",
                return_value={"General": {"OffsetSource": "ivtim"}},
            ), patch(
                "src.offsets.requests.get", side_effect=self._remote_response,
            ) as get_mock:
                self.assertTrue(manager.load_configured_offsets())
            self.assertCountEqual(
                [call.args[0] for call in get_mock.call_args_list], list(custom_urls.values()),
            )

    def test_invalid_repository_cache_clears_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            cache_dir = root / "ivtim"
            cache_dir.mkdir()
            paths = self._write_payloads(cache_dir)
            paths["buttons"].write_text("{broken", encoding="utf-8")
            manager = OffsetManager(source_name="ivtim", config_path=str(root / "missing.json"))
            manager.offsets, manager.client, manager.buttons = self._payloads().values()
            manager._loaded_source = "ivtim"
            self.assertFalse(manager.load_cached_offsets())
            self.assertEqual(manager.offsets, {})
            self.assertEqual(manager.client, {})
            self.assertEqual(manager.buttons, {})
            self.assertIsNone(manager._loaded_source)

    def test_utility_and_gui_choices_share_loader_catalog(self):
        from classes.utility import Utility

        self.assertIs(Utility.load_offset_sources(), OFFSET_SOURCES)
        self.assertEqual(
            {source["id"] for source in Utility.get_available_offset_sources()},
            set(OFFSET_SOURCES) | {"local"},
        )
        self.assertEqual(OFFSET_SOURCES["hanstxx"]["branch"], "master")
        for key in ("offsets_url", "client_dll_url", "buttons_url"):
            self.assertIn("/build-14195/raw/", OFFSET_SOURCES["cesiumoq"][key])

    def test_update_timestamp_uses_selected_branch_file_and_separate_cache(self):
        from gui import home_tab

        for source in ("hanstxx", "cesiumoq"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temp_dir:
                root_dir = Path(temp_dir)
                a2x_cache = root_dir / "last_update_cache.txt"
                a2x_cache.write_text("old a2x timestamp", encoding="utf-8")
                root = Mock()
                root.winfo_exists.return_value = True
                root.after.side_effect = lambda delay, callback: callback()
                window = SimpleNamespace(root=root, update_value_label=Mock())
                response = Mock(content=json.dumps([
                    {"commit": {"committer": {"date": "2026-11-03T23:09:32Z"}}}
                ]).encode("utf-8"))

                with patch(
                    "gui.home_tab.ConfigManager.CONFIG_DIRECTORY", temp_dir,
                ), patch(
                    "gui.home_tab.ConfigManager.load_config",
                    return_value={"General": {"OffsetSource": source}},
                ), patch(
                    "gui.home_tab.requests.get", return_value=response,
                ) as get_mock, patch(
                    "gui.home_tab.threading.Thread",
                    side_effect=lambda target, daemon: SimpleNamespace(start=target),
                ):
                    home_tab.fetch_last_update(window)

                metadata = OFFSET_SOURCES[source]
                self.assertEqual(
                    get_mock.call_args.args[0],
                    f"https://api.github.com/repos/{metadata['repository']}/commits",
                )
                self.assertEqual(get_mock.call_args.kwargs["params"], {
                    "sha": metadata["branch"],
                    "path": metadata["offsets_path"],
                    "per_page": 1,
                })
                window.update_value_label.configure.assert_called_once_with(
                    text="11/03/2026 23:09", text_color="#22c55e",
                )
                self.assertEqual(a2x_cache.read_text(encoding="utf-8"), "old a2x timestamp")
                self.assertTrue((root_dir / f"last_update_cache_{source}.txt").is_file())

    def test_rejected_local_selection_restores_saved_repository_display(self):
        from gui import general_settings_tab

        mapping = {
            f"{metadata['name']} ({metadata['author']})": source
            for source, metadata in OFFSET_SOURCES.items()
        }
        for source in OFFSET_SOURCES:
            with self.subTest(source=source):
                window = SimpleNamespace(
                    offset_source_mapping=mapping,
                    offset_source_var=Mock(),
                )
                with patch(
                    "gui.general_settings_tab.ConfigManager.load_config",
                    return_value={"General": {"OffsetSource": source}},
                ), patch(
                    "gui.general_settings_tab.ConfigManager.set_value",
                ) as set_mock, patch(
                    "gui.general_settings_tab.messagebox.showerror",
                ) as error_mock, patch.object(
                    general_settings_tab.updater, "invalidate",
                ) as invalidate_mock:
                    general_settings_tab.update_offset_source(window, "local")

                expected_display = next(name for name, key in mapping.items() if key == source)
                window.offset_source_var.set.assert_called_once_with(expected_display)
                error_mock.assert_called_once()
                set_mock.assert_not_called()
                invalidate_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
