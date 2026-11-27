import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from classes.config_manager import ConfigManager
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
            "offsets": directory / "off.json",
            "client": directory / "client_dll.json",
            "buttons": directory / "buttons.json",
        }
        payloads = self._payloads(entity_list)
        for path in paths.values():
            path.write_text(json.dumps(payloads["offsets.json" if path.name == "off.json" else path.name]), encoding="utf-8")
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

    def test_all_network_sources_download_into_memory_without_creating_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", str(Path(temp_dir) / "unused"),
        ):
            root = Path(temp_dir)
            for source, metadata in OFFSET_SOURCES.items():
                with self.subTest(source=source), patch(
                    "src.offsets.ConfigManager.load_config", return_value={"General": {"OffsetSource": source}},
                ), patch("src.offsets.requests.get", side_effect=self._remote_response) as get_mock:
                    manager = OffsetManager(config_path=str(root / "missing.json"))
                    with patch("pathlib.Path.open", side_effect=AssertionError("Unexpected file IO")):
                        self.assertTrue(manager.load_configured_offsets())
                self.assertEqual(manager._loaded_source, source)
                self.assertEqual(manager.get_offset("client.dll", "dwEntityList"), 100 if source == "ivtim" else 1)
                self.assertCountEqual(
                    [call.args[0] for call in get_mock.call_args_list],
                    [metadata[key] for key in ("offsets_url", "client_dll_url", "buttons_url")],
                )
                self.assertEqual(list(root.rglob("*")), [])

    def test_network_load_removes_old_managed_offsets_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            root = Path(temp_dir)
            directories = [root] + [root / source for source in OFFSET_SOURCES]
            for directory in directories:
                directory.mkdir(exist_ok=True)
                for filename in ("off.json", "offsets.json", "keep.json"):
                    (directory / filename).write_text("{}", encoding="utf-8")
            external = root / "user-selected"
            external.mkdir()
            (external / "off.json").write_text("user data", encoding="utf-8")
            manager = OffsetManager(config_path=str(root / "missing.json"))
            with patch("src.offsets.ConfigManager.load_config", return_value={"General": {"OffsetSource": "a2x"}}), patch(
                "src.offsets.requests.get", side_effect=self._remote_response,
            ):
                self.assertTrue(manager.load_configured_offsets())
            for directory in directories:
                self.assertFalse((directory / "off.json").exists())
                self.assertFalse((directory / "offsets.json").exists())
                self.assertTrue((directory / "keep.json").is_file())
            self.assertEqual((external / "off.json").read_text(), "user data")

    def test_loading_config_does_not_rename_or_create_offsets_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "Offsets"
            cache_dir.mkdir()
            legacy = cache_dir / "offsets.json"
            legacy.write_text("{}", encoding="utf-8")
            config_file = root / "config.json"
            config_file.write_text(json.dumps({"user_id": "keep", "General": {"OffsetsFile": str(legacy)}}))
            with patch.multiple(
                ConfigManager, CONFIG_DIRECTORY=str(root), OFFSETS_DIRECTORY=str(cache_dir),
                CONFIG_FILE=config_file, _config_cache=None,
            ), patch("classes.config_manager.Path.rename", side_effect=AssertionError("Unexpected rename")):
                loaded = ConfigManager.load_config()
            self.assertEqual(loaded["user_id"], "keep")
            self.assertEqual(loaded["General"]["OffsetsFile"], str(legacy))
            self.assertFalse((cache_dir / "off.json").exists())
            self.assertTrue(legacy.exists())

    def test_failed_old_cache_cleanup_stops_network_load(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))
            with patch("src.offsets.ConfigManager.load_config", return_value={"General": {"OffsetSource": "a2x"}}), patch(
                "pathlib.Path.unlink", side_effect=PermissionError("locked"),
            ), patch("src.offsets.requests.get") as get_mock:
                self.assertFalse(manager.load_configured_offsets())
            get_mock.assert_not_called()
            self.assertIsNone(manager._loaded_source)

    def test_default_local_paths_use_off_json(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            self.assertEqual(
                OffsetManager._configured_local_paths({})["offsets"],
                Path(temp_dir) / "off.json",
            )
        self.assertEqual(Path(ConfigManager.DEFAULT_CONFIG["General"]["OffsetsFile"]).name, "off.json")

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

    def test_force_refresh_failure_reuses_only_current_source_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ), patch("src.offsets.ConfigManager.load_config", return_value={"General": {"OffsetSource": "ivtim"}}):
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))
            with patch("src.offsets.requests.get", side_effect=self._remote_response):
                self.assertTrue(manager.load_configured_offsets())
            for failure in (Mock(ok=False, status_code=503), Mock(ok=True, json=Mock(return_value={}))):
                with self.subTest(failure=failure), patch("src.offsets.requests.get", return_value=failure):
                    self.assertTrue(manager.load_configured_offsets(force_reload=True))
                    self.assertEqual(manager.get_offset("client.dll", "dwEntityList"), 100)
            with patch("src.offsets.requests.get", side_effect=ConnectionError("offline")):
                self.assertTrue(manager.load_configured_offsets(force_reload=True))
            self.assertEqual(list(Path(temp_dir).rglob("*")), [])

    def test_fresh_manager_cannot_load_disk_cache_offline(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "src.offsets.ConfigManager.OFFSETS_DIRECTORY", temp_dir,
        ):
            self._write_payloads(Path(temp_dir))
            manager = OffsetManager(config_path=str(Path(temp_dir) / "missing.json"))
            with patch("src.offsets.ConfigManager.load_config", return_value={"General": {"OffsetSource": "a2x"}}), patch(
                "src.offsets.requests.get", side_effect=ConnectionError("offline"),
            ), patch("pathlib.Path.open", side_effect=AssertionError("Unexpected disk cache read")):
                self.assertFalse(manager.load_configured_offsets())
            self.assertEqual(manager.offsets, {})
            self.assertIsNone(manager._loaded_source)

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

    def test_invalid_memory_snapshot_clears_previous_data(self):
        manager = OffsetManager(source_name="ivtim", config_path="missing-sources.json")
        payloads = list(self._payloads().values())
        manager.offsets, manager.client, manager.buttons = payloads
        manager._loaded_source = "ivtim"
        manager._snapshots["ivtim"] = (payloads[0], payloads[1], {})
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
