import os
import requests
import psutil
import sys
import subprocess
import pygetwindow as gw
import orjson
import ctypes
from packaging import version
from dateutil.parser import parse as parse_date
from pathlib import Path

from classes.config_manager import ConfigManager
from classes.logger import Logger

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

class Utility:
    @staticmethod
    def load_offset_sources():
        """
        Loads available offset sources from the updated repository paths.
        Returns a dictionary with correct a2x raw structure URLs.
        """
        return {
            "a2x": {
                "name": "A2X Source",
                "author": "a2x",
                "repository": "a2x/cs2-dumper",
                "offsets_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/refs/heads/main/output/offsets.json",
                "client_dll_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/refs/heads/main/output/client_dll.json",
                "buttons_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/refs/heads/main/output/buttons.json"
            }
        }

    @staticmethod
    def fetch_offsets():
        """Fetches JSON data from remote URLs or local files based on configuration."""
        config = ConfigManager.load_config()
        source = config["General"].get("OffsetSource", "a2x")
        
        if source == "local":
            config_dir = Path(ConfigManager.CONFIG_DIRECTORY)
            offsets_file = config.get("General", {}).get("OffsetsFile", config_dir / "offsets.json")
            client_file = config.get("General", {}).get("ClientDLLFile", config_dir / "client_dll.json")
            buttons_file = config.get("General", {}).get("ButtonsFile", config_dir / "buttons.json")
            
            try:
                if not all(f.exists() for f in [Path(offsets_file), Path(client_file), Path(buttons_file)]):
                    config["General"]["OffsetSource"] = "a2x"
                    ConfigManager.save_config(config)
                    return Utility.fetch_offsets()
                
                return orjson.loads(Path(offsets_file).read_bytes()), orjson.loads(Path(client_file).read_bytes()), orjson.loads(Path(buttons_file).read_bytes())
            except Exception:
                config["General"]["OffsetSource"] = "a2x"
                ConfigManager.save_config(config)
                return Utility.fetch_offsets()
        
        try:
            # ИСПРАВЛЕНИЕ: Выкачиваем смещения по точным официальным raw-ссылкам a2x
            src_cfg = Utility.load_offset_sources()["a2x"]
            
            res_offset = requests.get(src_cfg["offsets_url"], timeout=10)
            res_client = requests.get(src_cfg["client_dll_url"], timeout=10)
            res_buttons = requests.get(src_cfg["buttons_url"], timeout=10)

            if res_offset.status_code == 200 and res_client.status_code == 200 and res_buttons.status_code == 200:
                return orjson.loads(res_offset.content), orjson.loads(res_client.content), orjson.loads(res_buttons.content)
        except Exception as e:
            logger.error(f"Request failed for offset server: {e}")
        return None, None, None
        
    @staticmethod
    def get_available_offset_sources():
        return [{"id": "a2x", "name": "A2X Source", "author": "a2x", "display": "A2X Source (a2x)"}]

    @staticmethod
    def resource_path(relative_path):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.abspath("."), relative_path)

    @staticmethod
    def is_game_active():
        windows = gw.getWindowsWithTitle('Counter-Strike 2')
        return any(window.isActive for window in windows)

    @staticmethod
    def is_game_running():
        return any(proc.info['name'] == 'cs2.exe' for proc in psutil.process_iter(attrs=['name']))
    @staticmethod
    def extract_offsets(offsets: dict, client_data: dict, buttons_data: dict) -> dict | None:
        """Load memory offsets for game functionality from structured dictionaries."""
        try:
            client = offsets.get("client.dll", {})
            buttons = buttons_data.get("client.dll", {})
            classes = client_data.get("client.dll", {}).get("classes", {})

            # ИСПРАВЛЕНИЕ: Оптимизированный безопасный рекурсивный сборщик Netvars
            def get_field(class_name, field_name):
                class_info = classes.get(class_name)
                if not class_info:
                    return 0
                field = class_info.get("fields", {}).get(field_name)
                if field is not None:
                    return field
                parent_class_name = class_info.get("parent")
                if parent_class_name:
                    return get_field(parent_class_name, field_name)
                return 0

            # Построение базы данных смещений строго по присланному дампу a2x
            extracted_offsets = {
                "dwEntityList": client.get("dwEntityList", 41003272),
                "dwLocalPlayerPawn": client.get("dwLocalPlayerPawn", 39212824),
                "dwLocalPlayerController": client.get("dwLocalPlayerController", 39046008),
                "dwViewMatrix": client.get("dwViewMatrix", 39235616),
                "dwForceJump": buttons.get("jump", 35865568),
                
                # Привязка Netvars к их точным классам из client_dll.json
                "m_iHealth": get_field("C_BaseEntity", "m_iHealth"),
                "m_iTeamNum": get_field("C_BaseEntity", "m_iTeamNum"),
                "m_pGameSceneNode": get_field("C_BaseEntity", "m_pGameSceneNode"),
                "m_vOldOrigin": get_field("C_BasePlayerPawn", "m_vOldOrigin"),
                "m_pWeaponServices": get_field("C_BasePlayerPawn", "m_pWeaponServices"),
                "m_iIDEntIndex": get_field("C_CSPlayerPawn", "m_iIDEntIndex"),
                "m_flFlashDuration": get_field("C_CSPlayerPawnBase", "m_flFlashDuration"),
                "m_iszPlayerName": get_field("CBasePlayerController", "m_iszPlayerName"),
                "m_hActiveWeapon": get_field("CPlayer_WeaponServices", "m_hActiveWeapon"),
                "m_bDormant": get_field("CGameSceneNode", "m_bDormant"),
                "m_AttributeManager": get_field("C_EconEntity", "m_AttributeManager"),
                "m_Item": get_field("C_AttributeContainer", "m_Item"),
                "m_iItemDefinitionIndex": get_field("C_EconItemView", "m_iItemDefinitionIndex"),
                "m_hPlayerPawn": get_field("CBasePlayerController", "m_hPawn"),
                "m_pBoneArray": get_field("CSkeletonInstance", "m_modelState") + 0x80
            }

            return extracted_offsets
        except Exception as e:
            logger.error(f"Unexpected error in offset extraction: {e}")
            return None
        
    @staticmethod
    def get_color_name_from_hex(hex_color: str) -> str:
        import classes.config_manager as cm
        color_choices_dict = getattr(cm, "COLOR_CHOICES", {})
        for name, hex_code in color_choices_dict.items():
            if hex_code == hex_color:
                return name
        return "Black"
    
    @staticmethod
    def transliterate(text: str) -> str:
        if not text: return "Player"
        mapping = {
            'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
            'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'Zh', 'ж': 'zh',
            'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'I', 'й': 'i', 'К': 'K', 'к': 'k',
            'Л': 'L', 'л': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
            'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't',
            'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'Kh', 'х': 'kh', 'Ц': 'Ts', 'ц': 'ts',
            'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Щ': 'Shch', 'щ': 'shch', 'Ы': 'Y', 'ы': 'y',
            'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya', 'ъ': '', 'ъ': '', 'ь': '', 'ь': ''
        }
        cleaned = "".join(mapping.get(char, char) for char in text)
        return "".join(c for c in cleaned if ord(c) < 128)

    @staticmethod
    def get_vk_code(key: str) -> int:
        key = key.lower()
        vk_codes = {
            "mouse1": 0x01, "mouse2": 0x02, "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06,
            "space": 0x20, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "tab": 0x09,
            "backspace": 0x08, "esc": 0x1B,
            "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46, "g": 0x47, "h": 0x48,
            "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50,
            "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
            "y": 0x59, "z": 0x5A,
            "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35, "6": 0x37, "7": 0x37, "8": 0x38, "9": 0x39,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78,
            "f10": 0x79, "f11": 0x7A, "f12": 0x7B
        }
        return vk_codes.get(key, 0x20)
