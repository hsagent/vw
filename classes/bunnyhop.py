import threading
import time
import ctypes
from typing import Optional

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

# Define the main loop sleep time for reduced CPU usage
MAIN_LOOP_SLEEP = 0.001  

# Константы WinAPI для симуляции ввода клавиатуры
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002

# Битовая маска флагов игрока в Source 2 (Нахождение на земле)
FL_ONGROUND = (1 << 0)

class CS2Bunnyhop:
    """Manages the Bunnyhop functionality for Counter-Strike 2 using OS-level Input Simulation."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        """
        Initialize the Bunnyhop with a shared MemoryManager instance.
        """
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        
        # Динамическое смещение флагов из дампа
        self.m_fFlags_offset: Optional[int] = None
        self.load_configuration()

    def load_configuration(self):
        """Load and apply configuration settings."""
        self.bunnyhop_enabled = self.config.get("General", {}).get("Bunnyhop", False)
        self.jump_key = self.config.get("Bunnyhop", {}).get("JumpKey", "space").lower()
        self.jump_delay = self.config.get("Bunnyhop", {}).get("JumpDelay", 0.015)

    def update_config(self, config):
        """Update the configuration settings."""
        self.config = config
        self.load_configuration()
        logger.debug("Bunnyhop configuration updated.")

    def initialize_flags_offset(self) -> bool:
        """Рекурсивно извлекает смещение m_fFlags из класса C_BaseEntity."""
        try:
            # Извлекаем поле из client_data через наш get_field в Utility
            if hasattr(Utility, 'extract_offsets') and self.memory_manager.client_data:
                classes = self.memory_manager.client_data.get("client.dll", {}).get("classes", {})
                class_info = classes.get("C_BaseEntity", {})
                self.m_fFlags_offset = class_info.get("fields", {}).get("m_fFlags")
            
            # Резервный хардкод под текущий патч, если в JSON нет поля
            if self.m_fFlags_offset is None:
                self.m_fFlags_offset = 0x3CC  # Актуальное смещение m_fFlags для текущей версии CS2
                
            return True
        except Exception as e:
            logger.error(f"Error initializing m_fFlags offset: {e}")
            return False

    def start(self) -> None:
        """Start the Bunnyhop simulation loop."""
        if not self.initialize_flags_offset():
            logger.error("Failed to initialize m_fFlags offset.")
            return

        self.is_running = True
        self.stop_event.clear()

        is_game_active = Utility.is_game_active
        sleep = time.sleep
        read_longlong = self.memory_manager.read_longlong
        read_int = self.memory_manager.read_int
        
        logger.info("Фоновый поток Bunnyhop (OS-Input Simulation) успешно запущен.")
        
        while not self.stop_event.is_set():
            try:
                # Если бхоп отключен в меню или игра свернута — отдыхаем
                if not self.bunnyhop_enabled or not is_game_active():
                    sleep(0.05)
                    continue

                # Проверяем, зажал ли пользователь установленную клавишу бхопа (например, Пробел)
                vk_code = Utility.get_vk_code(self.jump_key)
                key_pressed = ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000

                if key_pressed:
                    # Читаем указатель на локального игрока (Pawn)
                    player_pawn = read_longlong(self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn)
                    
                    if player_pawn and player_pawn > 0:
                        # Читаем флаги пешки персонажа
                        flags = read_int(player_pawn + self.m_fFlags_offset)
                        
                        # Если первый бит флагов равен 1 (игрок коснулся земли)
                        if flags & FL_ONGROUND:
                            # Симулируем нажатие клавиши прыжка через ОС Windows
                            ctypes.windll.user32.keybd_event(VK_SPACE, 0, 0, 0)
                            sleep(self.jump_delay)
                            # Симулируем отжатие клавиши прыжка
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
