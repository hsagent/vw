import threading
import time
import pyMeow as overlay
import keyboard
import struct
from typing import Iterator, Optional, Dict

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)
# Define the main loop sleep time for reduced CPU usage
MAIN_LOOP_SLEEP = 0.05
# Number of entities to iterate over
ENTITY_COUNT = 64
# Size of each entity entry in memory
ENTITY_ENTRY_SIZE = 120

# Инициализируем пустой словарь связей костей
SKELETON_BONES = {}

# Позвоночник, тело и голова
SKELETON_BONES[6] = [5]       # Голова -> Шея
SKELETON_BONES[5] = [4]       # Шея -> Грудь
SKELETON_BONES[4] = [3, 13, 8] # Грудь -> Живот, Правое плечо, Левое плечо
SKELETON_BONES[3] = [2]       # Живот -> Центр
SKELETON_BONES[2] = [1]       # Центр -> Поясница
SKELETON_BONES[1] = [0]       # Поясница -> Таз

# Правая рука
SKELETON_BONES[13] = [14]     # Правое плечо -> Правый локоть
SKELETON_BONES[14] = [15]     # Правый локоть -> Правое запястье
SKELETON_BONES[15] = [16]     # Правое запястье -> Правая кисть

# Левая рука
SKELETON_BONES[8] = [9]       # Левое плечо -> Левый локоть
SKELETON_BONES[9] = [10]      # Левый локоть -> Левое запястье
SKELETON_BONES[10] = [11]     # Левая кисть -> Левая ладонь

# Ноги
SKELETON_BONES[0] = [22, 25]  # Таз -> Левое бедро, Правое бедро
SKELETON_BONES[22] = [23]     # Левое бедро -> Левое колено
SKELETON_BONES[23] = [24]     # Левое колено -> Левая стопа
SKELETON_BONES[25] = [26]     # Правое бедро -> Правое колено
SKELETON_BONES[26] = [27]     # Правое колено -> Правая стопа

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
        
        # Cached data
        self.name: str = ""
        self.health: int = 0
        self.team: int = -1
        self.pos: Dict[str, float] = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.dormant: bool = True
        self.all_bones_pos_3d: Optional[Dict[int, Dict[str, float]]] = None
    def update(self, use_transliteration: bool, skeleton_enabled: bool) -> bool:
        """Update all entity data at once to minimize memory reads."""
        try:
            self.health = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iHealth)
            if self.health <= 0 or self.health > 100:
                return False

            # Фикс: m_bDormant в CS2 находится внутри GameSceneNode
            game_scene = self.memory_manager.read_longlong(self.pawn_ptr + self.memory_manager.m_pGameSceneNode)
            if not game_scene:
                return False

            self.dormant = bool(self.memory_manager.read_int(game_scene + self.memory_manager.m_bDormant))
            if self.dormant:
                return False

            self.team = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iTeamNum)
            self.pos = self.memory_manager.read_vec3(self.pawn_ptr + self.memory_manager.m_vOldOrigin)
            
            raw_name = self.memory_manager.read_string(self.controller_ptr + self.memory_manager.m_iszPlayerName)
            self.name = Utility.transliterate(raw_name) if use_transliteration else raw_name

            if skeleton_enabled:
                self.all_bones_pos_3d = self.all_bone_pos(game_scene)
            else:
                self.all_bones_pos_3d = None

            return True
        except Exception:
            return False

    def bone_pos(self, bone: int) -> Dict[str, float]:
        """Get the 3D position of a specific bone, using cached data if available."""
        if self.all_bones_pos_3d and bone in self.all_bones_pos_3d:
            return self.all_bones_pos_3d[bone]
        
        try:
            game_scene = self.memory_manager.read_longlong(self.pawn_ptr + self.memory_manager.m_pGameSceneNode)
            bone_array_ptr = self.memory_manager.read_longlong(game_scene + self.memory_manager.m_pBoneArray)
            return self.memory_manager.read_vec3(bone_array_ptr + bone * 32)
        except Exception:
            return {"x": 0.0, "y": 0.0, "z": 0.0}

    def all_bone_pos(self, game_scene: int) -> Optional[Dict[int, Dict[str, float]]]:
        """Get all bone positions by reading the bone matrix safely."""
        try:
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
                    x, y, z = struct.unpack_from('fff', data, offset)
                    bone_positions[i] = {"x": x, "y": y, "z": z}
                except struct.error:
                    continue
            return bone_positions
        except Exception:
            return None

    @staticmethod
    def validate_screen_position(pos: Dict[str, float]) -> bool:
        """Validate if a screen position is within bounds."""
        return 0 <= pos["x"] <= overlay.get_screen_width() and 0 <= pos["y"] <= overlay.get_screen_height()

