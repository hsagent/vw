import os
import requests
import psutil
import sys
import subprocess
import pygetwindow as gw
import orjson
from packaging import version
from dateutil.parser import parse as parse_date
from pathlib import Path

from classes.config_manager import ConfigManager, COLOR_CHOICES
from classes.logger import Logger

# Инициализация логгера
logger = Logger.get_logger(__name__)

OFFSET_SOURCES = {
    "a2x": {
        "name": "A2X Source", "author": "a2x", "repository": "a2x/cs2-dumper",
        "offsets_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json",
        "client_dll_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json",
        "buttons_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/buttons.json"
    }
}

# Кэш для транслитерации (ускоряет повторную обработку одинаковых никнеймов)
_transliteration_cache = {}
_transliteration_cache_max_size = 100

class Utility:
    @staticmethod
    def load_offset_sources():
        """Возвращает каталог источников оффсетов."""
        return OFFSET_SOURCES

    @staticmethod
    def fetch_offsets():
        """Загружает JSON-данные смещений с серверов или локальных файлов."""
        config = ConfigManager.load_config()
        source = config["General"].get("OffsetSource", "a2x")
        
        if source == "local":
            config_dir = Path(ConfigManager.CONFIG_DIRECTORY)
            try:
                offset = orjson.loads(Path(config.get("General", {}).get("OffsetsFile", config_dir / "offsets.json")).read_bytes())
                client = orjson.loads(Path(config.get("General", {}).get("ClientDLLFile", config_dir / "client_dll.json")).read_bytes())
                buttons = orjson.loads(Path(config.get("General", {}).get("ButtonsFile", config_dir / "buttons.json")).read_bytes())
                return offset, client, buttons
            except Exception:
                config["General"]["OffsetSource"] = "a2x"
                ConfigManager.save_config(config)
                return Utility.fetch_offsets()
        
        try:
            available_sources = Utility.load_offset_sources()
            source_config = available_sources.get(source, OFFSET_SOURCES["a2x"])

            r_off = requests.get(source_config["offsets_url"], timeout=10, verify=True)
            r_cli = requests.get(source_config["client_dll_url"], timeout=10, verify=True)
            r_but = requests.get(source_config["buttons_url"], timeout=10, verify=True)

            if r_off.status_code == 200 and r_cli.status_code == 200 and r_but.status_code == 200:
                return orjson.loads(r_off.content), orjson.loads(r_cli.content), orjson.loads(r_but.content)
        except Exception:
            pass
        return None, None, None
        
    @staticmethod
    def get_available_offset_sources():
        """Возвращает список доступных источников для выпадающего списка GUI."""
        sources = Utility.load_offset_sources()
        source_list = []
        for s_id, cfg in sources.items():
            source_list.append({"id": s_id, "name": cfg["name"], "author": cfg["author"], "display": f"{cfg['name']} ({cfg['author']})"})
        source_list.append({"id": "local", "name": "Local Files", "author": "User", "display": "Local Files"})
        return source_list

    @staticmethod
    def check_for_updates(current_version):
        """Проверяет обновления на GitHub."""
        try:
            response = requests.get("https://api.github.com/repos/hsagent/vw/releases/latest", timeout=10, verify=True)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("tag_name", "")
                return latest_version, latest_version != current_version
            return None, False
        except Exception as e:
            logger.debug(f"Ошибка проверки обновлений: {e}")
            return None, False
    @staticmethod
    def resource_path(relative_path):
        """Возвращает путь к ресурсу, поддерживая нормальный запуск и сборку в .exe."""
        try:
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, relative_path)
            return os.path.join(os.path.abspath("."), relative_path)
        except Exception as e:
            logger.error(f"Не удалось получить путь к ресурсу: {e}")
            return None

    @staticmethod
    def is_game_active():
        """Проверяет, активно ли окно игры в данный момент на экране."""
        windows = gw.getWindowsWithTitle('Counter-Strike 2')
        return any(window.isActive for window in windows)

    @staticmethod
    def is_game_running():
        """Проверяет, запущен ли процесс игры cs2.exe в диспетчере задач."""
        return any(proc.info['name'] == 'cs2.exe' for proc in psutil.process_iter(attrs=['name']))
    
    @staticmethod
    def get_color_name_from_hex(hex_color: str) -> str:
        """Получает название цвета из его HEX кода."""
        for name, hex_code in COLOR_CHOICES.items():
            if hex_code == hex_color:
                return name
        return "Black"
    
    @staticmethod
    def transliterate(text: str) -> str:
        """Переводит кириллические символы никнеймов в латиницу для ImGui/pyMeow."""
        # Проверяем кэш
        if text in _transliteration_cache:
            return _transliteration_cache[text]

        mapping = {
            'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
            'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'Zh', 'ж': 'zh',
            'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'I', 'й': 'i', 'К': 'K', 'к': 'k',
            'Л': 'L', 'л': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
            'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't',
            'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'Kh', 'х': 'kh', 'Ц': 'Ts', 'ц': 'ts',
            'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Щ': 'Shch', 'щ': 'shch', 'Ы': 'Y', 'ы': 'y',
            'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya', 'Ъ': '', 'ъ': '', 'Ь': '', 'ь': ''
        }
        result = "".join(mapping.get(char, char) for char in text)

        # Сохраняем в кэш с ограничением размера
        if len(_transliteration_cache) < _transliteration_cache_max_size:
            _transliteration_cache[text] = result
        elif len(_transliteration_cache) >= _transliteration_cache_max_size:
            # Очищаем кэш если он переполнен
            _transliteration_cache.clear()
            _transliteration_cache[text] = result

        return result

    @staticmethod
    def get_vk_code(key: str) -> int:
        """Конвертирует строковое название клавиши в её виртуальный код Windows (VK_CODE)."""
        key = key.lower()
        vk_codes = {
            "mouse1": 0x01, "mouse2": 0x02, "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06,
            "space": 0x20, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "tab": 0x09,
            "backspace": 0x08, "esc": 0x1B,
            "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46, "g": 0x47, "h": 0x48,
            "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50,
            "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
            "y": 0x59, "z": 0x5A,
            "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35, "6": 0x36, "7": 0x37,
            "8": 0x38, "9": 0x39,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75, "f7": 0x76,
            "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B
        }
        return vk_codes.get(key, 0x20)
