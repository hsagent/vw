import os
import requests
import psutil
import sys
import ctypes
import pygetwindow as gw
import orjson
from typing import Dict, Any, Optional
from pathlib import Path

from classes.config_manager import ConfigManager
from classes.classes.logger import Logger

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

class Utility:
    @staticmethod
    def load_offset_sources() -> dict:
        """Loads available offset sources from the remote repository or returns defaults."""
        try:
            response = requests.get('https://raw.githubusercontent.com/hsagent/vw/refs/heads/main/src/offsets.json', timeout=5)
            if response.status_code == 200:
                return orjson.loads(response.content)
        except Exception:
            pass
            
        # Возвращаем проверенные эталонные структуры
        return {
            "a2x": {
                "name": "a2x Source",
                "author": "a2x",
                "repository": "a2x/cs2-dumper",
                "offsets_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json",
                "client_dll_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json",
                "buttons_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/buttons.json"
            }
        }

    @staticmethod
    def fetch_offsets() -> tuple:
        """Fetches JSON data from remote URLs or local files based on configuration."""
        config = ConfigManager.load_config()
        source = config["General"].get("OffsetSource", "a2x")
        
        # Обработка локального режима загрузки офсетов
        if source == "local":
            config_dir = Path(ConfigManager.CONFIG_DIRECTORY)
            offsets_file = config["General"].get("OffsetsFile", str(config_dir / "offsets.json"))
            client_file = config["General"].get("ClientDLLFile", str(config_dir / "client_dll.json"))
            buttons_file = config["General"].get("ButtonsFile", str(config_dir / "buttons.json"))
            try:
                offset = orjson.loads(Path(offsets_file).read_bytes())
                client = orjson.loads(Path(client_file).read_bytes())
                buttons = orjson.loads(buttons_file.read_bytes() if hasattr(buttons_file, "read_bytes") else Path(buttons_file).read_bytes())
                return offset, client, buttons
            except Exception as e:
                logger.error(f"Локальные файлы офсетов повреждены ({e}). Откат на сервер a2x.")
                source = "a2x"

        # Серверный режим загрузки (динамический парсинг дампера)
        try:
            sources = Utility.load_offset_sources()
            src_cfg = sources.get(source, sources["a2x"])
            
            res_off = requests.get(src_cfg["offsets_url"], timeout=10)
            res_cli = requests.get(src_cfg["client_dll_url"], timeout=10)
            res_btn = requests.get(src_cfg["buttons_url"], timeout=10)
            
            if res_off.status_code == 200 and res_cli.status_code == 200 and res_btn.status_code == 200:
                return orjson.loads(res_off.content), orjson.loads(res_cli.content), orjson.loads(res_btn.content)
        except Exception as e:
            logger.error(f"Не удалось скачать свежие смещения с сервера: {e}")
            
        return None, None, None

    @staticmethod
    def extract_offsets(offsets_data: dict, client_data: dict, buttons_data: dict) -> Optional[dict]:
        """
        Парсит новую древовидную иерархию JSON-дампа от a2x.
        Привязывает смещения к переменным MemoryManager.
        """
        try:
            extracted = {}
            
            # 1. Извлекаем глобальные адреса из offsets.json
            cli_off = offsets_data.get("client.dll", {})
            extracted["dwEntityList"] = cli_off.get("dwEntityList")
            extracted["dwLocalPlayerPawn"] = cli_off.get("dwLocalPlayerPawn")
            extracted["dwLocalPlayerController"] = cli_off.get("dwLocalPlayerController")
            extracted["dwViewMatrix"] = cli_off.get("dwViewMatrix")
            
            # 2. Извлекаем инпуты клавиш прыжка из buttons.json
            extracted["dwForceJump"] = buttons_data.get("client.dll", {}).get("jump")

            # Вспомогательная функция глубокого поиска по классам client_dll.json
            def get_var(class_name: str, field_name: str) -> Optional[int]:
                return (client_data.get("client.dll", {})
                                   .get("classes", {})
                                   .get(class_name, {})
                                   .get("fields", {})
                                   .get(field_name))

            # 3. Привязка сетевых переменных (Netvars) к их точным классам Source 2
            extracted["m_iHealth"] = get_var("C_BaseEntity", "m_iHealth")
            extracted["m_iTeamNum"] = get_var("C_BaseEntity", "m_iTeamNum")
            extracted["m_pGameSceneNode"] = get_var("C_BaseEntity", "m_pGameSceneNode")
            
            extracted["m_iIDEntIndex"] = get_var("C_CSPlayerPawn", "m_iIDEntIndex")
            extracted["m_flFlashDuration"] = get_var("C_CSPlayerPawnBase", "m_flFlashDuration")
            
            extracted["m_iszPlayerName"] = get_var("CBasePlayerController", "m_iszPlayerName")
            extracted["m_hPlayerPawn"] = get_var("CBasePlayerController", "m_hPawn") # Исправлено: строго m_hPawn
            
            extracted["m_vOldOrigin"] = get_var("C_BasePlayerPawn", "m_vOldOrigin")
            extracted["m_pWeaponServices"] = get_var("C_BasePlayerPawn", "m_pWeaponServices")
            
            extracted["m_bDormant"] = get_var("CGameSceneNode", "m_bDormant")
            
            # Вычисление BoneArray на основе смещения modelState
            model_state = get_var("CSkeletonInstance", "m_modelState")
            extracted["m_pBoneArray"] = model_state + 0x80 if model_state is not None else None
            
            extracted["m_hActiveWeapon"] = get_var("CPlayer_WeaponServices", "m_hActiveWeapon")
            extracted["m_AttributeManager"] = get_var("C_EconEntity", "m_AttributeManager")
            extracted["m_Item"] = get_var("C_AttributeContainer", "m_Item")
            extracted["m_iItemDefinitionIndex"] = get_var("C_EconItemView", "m_iItemDefinitionIndex")

            # Валидация структуры
            if extracted["dwEntityList"] is None:
                return None

            return extracted
        except Exception as e:
            logger.error(f"Критическая ошибка разбора структуры дампа в extract_offsets: {e}")
            return None

    # ==========================================
    # СИСТЕМНЫЕ МЕТОДЫ ВАЛИДАЦИИ И АКТИВНОСТИ ОКНА CS2
    # ==========================================
    @staticmethod
    def is_game_running() -> bool:
        """Проверяет, запущен ли процесс cs2.exe в диспетчере задач Windows."""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == "cs2.exe":
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    @staticmethod
    def is_game_active() -> bool:
        """Проверяет, находится ли окно Counter-Strike 2 в фокусе (активно)."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value == "Counter-Strike 2"
        except Exception:
            return False

    @staticmethod
    def get_vk_code(key_str: str) -> int:
        """Возвращает виртуальный код клавиши (Virtual Key Code) для WinAPI."""
        key_map = {
            "space": 0x20, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
            "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06
        }
        if key_str in key_map:
            return key_map[key_str]
        if len(key_str) == 1:
            return ctypes.windll.user32.VkKeyScanW(ord(key_str)) & 0xFF
        return 0x20 # По умолчанию возвращаем пробел

    @staticmethod
    def transliterate(text: str) -> str:
        """Безопасно очищает кириллицу из никнеймов игроков для защиты pyMeow от крашей."""
        if not text:
            return "Player"
        # Простая и производительная карта транслита
        cyrillic = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        latin = "abvgdeezzhijklmnoprstufhcchshsh''y'euyABVGD側にEZZHIJKLMNOPRSTUFHCCHSHSH''Y'EUY"
        tr_map = str.maketrans({c: l for c, l in zip(cyrillic, latin)})
        
        cleaned = text.translate(tr_map)
        # Оставляем только базовые ASCII-символы для стабильности рендера C++ оверлея
        return "".join(c for c in cleaned if ord(c) < 128)
