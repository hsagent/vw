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

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)
# Define the main loop sleep time for reduced CPU usage
MAIN_LOOP_SLEEP = 0.05
# Number of entities to iterate over
ENTITY_COUNT = 64
# Size of each entity entry in memory
ENTITY_ENTRY_SIZE = 120

# Полная оригинальная структура скелета {родительский_бон: [дочерние_боны]}
SKELETON_BONES = {
    # Trunk Core Chain
    6:,  # Head -> Neck
    5:,  # Neck -> Chest
    4:,  # Chest -> Stomach, Right Shoulder, Left Shoulder
    3:,  # Stomach -> Center Point
    2:,  # Center Point -> Small Head
    1:,  # Small Head -> Pelvis 
    # Right Hand Chain (4 points)
    13:,  # Right Shoulder -> Right Elbow
    14:,  # Right Elbow -> Right Wrist
    15:,  # Right Wrist -> Right Hand 
    # Left Arm Chain (4 points)
    8:,  # Left Shoulder -> Left Elbow
    9:,  # Left Elbow -> Left Wrist
    10:,  # Left Wrist -> Left Hand
    # Legs Chain
    0:,  # Pelvis -> Left Hip, Right Hip
    22:,  # Left Hip -> Left Knee
    23:,  # Left Knee -> Left Foot
    25:,  # Right Hip -> Right Knee
    26:,  # Right Knee -> Right Foot
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
            fill_color = overlay.get_color("red" if health_percent  None:
        """Start the Overlay rendering loop."""
        self.is_running = True
        self.stop_event.clear()

        try:
            overlay.overlay_init("Counter-Strike 2", fps=0)
        except Exception as e:
            logger.error(f"Overlay initialization error: {e}")
            self.is_running = False
            return

        frame_time = 1.0 / self.target_fps
        is_game_active = Utility.is_game_active
        sleep = time.sleep
        logger.info("Фоновый прозрачный оверлей ESP Wallhack успешно запущен.")

        while not self.stop_event.is_set():
            start_time = time.time()
            try:
                if not is_game_active():
                    sleep(0.05)
                    continue

                view_matrix = self.memory_manager.read_floats(self.memory_manager.client_base + self.memory_manager.dwViewMatrix, 16)
                local_controller_ptr = self.memory_manager.read_longlong(self.memory_manager.client_base + self.memory_manager.dwLocalPlayerController)
                
                if local_controller_ptr:
                    local_pawn_ptr = self.memory_manager.read_longlong(self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn)
                    self.local_team = self.memory_manager.read_int(local_pawn_ptr + self.memory_manager.m_iTeamNum) if local_pawn_ptr else None
                else:
                    self.local_team = None

                entities = list(self.iterate_entities(local_controller_ptr))

                if overlay.overlay_loop():
                    overlay.begin_drawing()
                    for entity in entities:
                        is_teammate = self.local_team is not None and entity.team == self.local_team
                        if is_teammate and not self.draw_teammates:
                            continue
                        self.draw_entity(entity, view_matrix, is_teammate)
                    overlay.end_drawing()

                sleep_time = frame_time - (time.time() - start_time)
                if sleep_time > 0: sleep(sleep_time)
            except Exception as e:
                logger.error(f"Unexpected error in overlay loop: {e}")
                sleep(MAIN_LOOP_SLEEP)

        overlay.overlay_close()

    def stop(self) -> None:
        """Stop the Overlay."""
        self.is_running = False
        self.stop_event.set()
