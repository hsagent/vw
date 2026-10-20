import os
import orjson
import copy
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import threading

from classes.logger import Logger

# Инициализация логгера
logger = Logger.get_logger(__name__)

class ConfigManager:
    """
    Потокобезопасный менеджер конфигурации приложения.
    Предоставляет кэширование, миграцию ключей и защиту от сбоев.
    """
    
    VERSION = "v1.2.9.4"
    
    # ЖЕСТКАЯ ПРИВЯЗКА К СИСТЕМНОЙ ПАПКЕ В APPDATA
    CONFIG_DIRECTORY = os.path.expanduser(r'~\AppData\Local\My Project')
    OFFSETS_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "Offsets")
    UPDATE_DIRECTORY = os.path.join(CONFIG_DIRECTORY, "Update")
    CONFIG_FILE = Path(CONFIG_DIRECTORY) / 'config.json'

    
    # Обновленный DEFAULT_CONFIG под наши новые фиксы CS2
    DEFAULT_CONFIG = {
        "user_id": None,
        "General": {
            "Trigger": False,
            "Overlay": False,
            "Bunnyhop": False,
            "Noflash": False,
            "OffsetSource": "a2x",
            "OffsetsFile": str(Path(OFFSETS_DIRECTORY) / "offsets.json"),
            "ClientDLLFile": str(Path(OFFSETS_DIRECTORY) / "client_dll.json"),
            "ButtonsFile": str(Path(OFFSETS_DIRECTORY) / "buttons.json")
        },
        "Trigger": {
            "TriggerKey": "x",
            "ToggleMode": False,
            "AttackOnTeammates": False,
            "active_weapon_type": "Rifles",
            "WeaponSettings": {
                "Pistols": {"ShotDelayMin": 0.015, "ShotDelayMax": 0.03, "PostShotDelay": 0.05},
                "Rifles": {"ShotDelayMin": 0.01, "ShotDelayMax": 0.025, "PostShotDelay": 0.05},
                "Snipers": {"ShotDelayMin": 0.03, "ShotDelayMax": 0.06, "PostShotDelay": 0.4},
                "SMGs": {"ShotDelayMin": 0.01, "ShotDelayMax": 0.02, "PostShotDelay": 0.05},
                "Heavy": {"ShotDelayMin": 0.02, "ShotDelayMax": 0.04, "PostShotDelay": 0.15}
            }
        },
        "Overlay": {
            "target_fps": 60,
            "enable_box": True,
            "enable_skeleton": True, # Включаем скелетоны по умолчанию
            "draw_snaplines": False,
            "snaplines_color_hex": "#FFFFFF",
            "box_line_thickness": 1.2,
            "box_color_hex": "#FFA500",
            "text_color_hex": "#FFFFFF",
            "draw_health_numbers": True,
            "use_transliteration": False,
            "draw_nicknames": True,
            "draw_teammates": False,
            "teammate_color_hex": "#00FFFF"
        },
        "Bunnyhop": {
            "JumpKey": "space",
            "JumpDelay": 0.01
        },
        "NoFlash": {
            "FlashSuppressionStrength": 0.0
        },
        "GitHub": {
            "AccessToken": None
        }
    }
    
    _config_cache: Optional[Dict[str, Any]] = None
    _lock: threading.Lock = threading.Lock()
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """Загружает конфигурацию из файла (Thread-safe и Double-check паттерн)."""
        with cls._lock:
            if cls._config_cache is not None:
                return copy.deepcopy(cls._config_cache)

            cls._ensure_directories()

            if not cls.CONFIG_FILE.exists():
                cls._create_default_config()
            else:
                cls._load_existing_config()

            return copy.deepcopy(cls._config_cache)

    @classmethod
    def reload_config(cls) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Reload configuration from disk and return previous/current snapshots."""
        with cls._lock:
            previous = copy.deepcopy(cls._config_cache) if cls._config_cache is not None else {}
            cls._config_cache = None
            cls._ensure_directories()
            if cls.CONFIG_FILE.exists():
                cls._load_existing_config()
            else:
                cls._create_default_config()
            return previous, copy.deepcopy(cls._config_cache)
    
    @classmethod
    def _ensure_directories(cls) -> None:
        try:
            Path(cls.CONFIG_DIRECTORY).mkdir(parents=True, exist_ok=True)
            Path(cls.OFFSETS_DIRECTORY).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Не удалось создать директории: {e}")
    @classmethod
    def _create_default_config(cls) -> None:
        logger.info(f"Конфигурация создана по умолчанию: {cls.CONFIG_FILE}")
        default_copy = copy.deepcopy(cls.DEFAULT_CONFIG)
        cls._config_cache = default_copy
        cls._save_to_file(default_copy, log_info=False)
    
    @classmethod
    def _load_existing_config(cls) -> None:
        try:
            file_bytes = cls.CONFIG_FILE.read_bytes()
            loaded_config = orjson.loads(file_bytes)
            
            if not isinstance(loaded_config, dict):
                raise ValueError("Неверная структура JSON")
            
            cls._config_cache = loaded_config
            
            # Миграция отсутствующих ключей
            if cls._update_config(cls.DEFAULT_CONFIG, cls._config_cache):
                logger.info("Конфигурация дополнена недостающими ключами.")
                cls._save_to_file(cls._config_cache, log_info=False)
                
        except Exception as e:
            logger.error(f"Сбой загрузки файла конфигурации: {e}. Сброс на дефолт.")
            default_copy = copy.deepcopy(cls.DEFAULT_CONFIG)
            cls._config_cache = default_copy
            cls._save_to_file(default_copy, log_info=False)
    
    @classmethod
    def _update_config(cls, default: Dict[str, Any], current: Dict[str, Any]) -> bool:
        updated = False
        for key, value in default.items():
            if key not in current:
                current[key] = copy.deepcopy(value)
                updated = True
            elif isinstance(value, dict) and isinstance(current.get(key), dict):
                if cls._update_config(value, current[key]):
                    updated = True
        return updated
    
    @classmethod
    def save_config(cls, config: Dict[str, Any], log_info: bool = True) -> bool:
        with cls._lock:
            cls._config_cache = copy.deepcopy(config)
            return cls._save_to_file(config, log_info)
    
    @classmethod
    def _save_to_file(cls, config: Dict[str, Any], log_info: bool = True) -> bool:
        try:
            Path(cls.CONFIG_DIRECTORY).mkdir(parents=True, exist_ok=True)
            config_bytes = orjson.dumps(config, option=orjson.OPT_INDENT_2)
            # Атомарная запись: вотчер конфига не должен прочитать недописанный
            # JSON и сбросить настройки на дефолтные.
            tmp_file = cls.CONFIG_FILE.with_name(cls.CONFIG_FILE.name + ".tmp")
            tmp_file.write_bytes(config_bytes)
            os.replace(tmp_file, cls.CONFIG_FILE)
            if log_info:
                logger.info(f"Конфигурация успешно сохранена в {cls.CONFIG_FILE}.")
            return True
        except Exception as e:
            logger.error(f"Не удалось записать конфиг на диск: {e}")
            return False
    
    @classmethod
    def reset_to_default(cls) -> Dict[str, Any]:
        with cls._lock:
            default_copy = copy.deepcopy(cls.DEFAULT_CONFIG)
            cls._config_cache = default_copy
            cls._save_to_file(default_copy, log_info=True)
            return copy.deepcopy(default_copy)
    
    @classmethod
    def get_value(cls, *keys: str, default: Any = None) -> Any:
        config = cls.load_config()
        current = config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    
    @classmethod
    def set_value(cls, *keys: str, value: Any) -> bool:
        if not keys: return False
        with cls._lock:
            config = copy.deepcopy(cls._config_cache) if cls._config_cache is not None else None
            if config is None:
                cls._ensure_directories()
                if cls.CONFIG_FILE.exists():
                    try:
                        config = orjson.loads(cls.CONFIG_FILE.read_bytes())
                    except (OSError, orjson.JSONDecodeError):
                        config = copy.deepcopy(cls.DEFAULT_CONFIG)
                else:
                    config = copy.deepcopy(cls.DEFAULT_CONFIG)
            current = config
            for key in keys[:-1]:
                child = current.get(key)
                if not isinstance(child, dict):
                    child = {}
                    current[key] = child
                current = child
            current[keys[-1]] = value
            cls._config_cache = copy.deepcopy(config)
            return cls._save_to_file(config, log_info=False)

# Цветовая палитра HEX для GUI
COLOR_CHOICES = {
    "Orange": "#FFA500", "Red": "#FF0000", "Green": "#00FF00",
    "Blue": "#0000FF", "White": "#FFFFFF", "Black": "#000000",
    "Cyan": "#00FFFF", "Yellow": "#FFFF00"
}

class Colors:
    """
    Класс ленивой инициализации цветов pyMeow.
    Защищает приложение от зависания при импорте менеджера конфигураций.
    """
    _colors_cache = None

    @classmethod
    def init_colors(cls):
        """Вызывать этот метод строго внутри рендер-потока ESP после инициализации overlay_init!"""
        try:
            from pyMeow import get_color, fade_color
            cls.orange = get_color("orange")
            cls.black = get_color("black")
            cls.cyan = get_color("cyan")
            cls.white = get_color("white")
            cls.grey = fade_color(get_color("#242625"), 0.7)
            cls.red = get_color("red")
            cls.green = get_color("green")
            cls.blue = get_color("blue")
            cls.yellow = get_color("yellow")
        except ImportError:
            pass