class CS2Overlay:
    """Manages the ESP overlay for Counter-Strike 2."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        """Initialize the Overlay with a shared MemoryManager instance."""
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.local_team = None
        self.screen_width = overlay.get_screen_width()
        self.screen_height = overlay.get_screen_height()
        self.load_configuration()

    def load_configuration(self) -> None:
        """Load and apply configuration settings."""
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
        """Update the configuration settings."""
        self.config = config
        self.load_configuration()
        logger.debug("Overlay configuration updated.")
    def iterate_entities(self, local_controller_ptr: int) -> Iterator[Entity]:
        """Iterate over game entities and yield valid Entity objects with updated 120-byte step."""
        ent_list_ptr = self.memory_manager.ent_list
        if not ent_list_ptr or not self.memory_manager.client_base:
            return

        for i in range(1, ENTITY_COUNT + 1):
            try:
                list_index = (i & 0x7FFF) >> 9
                entity_index = i & 0x1FF
                entry_ptr = self.memory_manager.read_longlong(ent_list_ptr + (8 * list_index) + 16)
                if not entry_ptr: continue

                # Фикс: шаг сетки равен строго 120 байтам для Source 2
                controller_ptr = self.memory_manager.read_longlong(entry_ptr + 120 * entity_index)
                if not controller_ptr or controller_ptr == local_controller_ptr: continue

                pawn_handle = self.memory_manager.read_int(controller_ptr + self.memory_manager.m_hPlayerPawn)
                if not pawn_handle: continue

                list_entry_ptr = self.memory_manager.read_longlong(ent_list_ptr + 8 * ((pawn_handle & 0x7FFF) >> 9) + 16)
                if not list_entry_ptr: continue

                pawn_ptr = self.memory_manager.read_longlong(list_entry_ptr + 120 * (pawn_handle & 0x1FF))
                if not pawn_ptr: continue

                entity = Entity(controller_ptr, pawn_ptr, self.memory_manager)
                if entity.update(self.use_transliteration, self.enable_skeleton):
                    yield entity
            except Exception:
                continue

    def draw_skeleton(self, entity: Entity, view_matrix: list, color: tuple, all_bones_pos_3d: Dict[int, Dict[str, float]]) -> None:
        """Draw the skeleton of an entity."""
        try:
            if not all_bones_pos_3d: return
            bone_positions_2d = {}
            for bone_id in ALL_BONE_IDS:
                if bone_id in all_bones_pos_3d:
                    pos_2d = overlay.world_to_screen(view_matrix, all_bones_pos_3d[bone_id], 1)
                    if pos_2d and entity.validate_screen_position(pos_2d):
                        bone_positions_2d[bone_id] = pos_2d

            for start_bone, end_bones in SKELETON_BONES.items():
                if start_bone in bone_positions_2d:
                    for end_bone in end_bones:
                        if end_bone in bone_positions_2d:
                            overlay.draw_line(
                                bone_positions_2d[start_bone]["x"], bone_positions_2d[start_bone]["y"],
                                bone_positions_2d[end_bone]["x"], bone_positions_2d[end_bone]["y"],
                                color, 1.5
                            )
        except Exception as e:
            logger.error(f"Error drawing skeleton: {e}")

    def draw_entity(self, entity: Entity, view_matrix: list, is_teammate: bool = False) -> None:
        """Render the ESP overlay for a given entity."""
        try:
            pos2d = overlay.world_to_screen(view_matrix, entity.pos, 1)
            head_pos2d = overlay.world_to_screen(view_matrix, entity.bone_pos(6), 1)

            if not entity.validate_screen_position(pos2d) or not entity.validate_screen_position(head_pos2d):
                return

            entity.pos2d, entity.head_pos2d = pos2d, head_pos2d
            box_height = entity.pos2d["y"] - entity.head_pos2d["y"]
            box_width = box_height / 2
            half_width = box_width / 2

            outline_color = overlay.get_color(self.teammate_color_hex if is_teammate else self.box_color_hex)
            text_color = overlay.get_color(self.text_color_hex)

            if self.enable_skeleton and entity.all_bones_pos_3d:
                self.draw_skeleton(entity, view_matrix, outline_color, entity.all_bones_pos_3d)

            if self.draw_snaplines:
                overlay.draw_line(
                    overlay.get_screen_width() / 2, overlay.get_screen_height(),
                    entity.head_pos2d["x"], entity.head_pos2d["y"],
                    overlay.get_color(self.snaplines_color_hex), 1.5
                )

            if self.enable_box:
                overlay.draw_rectangle_lines(
                    entity.head_pos2d["x"] - half_width, entity.head_pos2d["y"] - half_width / 2,
                    box_width, box_height + half_width / 2,
                    outline_color, self.box_line_thickness
                )

            if self.draw_nicknames:
                font_sz = 11
                text_w = overlay.measure_text(entity.name, font_sz)
                overlay.draw_text(
                    entity.name, entity.head_pos2d["x"] - text_w // 2,
                    entity.head_pos2d["y"] - half_width / 2 - 15, font_sz, text_color
                )

            # Рендеринг вертикальной полоски здоровья (HP Bar)
            bar_width, bar_margin = 4, 2
            bar_x = entity.head_pos2d["x"] - half_width - bar_width - bar_margin
            bar_y = entity.head_pos2d["y"] - half_width / 2
            bar_height = box_height + half_width / 2
            
            overlay.draw_rectangle(bar_x, bar_y, bar_width, bar_height, overlay.get_color("black"))
            health_percent = max(0, min(entity.health, 100))
            fill_height = (health_percent / 100.0) * bar_height
                        # Определение цвета полоски в зависимости от уровня здоровья (ms)
            fill_color = overlay.get_color("red" if health_percent <= 20 else "yellow" if health_percent <= 50 else "green")
            overlay.draw_rectangle(bar_x, bar_y + (bar_height - fill_height), bar_width, fill_height, fill_color)
            
            if self.draw_health_numbers:
                overlay.draw_text(f"{entity.health}", int(bar_x - 22), int(bar_y + bar_height / 2 - 5), 10, text_color)
        except Exception as e:
            logger.debug(f"Error drawing entity: {e}")

    
