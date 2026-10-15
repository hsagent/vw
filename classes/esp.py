import threading
import time
import pyMeow as overlay
import keyboard
import struct
from typing import Iterator, Optional, Dict

from classes.config_manager import ConfigManager, Colors, COLOR_CHOICES
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

logger = Logger.get_logger(__name__)

MAIN_LOOP_SLEEP = 0.001  # Уменьшено для плавности оверлея
ENTITY_COUNT = 64        # Увеличено до 64 (в матчах 5v5 + боты 32 может не хватать)

# Структура скелета {родительский_бон: [дочерние_боны]}
SKELETON_BONES = {
    6:,  # Голова -> Шея
    5:,  # Шея -> Грудь
    4:,  # Грудь -> Живот, Правое плечо, Левое плечо
    3:,  # Живот -> Центр
    2:,  # Центр -> Поясница
    1:,  # Поясница -> Таз
    13:,  # Правое плечо -> Правый локоть
    14:,  # Правый локоть -> Правое запястье
    15:,  # Правое запястье -> Правая кисть
    8:,   # Левое плечо -> Левый локоть
    9:,  # Левый локоть -> Левое запястье
    10:, # Левое запястье -> Левая кисть
    0:,  # Таз -> Левое бедро, Правое бедро
    22:,  # Левое бедро -> Левое колено
    23:,  # Левое колено -> Левая стопа
    25:,  # Правое бедро -> Правое колено
    26:,  # Правое колено -> Правая стопа
}
ALL_BONE_IDS = set(SKELETON_BONES.keys())
for _bones in SKELETON_BONES.values():
    ALL_BONE_IDS.update(_bones)
MAX_BONE_ID = max(ALL_BONE_IDS) if ALL_BONE_IDS else 0

class Entity:
    """Represents a game entity with cached data for efficient access."""
    def __init__(self, controller_ptr: int, pawn_ptr: int, memory_manager: MemoryManager) -> None:
        self.controller_ptr = controller_ptr
        self.pawn_ptr = pawn_ptr
        self.memory_manager = memory_manager
        self.pos2d: Optional[Dict[str, float]] = None
        self.head_pos2d: Optional[Dict[str, float]] = None
        
        self.name: str = ""
        self.health: int = 0
        self.team: int = -1
        self.pos: Dict[str, float] = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.dormant: bool = True
        self.all_bones_pos_3d: Optional[Dict[int, Dict[str, float]]] = None

    def update(self, use_transliteration: bool, skeleton_enabled: bool) -> bool:
        """Update all entity data at once to minimize memory reads."""
        try:
            # Чтение здоровья
            self.health = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iHealth)
            if self.health <= 0 or self.health > 100:
                return False

            # Исправление: bDormant находится в GameSceneNode, а не напрямую в пешке!
            game_scene = self.memory_manager.read_longlong(self.pawn_ptr + self.memory_manager.m_pGameSceneNode)
            if not game_scene:
                return False
                
            self.dormant = bool(self.memory_manager.read_int(game_scene + self.memory_manager.m_bDormant))
            if self.dormant:
                return False

            # Чтение команды и координат
            self.team = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iTeamNum)
            self.pos = self.memory_manager.read_vec3(self.pawn_ptr + self.memory_manager.m_vOldOrigin)
            
            # Чтение имени игрока
            raw_name = self.memory_manager.read_string(self.controller_ptr + self.memory_manager.m_iszPlayerName)
            self.name = Utility.transliterate(raw_name) if use_transliteration else raw_name

            if skeleton_enabled and game_scene:
                self.all_bones_pos_3d = self.all_bone_pos(game_scene)
            else:
                self.all_bones_pos_3d = None

            return True
        except Exception:
            return False

    def all_bone_pos(self, game_scene: int) -> Optional[Dict[int, Dict[str, float]]]:
        """Get all bone positions by reading the bone matrix safely."""
        try:
            # Извлекаем указатель на массив костей (уже скорректированный в Utility на +0x80)
            bone_array_ptr = self.memory_manager.read_longlong(game_scene + self.memory_manager.m_pBoneArray)
            if not bone_array_ptr:
                return None

            num_bones_to_read = MAX_BONE_ID + 1
            data = self.memory_manager.pm.read_bytes(bone_array_ptr, num_bones_to_read * 32)
            if not data:
                return None

            bone_positions = {}
            for i in ALL_BONE_IDS:
                offset = i * 32
                try:
                    # Извлекаем Vector3 (x, y, z) из матрицы костей
                    x, y, z = struct.unpack_from('fff', data, offset)
                    bone_positions[i] = {"x": x, "y": y, "z": z}
                except struct.error:
                    continue
            return bone_positions
        except Exception:
            return None


class CS2Overlay:
    """Manages the ESP overlay for Counter-Strike 2 using pyMeow."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.load_configuration()

    def load_configuration(self) -> None:
        settings = self.config['Overlay']
        self.enable_box = settings['enable_box']
        self.enable_skeleton = settings.get('enable_skeleton', True)
        self.draw_snaplines = settings['draw_snaplines']
        self.snaplines_color_hex = settings['snaplines_color_hex']
        self.box_line_thickness = settings['box_line_thickness']
        self.box_color_hex = settings['box_color_hex']
        self.text_color_hex = settings['text_color_hex']
        self.draw_health_numbers = settings['draw_health_numbers']
        self.use_transliteration = settings['use_transliteration']
        self.draw_nicknames = settings['draw_nicknames']
        self.draw_teammates = settings['draw_teammates']
        self.teammate_color_hex = settings['teammate_color_hex']
        self.target_fps = int(settings['target_fps'])

    def update_config(self, config: dict) -> None:
        self.config = config
        self.load_configuration()
        logger.debug("Overlay configuration updated.")

    def iterate_entities(self) -> Iterator[Entity]:
        """Iterate over game entities and yield valid Entity objects."""
        # Исправление: заменено не существующее client_dll_base на client_base
        if not self.memory_manager.client_base or not self.memory_manager.ent_list:
            return

        for i in range(1, ENTITY_COUNT + 1):
            try:
                # Поиск контроллера сущности в памяти
                list_entry = self.memory_manager.read_longlong(
                    self.memory_manager.ent_list + 8 * ((i & 0x7FFF) >> 9) + 16
                )
                if not list_entry:
                    continue

                controller_ptr = self.memory_manager.read_longlong(list_entry + 120 * (i & 0x1FF))
                if not controller_ptr:
                    continue

                # Получение пешки игрока через контроллер
                pawn_handle = self.memory_manager.read_int(controller_ptr + self.memory_manager.m_hPlayerPawn)
                if not pawn_handle:
                    continue

                # Ищем базовый адрес пешки в EntityList
                list_entry_pawn = self.memory_manager.read_longlong(
                    self.memory_manager.ent_list + 8 * ((pawn_handle & 0x7FFF) >> 9) + 16
                )
                if not list_entry_pawn:
                    continue

                pawn_ptr = self.memory_manager.read_longlong(list_entry_pawn + 120 * (pawn_handle & 0x1FF))
                if not pawn_ptr:
                    continue

                # Пропускаем отрисовку самого себя (Локального игрока)
                local_pawn = self.memory_manager.read_longlong(
                    self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
                )
                if pawn_ptr == local_pawn:
                    continue

                yield Entity(controller_ptr, pawn_ptr, self.memory_manager)

            except Exception:
                continue
