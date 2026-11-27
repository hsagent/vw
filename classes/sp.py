import ctypes
import threading
import time

from classes.config_manager import ConfigManager
from classes.logger import Logger
from classes.utility import Utility
from typing import Dict, Any

logger = Logger.get_logger(__name__)

# Флаги игрока CS2
FL_ONGROUND = 1 << 0  # Игрок на земле

# Скан-код Пробела для DirectInput (резервный способ)
SPACE_SCAN_CODE = 0x39
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

# dwForceJump: 0x10001 — «+jump», 0x100 — «-jump» (значения из CS2_External)
FORCE_JUMP_PRESS = 0x00010001
FORCE_JUMP_RELEASE = 0x00000100

_user32 = ctypes.windll.user32


def press_space():
    """Резервный способ: эмуляция Пробела через keybd_event."""
    _user32.keybd_event(0, SPACE_SCAN_CODE, KEYEVENTF_SCANCODE, 0)
    time.sleep(0.01)
    _user32.keybd_event(0, SPACE_SCAN_CODE, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)


class CS2Bunnyhop:
    def __init__(self, memory_manager) -> None:
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()

        self.config = ConfigManager.load_config()
        self.load_configuration()

        self._force_jump_addr = 0
        self._last_jump_log = 0.0

    def load_configuration(self) -> None:
        """Читает клавишу активации и задержку из Bunnyhop-секции конфига."""
        settings = self.config.get("Bunnyhop", {})
        self.jump_key = str(settings.get("JumpKey", "space") or "space")
        self.jump_vk = Utility.get_vk_code(self.jump_key)
        try:
            self.jump_delay = min(0.1, max(0.005, float(settings.get("JumpDelay", 0.01))))
        except (TypeError, ValueError):
            self.jump_delay = 0.01

    def update_config(self, config: Dict[str, Any]) -> None:
        """Применяет новые настройки на лету (вызывается из GUI)."""
        self.config = config
        self.load_configuration()
        logger.debug("Конфигурация Bunnyhop успешно обновлена.")

    def _jump(self) -> bool:
        """Один прыжок: запись +jump/-jump в dwForceJump либо keybd_event."""
        if self._force_jump_addr and self.memory_manager.write_int(
            self._force_jump_addr, FORCE_JUMP_PRESS
        ):
            time.sleep(self.jump_delay)
            self.memory_manager.write_int(self._force_jump_addr, FORCE_JUMP_RELEASE)
            return True
        press_space()
        return False

    def start(self) -> None:
        """Запускает поток автоматического прыжка."""
        self.is_running = True
        self.stop_event.clear()

        jump_offset = getattr(self.memory_manager, "dwForceJump", 0)
        self._force_jump_addr = (
            self.memory_manager.client_base + jump_offset if jump_offset else 0
        )
        method = "dwForceJump" if self._force_jump_addr else "keybd_event (fallback)"
        logger.info(
            f"Bunnyhop запущен (клавиша: {self.jump_key}, задержка {self.jump_delay:.3f} с, "
            f"способ: {method})."
        )

        try:
            while not self.stop_event.is_set():
                try:
                    if _user32.GetAsyncKeyState(self.jump_vk) & 0x8000:
                        player = self.memory_manager.read_longlong(
                            self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
                        )
                        if player:
                            flags = self.memory_manager.read_int(player + self.memory_manager.m_fFlags)

                            # Проверяем флаг FL_ONGROUND
                            if flags & FL_ONGROUND:
                                used_force = self._jump()
                                now = time.monotonic()
                                if now - self._last_jump_log >= 1.0:
                                    self._last_jump_log = now
                                    logger.debug(
                                        f"Bunnyhop: прыжок (flags={flags:#x}, "
                                        f"forcejump={used_force})"
                                    )
                    if self.stop_event.wait(0.005):
                        break
                except Exception as e:
                    logger.debug(f"Ошибка в цикле Bunnyhop: {e}")
                    if self.stop_event.wait(0.1):
                        break
        finally:
            self.is_running = False
            logger.debug("Bunnyhop остановлен.")

    def stop(self) -> None:
        """Останавливает поток Bunnyhop."""
        self.is_running = False
        self.stop_event.set()
