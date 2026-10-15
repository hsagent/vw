import os
import orjson
import copy
from pathlib import Path
from typing import Dict, Any, Optional
import threading

from classes.logger import Logger

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

class ConfigManager:
    """
    Thread-safe configuration manager for the application.
    
    Provides methods to load and save configuration settings with:
    - Automatic caching for performance
    - Thread-safe operations
    - Automatic migration of missing keys
    - Validation and error recovery
    """
    
    # Application version
    VERSION = "v1"
    
    # Directory paths
    UPDATE_DIRECTORY = os.path.expanduser(r'~\AppData\Local\NewProjectName\Update')
    OFFSETS_DIRECTORY = os.path.expanduser(r'~\AppData\Local\NewProjectName\Offsets')
    CONFIG_DIRECTORY = os.path.expanduser(r'~\AppData\Local\NewProjectName')
    CONFIG_FILE = Path(CONFIG_DIRECTORY) / 'config.json'
    
    # СИНХРОНИЗИРОВАННАЯ КОНФИГУРАЦИЯ ПО УМОЛЧАНИЮ
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
                # Значения теперь строго в МИЛЛИСЕКУНДАХ (целые числа) для корректной работы рандомайзера задержек
                "Pistols": {"ShotDelayMin": 10, "ShotDelayMax": 30, "PostShotDelay": 150},
                "Rifles": {"ShotDelayMin": 15, "ShotDelayMax": 40, "PostShotDelay": 100},
                "Snipers": {"ShotDelayMin": 0, "ShotDelayMax": 5, "PostShotDelay": 400},
                "SMGs": {"ShotDelayMin": 5, "ShotDelayMax": 20, "PostShotDelay": 80},
                "Heavy": {"ShotDelayMin": 20, "ShotDelayMax": 50, "PostShotDelay": 250}
            }
        },
        "Overlay": {
            "target_fps": 60,
            "enable_box": True,
            "enable_skeleton": True,      # Включаем скелеты по умолчанию для теста обновленной матрицы костей
            "draw_snaplines": False,       # Снаплайны лучше выключить, чтобы не засорять обзор
            "snaplines_color_hex": "#FFFFFF",
            "box_line_thickness": 1.5,
            "box_color_hex": "#FFA500",
            "text_color_hex": "#FFFFFF",
            "draw_health_numbers": True,
            "use_transliteration": True,   # Включаем транслитерацию для защиты от краша pyMeow при чтении кириллицы в никах
            "draw_nicknames": True,
            "draw_teammates": False,
            "teammate_color_hex": "#00FFFF"
        },
        "Bunnyhop": {
            "JumpKey": "space",
            "JumpDelay": 0.015            # Оптимальная задержка субтика прыжка
        },
        "NoFlash": {
            "FlashSuppressionStrength": 0.0
        },
        "GitHub": {
            "AccessToken": None
        }
    }
    
    # Cache and thread safety
    _config_cache: Optional[Dict[str, Any]] = None
    _lock: threading.Lock = threading.Lock()
