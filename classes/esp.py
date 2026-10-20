import threading
import time
import struct
import pyMeow as overlay
from typing import Iterator, Optional, Dict

from classes.config_manager import ConfigManager, Colors
from classes.memory_manager import MemoryManager, ENTITY_INDEX_MASK
from classes.logger import Logger
from classes.utility import Utility

# Инициализация логгера
logger = Logger.get_logger(__name__)

# Сон основного цикла для снижения нагрузки на CPU
MAIN_LOOP_SLEEP = 0.01

# АКТУАЛЬНО ДЛЯ CS2: размер записи entity list на текущей сборке — 112 байт (0x70).
# Реально используемый размер определяется в MemoryManager.detect_entity_entry_size().
ENTITY_COUNT = 64
ENTITY_ENTRY_SIZE = 112

# Максимальный индекс, до которого раз в 5 секунд ищем контроллеры игроков
DISCOVERY_MAX_INDEX = 512
DISCOVERY_INTERVAL = 5.0

HEAD_BONE = 6
BONE_STRIDE = 32

# ПОЛНАЯ структура костей скелета для CS2 {родитель: [дочерние]}
SKELETON_BONES = dict([
    (6, [5]),          # Head -> Neck
    (5, [4]),          # Neck -> Chest
    (4, [3, 13, 8]),   # Chest -> Stomach, Right Shoulder, Left Shoulder
    (3, [2]),          # Stomach -> Center Point
    (2, [1]),          # Center Point -> Small Head
    (1, [0]),          # Small Head -> Pelvis

    # Правая рука
    (13, [14]),        # Right Shoulder -> Right Elbow
    (14, [15]),        # Right Elbow -> Right Wrist
    (15, [16]),        # Right Wrist -> Right Hand

    # Левая рука
    (8, [9]),          # Left Shoulder -> Left Elbow
    (9, [10]),         # Left Elbow -> Left Wrist
    (10, [11]),        # Left Wrist -> Left Hand

    # Ноги
    (0, [22, 25]),     # Pelvis -> Left Hip, Right Hip
    (22, [23]),        # Left Hip -> Left Knee
    (23, [24]),        # Left Knee -> Left Foot
    (25, [26]),        # Right Hip -> Right Knee
    (26, [27])         # Right Knee -> Right Foot
])

ALL_BONE_IDS = set(SKELETON_BONES.keys())
for _bones in SKELETON_BONES.values():
    ALL_BONE_IDS.update(_bones)
MAX_BONE_ID = max(ALL_BONE_IDS) if ALL_BONE_IDS else 0

# Список линий скелета строится из SKELETON_BONES, чтобы не дублировать структуру
BONE_CONNECTIONS = tuple(
    (parent, child)
    for parent, children in SKELETON_BONES.items()
    for child in children
)

ZERO_VEC3 = {"x": 0.0, "y": 0.0, "z": 0.0}


