import threading
import time
from typing import Dict, Any, Optional, Tuple

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

# Инициализация логгера
logger = Logger.get_logger(__name__)

# Сон основного цикла NoFlash
NOFLASH_LOOP_SLEEP = 0.01

class CS2NoFlash:
    """Управляет функционалом легитимного NoFlash для Counter-Strike 2."""
    def __init__(self, memory_manager: MemoryManager) -> None:
        """
        Инициализация NoFlash с общим экземпляром MemoryManager.
        """
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        
        self.local_player_address: Optional[int] = None
        self.flash_duration_offset: Optional[int] = None
        self.flash_max_alpha_offset: Optional[int] = None # ДОБАВЛЕНО для CS2
        
        self.load_configuration()

    def load_configuration(self):
        """Загружает и применяет настройки силы NoFlash."""
        # Значение от 0.0 (дефолтная слепота) до 255.0 (экран полностью чистый)
        # Безопаснее всего ставить частичное скрытие (например, 100.0)
        self.flash_suppression_strength = float(self.config.get("NoFlash", {}).get("FlashSuppressionStrength", 255.0))

    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновляет конфигурацию на лету прямо во время работы потока."""
        self.config = config
        self.load_configuration()
        logger.debug("Конфигурация NoFlash успешно обновлена.")

    def initialize_local_player(self) -> bool:
        """Инициализирует адреса локального игрока и смещения флеша."""
        if self.memory_manager.dwLocalPlayerPawn is None or self.memory_manager.m_flFlashDuration is None:
            logger.error("Оффсеты dwLocalPlayerPawn или m_flFlashDuration не найдены в MemoryManager.")
            return False
        try:
            self.local_player_address = self.memory_manager.client_base + self.memory_manager.dwLocalPlayerPawn
            self.flash_duration_offset = self.memory_manager.m_flFlashDuration

            # В CS2 оффсет MaxAlpha находится рядом с FlashDuration
            # Пробуем оба варианта: -4 и +4 байта
            # Используем конфигурируемое значение, если оно есть
            alpha_offset_config = self.config.get("NoFlash", {}).get("FlashMaxAlphaOffset")
            if alpha_offset_config:
                self.flash_max_alpha_offset = self.flash_duration_offset + int(alpha_offset_config)
            else:
                # По умолчанию пробуем -4 (наиболее частый случай)
                self.flash_max_alpha_offset = self.flash_duration_offset - 4
            return True
        except Exception as e:
            logger.error(f"Ошибка при инициализации адресов NoFlash: {e}")
            return False
    def start(self) -> None:
        """Запускает бесконечный поток NoFlash."""
        if not self.initialize_local_player():
            logger.error("Не удалось настроить локальные адреса для NoFlash.")
            self.is_running = False
            return

        self.is_running = True
        self.stop_event.clear()

        is_game_active = Utility.is_game_active
        sleep = time.sleep
        read_longlong = self.memory_manager.read_longlong
        read_float = self.memory_manager.pm.read_float if hasattr(self.memory_manager, 'pm') else None
        
        local_player_addr = self.local_player_address
        dur_offset = self.flash_duration_offset
        alpha_offset = self.flash_max_alpha_offset
        
        failed_reads = 0
        max_failed_reads = 10
        reinit_backoff = 0.1
        logged_waiting = False

        logger.info("Модуль NoFlash успешно запущен.")

        while not self.stop_event.is_set():
            try:
                if not is_game_active():
                    sleep(0.1)
                    logged_waiting = False
                    continue

                # Читаем указатель на LocalPlayerPawn
                player_position = read_longlong(local_player_addr)

                if player_position and player_position > 0:
                    if failed_reads > 0:
                        failed_reads = 0
                        reinit_backoff = 0.1
                        logged_waiting = False

                    # ИСПРАВЛЕНО: Берем актуальное значение силы подавления из конфига на каждом тике
                    target_alpha = self.flash_suppression_strength

                    # Читаем текущую длительность ослепления игрока
                    try:
                        current_duration = self.memory_manager.pm.read_float(player_position + dur_offset)
                        
                        # Если игрок ослеплен (длительность > 0)
                        if current_duration > 0.0:
                            # Изменяем альфу (прозрачность флеша) на легитимное значение
                            # Вместо записи 0 в duration (что палится античитом), мы снижаем интенсивность белого экрана
                            self.memory_manager.write_float(player_position + alpha_offset, target_alpha)
                            
                    except Exception:
                        failed_reads += 1
                else:
                    failed_reads += 1

                    # Если игрок умер или раунд перезапустился — выполняем мягкую переинициализацию
                    if failed_reads >= max_failed_reads:
                        if not logged_waiting:
                            logger.warning("Ожидание спавна локального игрока для NoFlash...")
                            logged_waiting = True
                        if self.initialize_local_player():
                            local_player_addr = self.local_player_address
                            dur_offset = self.flash_duration_offset
                            alpha_offset = self.flash_max_alpha_offset
                        failed_reads = 0
                        sleep(reinit_backoff)
                        reinit_backoff = min(reinit_backoff * 2, 2.0)
                        continue

                sleep(NOFLASH_LOOP_SLEEP)

            except Exception as e:
                logger.error(f"Непредвиденная ошибка в цикле NoFlash: {e}")
                failed_reads += 1
                sleep(NOFLASH_LOOP_SLEEP)

    def stop(self) -> None:
        """Останавливает работу модуля NoFlash."""
        self.is_running = False
        self.stop_event.set()
        logger.debug("NoFlash успешно остановлен.")
