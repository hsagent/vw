import threading
import time
import ctypes
from typing import Optional

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

logger = Logger.get_logger(__name__)
MAIN_LOOP_SLEEP = 0.001 

# Скан-код клавиши Пробел для эмуляции ввода
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002

# Флаги игрока в CS2 (находится ли на земле)
FL_ONGROUND = (1 << 0)

class CS2Bunnyhop:
    """Manages the Bunnyhop functionality for Counter-Strike 2 via WinAPI Input Simulation."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.load_configuration()

    def load_configuration(self):
        self.bunnyhop_enabled = self.config.get("General", {}).get("Bunnyhop", False)
        self.jump_key = self.config.get("Bunnyhop", {}).get("JumpKey", "space").lower()
        self.jump_delay = self.config.get("Bunnyhop", {}).get("JumpDelay", 0.01)

    def update_config(self, config):
        self.config = config
        self.load_configuration()
        logger.debug("Bunnyhop configuration updated.")

    def start(self) -> None:
        """Start the Bunnyhop simulation loop."""
        self.is_running = True
        is_game_active = Utility.is_game_active
        sleep = time.sleep
        
        logger.info("Bunnyhop thread successfully started.")
        
        while not self.stop_event.is_set():
            try:
                if not self.bunnyhop_enabled or not is_game_active():
                    sleep(0.1)  # Спим дольше, если игра свернута или бхоп выключен
                    continue

                # Проверяем, зажата ли клавиша прыжка (например, пробел)
                vk_code = Utility.get_vk_code(self.jump_key)
                key_pressed = ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000

                if key_pressed:
                    # Читаем указатель на локального игрока (Local Player Pawn)
                    player_pawn = self.memory_manager.read_longlong(
                        self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
                    )
                    
                    if player_pawn:
                        # Читаем флаги игрока (m_fFlags обычно находится в клаصه C_BaseEntity)
                        # Если у вас еще нет m_fFlags в MemoryManager, временно захардкодьте его актуальное смещение, например 0x3CC или из дампа
                        m_fFlags_offset = getattr(self.memory_manager, "m_fFlags", 0x3CC) 
                        flags = self.memory_manager.read_int(player_pawn + m_fFlags_offset)
                        
                        # Если игрок стоит на земле (битовая маска FL_ONGROUND)
                        if flags & FL_ONGROUND:
                            # Симулируем нажатие пробела через ОС
                            ctypes.windll.user32.keybd_event(VK_SPACE, 0, 0, 0)
                            sleep(self.jump_delay)
                            # Симулируем отпускание пробела
                            ctypes.windll.user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
                
                sleep(MAIN_LOOP_SLEEP)
                
            except Exception as e:
                logger.error(f"Unexpected error in Bunnyhop loop: {e}", exc_info=True)
                sleep(MAIN_LOOP_SLEEP)

    def stop(self) -> None:
        """Stop the Bunnyhop."""
        self.is_running = False
        self.stop_event.set()
        logger.debug("Bunnyhop stopped.")
