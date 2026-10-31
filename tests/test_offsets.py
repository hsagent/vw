import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.offsets import OffsetManager


class LocalOffsetTests(unittest.TestCase):
    def _write_payloads(self, directory):
        paths = {
            "offsets": directory / "offsets.json",
            "client": directory / "client_dll.json",
            "buttons": directory / "buttons.json",
        }
        paths["offsets"].write_text(
            json.dumps(
                {
                    "client.dll": {
                        "dwEntityList": 1,
                        "dwLocalPlayerPawn": 2,
                        "dwLocalPlayerController": 3,
                        "dwViewMatrix": 4,
                    }
                }
            ),
            encoding="utf-8",
        )
        paths["client"].write_text(
            json.dumps(
                {
                    "client.dll": {
                        "classes": {
                            "C_BaseEntity": {"fields": {"m_iHealth": 844}}
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        paths["buttons"].write_text(
            json.dumps({"client.dll": {"jump": 5}}),
            encoding="utf-8",
        )
        return paths

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


if __name__ == "__main__":
    unittest.main()
