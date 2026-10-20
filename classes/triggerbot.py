import ctypes
import random
import threading
import time
from typing import Dict, Any

from classes.config_manager import ConfigManager
from classes.logger import Logger
from classes.utility import Utility

logger = Logger.get_logger(__name__)

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_MOUSE = 0

LOOP_SLEEP = 0.001
IDLE_SLEEP = 0.005
ACTIVE_CHECK_INTERVAL = 0.25
TARGET_GRACE = 0.3

_user32 = ctypes.windll.user32


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", _MOUSEINPUT)]


def _is_key_down(vk: int) -> bool:
    """Состояние клавиши через GetAsyncKeyState (работает и для mouse4/mouse5)."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _send_mouse(flags: int) -> bool:
    """SendInput — современнее mouse_event, возвращает False при блокировке (UIPI)."""
    inp = _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(dwFlags=flags))
    try:
        return _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1
    except Exception:
        return False


def force_shoot() -> bool:
    """Одиночный выстрел. True, если клик удалось отправить.

    SendInput + fallback на mouse_event: если приложение запущено без прав
    администратора, а CS2 с ними, Windows блокирует синтетический ввод (UIPI),
    и оба вызова не доходят до игры — это видно по возвращаемому False.
    """
    ok = _send_mouse(MOUSEEVENTF_LEFTDOWN)
    if not ok:
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.01)
    up_ok = _send_mouse(MOUSEEVENTF_LEFTUP)
    if not up_ok:
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return ok and up_ok


class CS2TriggerBot:
    """Триггербот: стреляет, когда прицел наведён на цель, по нажатию клавиши."""

    def __init__(self, memory_manager) -> None:
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()

        self.config = ConfigManager.load_config()
        self.load_configuration()

        self._toggle_active = False
        self._key_was_down = False
        self._has_target = False
        self._next_shot_at = 0.0
        self._game_active = False
        self._last_active_check = 0.0
        self._active_logged = False
        self._target_logged = False
        self._last_diag_log = 0.0
        self._last_shot_log = 0.0
        self._last_target_seen = 0.0

    def load_configuration(self) -> None:
        """Читает настройки триггера и задержек для выбранного типа оружия."""
        settings = self.config.get("Trigger", {})

        self.trigger_key = str(settings.get("TriggerKey", "x") or "x")
        self.trigger_vk = Utility.get_vk_code(self.trigger_key)
        self.toggle_mode = bool(settings.get("ToggleMode", False))
        self.attack_teammates = bool(settings.get("AttackOnTeammates", False))
        self.config_weapon_type = settings.get("active_weapon_type", "Rifles")
        self.weapon_type = self.config_weapon_type
        self._set_delays()

    def _set_delays(self) -> None:
        """Подставляет ShotDelayMin/Max/PostShotDelay для текущего типа оружия."""
        settings = self.config.get("Trigger", {})
        weapon = settings.get("WeaponSettings", {}).get(self.weapon_type, {})
        self.shot_delay_min = max(0.0, self._safe_float(weapon.get("ShotDelayMin"), 0.01))
        self.shot_delay_max = max(self.shot_delay_min, self._safe_float(weapon.get("ShotDelayMax"), 0.03))
        self.post_shot_delay = max(0.0, self._safe_float(weapon.get("PostShotDelay"), 0.05))

    def _apply_weapon_type(self, weapon_type: str) -> None:
        """Переключает задержки при смене оружия (автоопределение из памяти)."""
        if not weapon_type or weapon_type == self.weapon_type:
            return
        if weapon_type not in ("Pistols", "Rifles", "Snipers", "SMGs", "Heavy"):
            return
        self.weapon_type = weapon_type
        self._set_delays()
        logger.debug(
            f"TriggerBot: активное оружие -> {weapon_type}, "
            f"задержки {self.shot_delay_min:.3f}-{self.shot_delay_max:.3f} / "
            f"post {self.post_shot_delay:.3f}"
        )

    @staticmethod
    def _safe_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def update_config(self, config: Dict[str, Any]) -> None:
        """Применяет новые настройки на лету (вызывается из GUI)."""
        self.config = config
        self.load_configuration()
        logger.debug("Конфигурация TriggerBot успешно обновлена.")

    def _can_shoot(self, fire_data: dict) -> bool:
        if fire_data["entity_health"] <= 0:
            return False
        is_teammate = fire_data["entity_team"] == fire_data["player_team"]
        return self.attack_teammates or not is_teammate

    def start(self) -> None:
        """Запускает поток сканирования прицела."""
        self.is_running = True
        self.stop_event.clear()
        self._toggle_active = False
        self._key_was_down = False
        self._has_target = False
        self._next_shot_at = 0.0
        self._last_target_seen = 0.0
        if self.trigger_vk == 0x20:
            logger.warning(
                "TriggerBot: TriggerKey=space — пробел одновременно является прыжком. "
                "Рекомендуется x или mouse4."
            )
        bunny_key = str(self.config.get("Bunnyhop", {}).get("JumpKey", "space") or "space")
        if Utility.get_vk_code(bunny_key) == self.trigger_vk:
            logger.warning(
                f"TriggerBot: TriggerKey={self.trigger_key} совпадает с Bunnyhop.JumpKey — "
                "bunnyhop будет генерировать синтетические нажатия и мешать триггеру."
            )
        logger.info(
            f"TriggerBot запущен (клавиша: {self.trigger_key}, "
            f"режим: {'toggle' if self.toggle_mode else 'hold'}, "
            f"задержки {self.shot_delay_min:.3f}-{self.shot_delay_max:.3f} / "
            f"post {self.post_shot_delay:.3f})"
        )

        try:
            while not self.stop_event.is_set():
                try:
                    now = time.monotonic()

                    if now - self._last_active_check >= ACTIVE_CHECK_INTERVAL:
                        self._last_active_check = now
                        self._game_active = Utility.is_game_active()
                    if not self._game_active:
                        self._reset_target()
                        if now - self._last_diag_log >= 5.0:
                            self._last_diag_log = now
                            logger.debug("Trigger: окно CS2 не активно")
                        time.sleep(0.05)
                        continue

                    key_down = _is_key_down(self.trigger_vk)
                    if self.toggle_mode:
                        if key_down and not self._key_was_down:
                            self._toggle_active = not self._toggle_active
                        active = self._toggle_active
                    else:
                        active = key_down
                    self._key_was_down = key_down

                    if not active:
                        self._reset_target()
                        if self._active_logged:
                            self._active_logged = False
                            logger.debug("Trigger: не активен (клавиша отпущена/выключен toggle)")
                        elif now - self._last_diag_log >= 2.0:
                            idx = self.memory_manager.get_crosshair_entity_index()
                            if idx > 0:
                                self._last_diag_log = now
                                logger.debug(
                                    f"Trigger: цель id={idx} под прицелом, но клавиша "
                                    f"{self.trigger_key} не нажата"
                                )
                        time.sleep(IDLE_SLEEP)
                        continue

                    if not self._active_logged:
                        self._active_logged = True
                        logger.debug(f"Trigger: активен (клавиша {self.trigger_key})")

                    fire_data = self.memory_manager.get_fire_logic_data()
                    if not fire_data or not self._can_shoot(fire_data):
                        # m_iIDEntIndex может «мигать» на границе хитбокса —
                        # короткую потерю цели не считаем новой целью, иначе
                        # задержка реакции (0.1 с у винтовок) всё время
                        # перезапускается и выстрела не происходит.
                        if self._has_target and (now - self._last_target_seen) <= TARGET_GRACE:
                            time.sleep(LOOP_SLEEP)
                            continue
                        # Grace period истек или цели никогда не было
                        self._reset_target()
                        if now - self._last_diag_log >= 2.0:
                            self._last_diag_log = now
                            logger.debug(
                                "Trigger: активен, цели нет "
                                f"(m_iIDEntIndex={self.memory_manager.get_crosshair_entity_index()})"
                            )
                        time.sleep(LOOP_SLEEP)
                        continue

                    self._last_target_seen = now

                    # Автоопределение типа оружия: задержки меняются на лету
                    self._apply_weapon_type(fire_data.get("weapon_type") or "")

                    if not self._has_target:
                        self._has_target = True
                        # Человекоподобная задержка реакции на появление цели
                        self._next_shot_at = now + random.uniform(
                            self.shot_delay_min, self.shot_delay_max
                        )
                        if not self._target_logged:
                            self._target_logged = True
                            logger.debug(
                                f"Trigger: цель id={fire_data.get('entity_index')} "
                                f"team={fire_data['entity_team']} hp={fire_data['entity_health']} "
                                f"weapon={fire_data.get('weapon_type') or '?'}"
                            )

                    if now >= self._next_shot_at:
                        if force_shoot():
                            self._next_shot_at = time.monotonic() + self.post_shot_delay
                            if now - self._last_shot_log >= 1.0:
                                self._last_shot_log = now
                                logger.debug(
                                    f"Trigger: выстрел (цель {fire_data.get('entity_index')}, "
                                    f"{self.weapon_type})"
                                )
                        else:
                            if now - self._last_diag_log >= 2.0:
                                self._last_diag_log = now
                                logger.debug(
                                    "Trigger: клик не доставлен (SendInput/mouse_event) — "
                                    "проверь, что приложение запущено от администратора"
                                )
                            self._next_shot_at = time.monotonic() + 0.1
                except Exception as e:
                    logger.debug(f"Ошибка в цикле TriggerBot: {e}")
                    time.sleep(0.05)
        finally:
            self.is_running = False
            self._toggle_active = False
            logger.debug("TriggerBot остановлен.")

    def _reset_target(self) -> None:
        self._has_target = False
        self._next_shot_at = 0.0
        self._target_logged = False
        self._last_target_seen = 0.0

    def stop(self) -> None:
        """Останавливает поток триггербота."""
        self.is_running = False
        self.stop_event.set()
