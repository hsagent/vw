import threading
import time
from typing import Optional

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)
# Define the main loop sleep time for NoFlash
NOFLASH_LOOP_SLEEP = 0.01

class CS2NoFlash:
    """Manages the NoFlash functionality for Counter-Strike 2."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        """
        Initialize the NoFlash with a shared MemoryManager instance.
        """
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.local_player_address: Optional[int] = None
        
        # Cache offset
        self.flash_duration_offset: Optional[int] = None
        self.load_configuration()

    def load_configuration(self):
        """Load and apply configuration settings."""
        # Значение 0.0 означает полную слепоту (Suppression), 
        # однако новые структуры дампа хранят силу suppresion_strength
        self.flash_suppression_strength = float(self.config.get("NoFlash", {}).get("FlashSuppressionStrength", 0.0))

    def update_config(self, config):
        """Update the configuration settings."""
        self.config = config
        self.load_configuration()
        logger.debug("NoFlash configuration updated.")

    def initialize_local_player(self) -> bool:
        """Initialize the local player address."""
        if self.memory_manager.dwLocalPlayerPawn is None or self.memory_manager.m_flFlashDuration is None:
            logger.error("dwLocalPlayerPawn or m_flFlashDuration offset not initialized.")
            return False
        try:
            self.local_player_address = self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
            self.flash_duration_offset = self.memory_manager.m_flFlashDuration
            return True
        except Exception as e:
            logger.error(f"Error setting local player address: {e}")
            return False

    def start(self) -> None:
        """Start the NoFlash thread loop."""
        if not self.initialize_local_player():
            logger.error("Failed to initialize local player address.")
            return

        self.is_running = True
        self.stop_event.clear()

        # Cache frequently used functions
        is_game_active = Utility.is_game_active
        sleep = time.sleep
        read_longlong = self.memory_manager.read_longlong
        write_float = self.memory_manager.write_float
        
        local_player_addr = self.local_player_address
        flash_offset = self.flash_duration_offset
        
        failed_reads = 0
        max_failed_reads = 10
        reinit_backoff = 0.1
        max_reinit_backoff = 5.0
        logged_waiting = False

        logger.info("Фоновый поток функции NoFlash успешно запущен.")

        while not self.stop_event.is_set():
            try:
                if not is_game_active():
                    sleep(NOFLASH_LOOP_SLEEP)
                    logged_waiting = False
                    continue

                # Читаем указатель на базовый адрес нашей пешки (Pawn)
                player_position = read_longlong(local_player_addr)

                if player_position and player_position > 0:
                    if failed_reads > 0:
                        failed_reads = 0
                        reinit_backoff = 0.1
                        logged_waiting = False

                    # Читаем текущее значение m_flFlashDuration из игры
                    current_flash = self.memory_manager.pm.read_float(player_position + flash_offset)
                    
                    # ИСПРАВЛЕНИЕ: Прямое чтение self.flash_suppression_strength вместо локальной переменной
                    # Позволяет на лету менять степень suppression_strength из интерфейса
                    target_flash = self.flash_suppression_strength

                    # Записываем значение только если игрока ослепило (чтобы не перегружать шину памяти WPM)
                    if current_flash > target_flash:
                        try:
                            write_float(player_position + flash_offset, target_flash)
                        except Exception as e:
                            logger.debug(f"Error writing flash duration: {e}")
                            failed_reads += 1
                else:
                    failed_reads += 1

                    if failed_reads >= max_failed_reads:
                        if not logged_waiting:
                            logger.warning("NoFlash: Локальный плеер Pawn не найден, ожидаем спавна на карте...")
                            logged_waiting = True
                        if self.initialize_local_player():
                            local_player_addr = self.local_player_address
                            flash_offset = self.flash_duration_offset
                        failed_reads = 0
                        sleep(reinit_backoff)
                        reinit_backoff = min(reinit_backoff * 2, max_reinit_backoff)
                        continue

                sleep(NOFLASH_LOOP_SLEEP)

            except Exception as e:
                logger.error(f"Unexpected error in NoFlash loop: {e}", exc_info=True)
                failed_reads += 1
                sleep(NOFLASH_LOOP_SLEEP)

    def stop(self) -> None:
        """Stop the NoFlash and clean up resources."""
        self.is_running = False
        self.stop_event.set()
        logger.debug("NoFlash stopped.")