class Entity:
    """Представляет сущность игрока в CS2 с оптимизированным чтением памяти."""
    def __init__(self, controller_ptr: int, pawn_ptr: int, memory_manager: MemoryManager) -> None:
        self.controller_ptr = controller_ptr
        self.pawn_ptr = pawn_ptr
        self.memory_manager = memory_manager

        self.name: str = ""
        self.health: int = 0
        self.team: int = -1
        self.pos: Dict[str, float] = dict(ZERO_VEC3)
        self.dormant: bool = False
        self.head_pos_3d: Optional[Dict[str, float]] = None
        self.all_bones_pos_3d: Optional[Dict[int, Dict[str, float]]] = None

    def update(self, use_transliteration: bool, skeleton_enabled: bool) -> bool:
        """Обновляет данные сущности за минимальное количество обращений к памяти."""
        try:
            self.health = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iHealth)
            if self.health <= 0 or self.health > 100:
                # У dormant-пешек HP в pawn может не обновляться — уточняем
                # состояние по контроллеру игрока.
                controller_health = self.memory_manager.read_int(
                    self.controller_ptr + self.memory_manager.m_iPawnHealth
                )
                controller_alive = self.memory_manager.read_int(
                    self.controller_ptr + self.memory_manager.m_bPawnIsAlive
                )
                if controller_alive & 0xFF and 0 < controller_health <= 100:
                    self.health = controller_health
                else:
                    return False

            # Проверка видимости игрока на сцене (Dormant). Scene-узел может
            # отсутствовать у dormant-сущности, поэтому он не обязателен:
            # последняя известная позиция pawn всё равно пригодна для бокса.
            game_scene = self.memory_manager.read_longlong(self.pawn_ptr + self.memory_manager.m_pGameSceneNode)

            # Dormant-сущности не отбрасываем: CS2 хранит последнюю известную
            # позицию/кости, иначе ESP показывал бы только игроков в PVS
            # (на практике это 1-2 человека из каждой команды).
            self.dormant = False
            if game_scene:
                self.dormant = bool(self.memory_manager.read_int(game_scene + self.memory_manager.m_bDormant))

            self.team = self.memory_manager.read_int(self.pawn_ptr + self.memory_manager.m_iTeamNum)
            self.pos = self.memory_manager.read_vec3(self.pawn_ptr + self.memory_manager.m_vOldOrigin)
            if not (self.pos["x"] or self.pos["y"] or self.pos["z"]):
                return False

            raw_name = self.memory_manager.read_string(self.controller_ptr + self.memory_manager.m_iszPlayerName)
            if not raw_name:
                raw_name = "Player"
            self.name = Utility.transliterate(raw_name) if use_transliteration else raw_name

            # Позиция головы нужна всегда (по ней строится бокс), скелет — опционально
            self.all_bones_pos_3d = None
            self.head_pos_3d = None
            if game_scene:
                if skeleton_enabled:
                    self.all_bones_pos_3d = self.all_bone_pos(game_scene)
                    self.head_pos_3d = (self.all_bones_pos_3d or {}).get(HEAD_BONE)
                    if self.head_pos_3d is None:
                        self.head_pos_3d = self.single_bone_pos(game_scene, HEAD_BONE)
                else:
                    self.head_pos_3d = self.single_bone_pos(game_scene, HEAD_BONE)

            return True
        except Exception:
            return False

    def bone_pos(self, bone: int) -> Dict[str, float]:
        """Возвращает 3D позицию конкретной кости из кэша."""
        if self.all_bones_pos_3d and bone in self.all_bones_pos_3d:
            return self.all_bones_pos_3d[bone]
        if bone == HEAD_BONE and self.head_pos_3d:
            return self.head_pos_3d
        return dict(ZERO_VEC3)

    def _bone_array_ptr(self, game_scene: int) -> int:
        return self.memory_manager.read_longlong(game_scene + self.memory_manager.m_pBoneArray)

    def single_bone_pos(self, game_scene: int, bone: int) -> Optional[Dict[str, float]]:
        """Читает позицию одной кости (дешевле, чем весь скелет)."""
        try:
            bone_array_ptr = self._bone_array_ptr(game_scene)
            if not bone_array_ptr:
                return None
            pos = self.memory_manager.read_vec3(bone_array_ptr + bone * BONE_STRIDE)
            if not (pos["x"] or pos["y"] or pos["z"]):
                return None
            return pos
        except Exception:
            return None

    def all_bone_pos(self, game_scene: int) -> Optional[Dict[int, Dict[str, float]]]:
        """Вытягивает из памяти матрицу всех костей игрока."""
        try:
            bone_array_ptr = self._bone_array_ptr(game_scene)
            if not bone_array_ptr:
                return None

            num_bones_to_read = MAX_BONE_ID + 1
            data = self.memory_manager.pm.read_bytes(bone_array_ptr, num_bones_to_read * BONE_STRIDE)
            if not data or len(data) < num_bones_to_read * BONE_STRIDE:
                return None

            bone_positions = {}
            for i in ALL_BONE_IDS:
                offset = i * BONE_STRIDE
                x, y, z = struct.unpack_from('fff', data, offset)
                bone_positions[i] = {"x": x, "y": y, "z": z}
            return bone_positions
        except Exception:
            return None

    @staticmethod
    def validate_screen_position(
        pos: Optional[Dict[str, float]],
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> bool:
        """Проверяет валидность координат проекции экрана (мягкое отсечение краев).

        Размер экрана можно передать один раз на кадр, чтобы не дергать
        get_screen_width/height для каждой кости.
        """
        if not pos:
            return False
        if screen_width is None:
            screen_width = overlay.get_screen_width()
        if screen_height is None:
            screen_height = overlay.get_screen_height()
        return (
            -500 <= pos["x"] <= (screen_width + 500)
            and -500 <= pos["y"] <= (screen_height + 500)
        )


class CS2Overlay:
    """Управляет созданием, конфигурацией и циклом отрисовки ESP оверлея."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.local_team = None
        self.screen_width = overlay.get_screen_width()
        self.screen_height = overlay.get_screen_height()
        self._color_cache: Dict[str, object] = {}
        # Индексы контроллеров вне стандартных 1..ENTITY_COUNT (если сервер
        # выдал игрокам более высокие слоты) и время последнего поиска.
        self._extra_indices: set = set()
        self._last_discovery = 0.0
        self.load_configuration()

    def load_configuration(self) -> None:
        """Применяет настройки из конфигурации проекта."""
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
        self.target_fps = max(1, int(settings['target_fps']))

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.load_configuration()
        logger.debug("Конфигурация ESP оверлея успешно обновлена.")

    def _color(self, value: str):
        """Кэширует результат get_color: разбор hex-строки не должен идти каждый кадр."""
        color = self._color_cache.get(value)
        if color is None:
            color = overlay.get_color(value)
            self._color_cache[value] = color
        return color

    def iterate_entities(self, local_controller_ptr: int) -> Iterator[Entity]:
        """Универсальный перебор игроков с авто-определением сдвигов движка Valve."""
        indices = set(range(1, ENTITY_COUNT + 1))
        indices.update(self._extra_indices)
        for i in sorted(indices):
            try:
                controller_ptr = self.memory_manager.get_entity(i)
                if not controller_ptr or controller_ptr == local_controller_ptr:
                    continue

                # m_hPlayerPawn — 32-битный CHandle, читаем int и маскируем индекс
                pawn_handle = self.memory_manager.read_int(
                    controller_ptr + self.memory_manager.m_hPlayerPawn
                )
                if not pawn_handle:
                    continue

                pawn_ptr = self.memory_manager.get_entity(pawn_handle & ENTITY_INDEX_MASK)
                if not pawn_ptr:
                    continue

                entity = Entity(controller_ptr, pawn_ptr, self.memory_manager)
                if entity.update(self.use_transliteration, self.enable_skeleton):
                    yield entity
            except Exception:
                continue

    def discover_extra_indices(self, local_controller_ptr: int) -> None:
        """Редкий (раз в 5 с) поиск игроков за пределами слотов 1..64."""
        found = set()
        for i in range(ENTITY_COUNT + 1, DISCOVERY_MAX_INDEX + 1):
            try:
                controller_ptr = self.memory_manager.get_entity(i)
                if not controller_ptr or controller_ptr == local_controller_ptr:
                    continue
                pawn_handle = self.memory_manager.read_int(
                    controller_ptr + self.memory_manager.m_hPlayerPawn
                )
                if not pawn_handle:
                    continue
                pawn_ptr = self.memory_manager.get_entity(pawn_handle & ENTITY_INDEX_MASK)
                if not pawn_ptr:
                    continue
                team = self.memory_manager.read_int(pawn_ptr + self.memory_manager.m_iTeamNum)
                health = self.memory_manager.read_int(pawn_ptr + self.memory_manager.m_iHealth)
                if team in (2, 3) and 0 < health <= 100:
                    found.add(i)
            except Exception:
                continue
        self._extra_indices = found
        if found:
            logger.debug(f"ESP: игроки найдены вне слотов 1..{ENTITY_COUNT}: {sorted(found)}")

    def draw_skeleton(self, entity: Entity, view_matrix: list, color: tuple, all_bones_pos_3d: Dict[int, Dict[str, float]]) -> None:
        """Отрисовывает линии костей скелета игрока."""
        if not all_bones_pos_3d:
            return

        bone_positions_2d = {}
        screen_width = overlay.get_screen_width()
        screen_height = overlay.get_screen_height()
        for bone_id in ALL_BONE_IDS:
            pos_3d = all_bones_pos_3d.get(bone_id)
            if pos_3d is None:
                continue
            try:
                pos_2d = overlay.world_to_screen(view_matrix, pos_3d, 1)
            except Exception:
                # world_to_screen бросает исключение для точек за камерой
                continue
            if entity.validate_screen_position(pos_2d, screen_width, screen_height):
                bone_positions_2d[bone_id] = pos_2d

        for start_bone, end_bone in BONE_CONNECTIONS:
            if start_bone in bone_positions_2d and end_bone in bone_positions_2d:
                overlay.draw_line(
                    bone_positions_2d[start_bone]["x"], bone_positions_2d[start_bone]["y"],
                    bone_positions_2d[end_bone]["x"], bone_positions_2d[end_bone]["y"],
                    color, 1.5
                )

    def draw_entity(self, entity: Entity, view_matrix: list, is_teammate: bool = False) -> None:
        """Рендерит элементы ESP (Box, Скелет, Никнейм, Здоровье) для сущности."""
        try:
            head_pos_3d = entity.head_pos_3d
            if not head_pos_3d:
                # У dormant/далёких сущностей кости могут быть недоступны —
                # строим бокс от последней известной позиции ног.
                if not (entity.pos["x"] or entity.pos["y"] or entity.pos["z"]):
                    return
                head_pos_3d = {
                    "x": entity.pos["x"],
                    "y": entity.pos["y"],
                    "z": entity.pos["z"] + 72.0,
                }

            try:
                pos2d = overlay.world_to_screen(view_matrix, entity.pos, 1)
                head_pos2d = overlay.world_to_screen(view_matrix, head_pos_3d, 1)
            except Exception:
                return

            screen_width = overlay.get_screen_width()
            screen_height = overlay.get_screen_height()
            if not entity.validate_screen_position(pos2d, screen_width, screen_height) \
                    or not entity.validate_screen_position(head_pos2d, screen_width, screen_height):
                return

            box_height = pos2d["y"] - head_pos2d["y"]
            if box_height <= 1:
                return
            box_width = box_height / 1.8
            half_width = box_width / 2

            box_color = self._color(self.teammate_color_hex if is_teammate else self.box_color_hex)
            text_color = self._color(self.text_color_hex)

            if self.enable_skeleton and entity.all_bones_pos_3d:
                self.draw_skeleton(entity, view_matrix, box_color, entity.all_bones_pos_3d)

            if self.draw_snaplines:
                overlay.draw_line(
                    screen_width / 2, screen_height,
                    pos2d["x"], pos2d["y"],
                    self._color(self.snaplines_color_hex), 1.2
                )

            if self.enable_box:
                overlay.draw_rectangle_lines(
                    head_pos2d["x"] - half_width, head_pos2d["y"] - 10,
                    box_width, box_height + 10,
                    box_color, self.box_line_thickness
                )

            if self.draw_nicknames:
                name_width = overlay.measure_text(entity.name, 12)
                overlay.draw_text(
                    entity.name,
                    head_pos2d["x"] - name_width / 2, head_pos2d["y"] - 26,
                    12, text_color
                )

            bar_width = 3
            bar_x = head_pos2d["x"] - half_width - 6
            bar_y = head_pos2d["y"] - 10
            bar_height = box_height + 10

            overlay.draw_rectangle(bar_x, bar_y, bar_width, bar_height, self._color("black"))

            health_percent = max(0, min(entity.health, 100))
            fill_height = (health_percent / 100.0) * bar_height
            fill_y = bar_y + (bar_height - fill_height)

            if health_percent > 0:
                if health_percent > 50:
                    health_color = self._color("green")
                elif health_percent > 25:
                    health_color = self._color("yellow")
                else:
                    health_color = self._color("red")
                overlay.draw_rectangle(bar_x, fill_y, bar_width, fill_height, health_color)

            if self.draw_health_numbers:
                health_text = str(entity.health)
                text_width = overlay.measure_text(health_text, 12)
                overlay.draw_text(
                    health_text,
                    bar_x - text_width - 4, fill_y - 6,
                    12, text_color
                )
        except Exception as e:
            logger.debug(f"Ошибка отрисовки сущности: {e}")

    def start(self) -> None:
        """Запускает поток отрисовки Overlay."""
        self.is_running = True
        self.stop_event.clear()

        try:
            overlay.overlay_init("Counter-Strike 2", fps=0)
            self.screen_width = overlay.get_screen_width()
            self.screen_height = overlay.get_screen_height()
            Colors.init_colors()
        except Exception as e:
            logger.error(f"Ошибка инициализации pyMeow оверлея: {e}")
            self.is_running = False
            return

        frame_time = 1.0 / self.target_fps
        is_game_active = Utility.is_game_active

        try:
            while not self.stop_event.is_set():
                start_time = time.time()
                try:
                    if not overlay.overlay_loop():
                        logger.debug("Окно оверлея закрыто, завершаю цикл отрисовки.")
                        break

                    if not is_game_active():
                        time.sleep(0.1)
                        continue

                    view_matrix = self.memory_manager.read_floats(
                        self.memory_manager.client_base + self.memory_manager.dwViewMatrix, 16
                    )
                    if len(view_matrix) != 16:
                        time.sleep(MAIN_LOOP_SLEEP)
                        continue

                    local_controller = self.memory_manager.read_longlong(
                        self.memory_manager.client_base + self.memory_manager.dwLocalPlayerController
                    )

                    if local_controller:
                        local_pawn = self.memory_manager.read_longlong(
                            self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
                        )
                        self.local_team = (
                            self.memory_manager.read_int(local_pawn + self.memory_manager.m_iTeamNum)
                            if local_pawn else None
                        )
                    else:
                        local_pawn = 0
                        self.local_team = None

                    now = time.time()
                    do_discovery = now - self._last_discovery >= DISCOVERY_INTERVAL
                    if do_discovery:
                        self._last_discovery = now
                        self.discover_extra_indices(local_controller)

                    entities = list(self.iterate_entities(local_controller))

                    # Если в матче вдруг не нашлось ни одного игрока — возможно,
                    # сменился размер записи entity list (112/120 байт).
                    if do_discovery and not entities and local_pawn:
                        old_size = self.memory_manager.entity_entry_size
                        self.memory_manager.detect_entity_entry_size()
                        if self.memory_manager.entity_entry_size != old_size:
                            entities = list(self.iterate_entities(local_controller))

                    if do_discovery:
                        logger.debug(
                            "ESP: игроков=%d dormant=%d extra=%s stride=%d",
                            len(entities),
                            sum(1 for e in entities if e.dormant),
                            sorted(self._extra_indices),
                            self.memory_manager.entity_entry_size,
                        )

                    try:
                        overlay.begin_drawing()
                        try:
                            for entity in entities:
                                is_teammate = self.local_team is not None and entity.team == self.local_team
                                if is_teammate and not self.draw_teammates:
                                    continue
                                self.draw_entity(entity, view_matrix, is_teammate)
                        except Exception as e:
                            logger.error(f"Ошибка рендеринга сущностей: {e}")
                        finally:
                            # end_drawing обязан вызываться всегда, иначе кадр raylib остаётся незавершённым
                            overlay.end_drawing()
                    except Exception as e:
                        logger.error(f"Критическая ошибка begin_drawing: {e}")

                    elapsed = time.time() - start_time
                    sleep_time = frame_time - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                except Exception as e:
                    logger.error(f"Ошибка в основном цикле оверлея pyMeow: {e}")
                    time.sleep(MAIN_LOOP_SLEEP)
        finally:
            try:
                overlay.overlay_close()
            except Exception:
                pass
            self.is_running = False
            logger.debug("Оверлей успешно закрыт и очищен.")

    def stop(self) -> None:
        """Останавливает работу оверлея."""
        self.is_running = False
        self.stop_event.set()
