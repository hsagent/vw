import threading
import time
import random
import ctypes
import winsound
from typing import Optional, Dict, Any

from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

# Define the main loop sleep time for reduced CPU usage
MAIN_LOOP_SLEEP = 0.001  

# Низкоуровневые системные константы WinAPI для мыши
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class CS2TriggerBot:
    def __init__(self, memory_manager: MemoryManager) -> None:
        """
        Initialize the TriggerBot with a shared MemoryManager instance.
        """
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.toggle_state = False
        
        # Cached weapon settings for current weapon
        self.current_weapon_settings: Optional[Dict[str, Any]] = None
        self.last_weapon_type: Optional[str] = None
        
        # Запуск первоначальной конфигурации клавиш
        self.load_configuration()
        logger.info("Низкоуровневый аппаратный TriggerBot успешно инициализирован.")

    def load_configuration(self) -> None:
        """Load and apply configuration settings."""
        settings = self.config['Trigger']
        self.trigger_key = settings['TriggerKey']
        self.toggle_mode = settings['ToggleMode']
        self.attack_on_teammates = settings['AttackOnTeammates']
        self.weapon_settings_cache = settings["WeaponSettings"]
        
        self.current_weapon_settings = None
        self.last_weapon_type = None
        
        # Карта аппаратных кодов GetAsyncKeyState для дополнительных кнопок мыши
        self.mouse_button_map = {
            "mouse1": 0x01,
            "mouse2": 0x02,
            "mouse3": 0x04,  # Колесико
            "mouse4": 0x05,  # Боковая кнопка 1
            "mouse5": 0x06,  # Боковая кнопка 2
        }

        self.is_mouse_trigger = self.trigger_key in self.mouse_button_map
        
        # Кэшируем итоговый VK_CODE для мгновенного опроса клавиатуры/мыши в цикле
        if self.is_mouse_trigger:
            self._trigger_vk_code = self.mouse_button_map[self.trigger_key]
        else:
            self._trigger_vk_code = Utility.get_vk_code(self.trigger_key)

    def update_config(self, config):
        """Update the configuration settings."""
        self.config = config
        self.load_configuration()
        logger.debug("TriggerBot configuration updated.")

    def play_toggle_sound(self, state: bool) -> None:
        """Play a sound when the toggle key is pressed."""
        try:
            def play_sound():
                winsound.Beep(1000 if state else 500, 150)
            threading.Thread(target=play_sound, daemon=True).start()
        except Exception as e:
            logger.error(f"Error playing toggle sound: {e}")

    def should_trigger(self, entity_team: int, player_team: int, entity_health: int) -> bool:
        """Determine if the bot should fire."""
        return (self.attack_on_teammates or entity_team != player_team) and 0  Dict[str, Any]:
        """Get weapon settings with caching for performance."""
        if weapon_type != self.last_weapon_type:
            self.current_weapon_settings = self.weapon_settings_cache.get(
                weapon_type, self.weapon_settings_cache.get("Rifles", {})
            )
            self.last_weapon_type = weapon_type
            logger.debug(f"TriggerBot weapon profile switched to: {weapon_type}")
        return self.current_weapon_settings

    def should_trigger(self, entity_team: int, player_team: int, entity_health: int) -> bool:
        """Determine if the bot should fire."""
        # Проверяем условия ведения огня: (атака по тимейтам разрешена ИЛИ это враг) И здоровье в рамках нормы (от 1 до 100)
        return (self.attack_on_teammates or entity_team != player_team) and 0 < entity_health <= 100

    def start(self) -> None:
        """Start the TriggerBot high-performance loop."""
        self.is_running = True
        self.stop_event.clear()

        # Local variables cache for maximum loop iteration speed
        is_game_active = Utility.is_game_active
        sleep = time.sleep
        get_fire_logic_data = self.memory_manager.get_fire_logic_data
        
        last_shot_time = 0
        min_shot_interval = 0.05  # Защитная задержка между выстрелами (50мс) против двойных кликов
        last_toggle_press = 0.0
        
        while not self.stop_event.is_set():
            try:
                # Если игра свернута — разгружаем процессор
                if not is_game_active():
                    sleep(0.05)
                    continue

                # Опрашиваем состояние нашей горячей клавиши триггера
                key_pressed = self.is_trigger_key_pressed()
                
                if self.toggle_mode:
                    # Режим переключателя (Toggle): меняем состояние при нажатии с дебаунсом в 300мс
                    if key_pressed and (time.time() - last_toggle_press > 0.3):
                        self.toggle_state = not self.toggle_state
                        self.play_toggle_sound(self.toggle_state)
                        last_toggle_press = time.time()
                    trigger_ready = self.toggle_state
                else:
                    # Режим удержания (Hold): работает строго пока кнопка зажата
                    trigger_ready = key_pressed

                if not trigger_ready:
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Извлекаем данные о противнике под прицелом из менеджера памяти
                data = get_fire_logic_data()
                if not data:
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Проверяем условия ведения огня (Не союзник + жив)
                if not self.should_trigger(data["entity_team"], data["player_team"], data["entity_health"]):
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Проверка лимита скорострельности
                current_time = time.time()
                if current_time - last_shot_time < min_shot_interval:
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Получаем профиль задержек под текущее удерживаемое оружие
                weapon_type = data.get("weapon_type", "Rifles")
                weapon_settings = self.get_weapon_settings(weapon_type)
                
                if not weapon_settings:
                    weapon_settings = self.weapon_settings_cache.get("Rifles", {})
                
                # ИСПРАВЛЕНИЕ: Переводим миллисекунды из конфигурации в доли секунды (/ 1000.0)
                shot_delay_min = weapon_settings.get('ShotDelayMin', 10) / 1000.0
                shot_delay_max = weapon_settings.get('ShotDelayMax', 35) / 1000.0
                post_shot_delay = weapon_settings.get('PostShotDelay', 100) / 1000.0

                # 1. Выдерживаем паузу перед выстрелом (Имитация пинга и реакции человека)
                if shot_delay_max > shot_delay_min:
                    delay = random.uniform(shot_delay_min, shot_delay_max)
                    if delay > 0:
                        sleep(delay)

                # 2. ИСПРАВЛЕНИЕ: Низкоуровневая эмуляция клика мыши на уровне ядра ОС (Не блокируется игрой)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                sleep(0.01)  # Фиксированное время удержания спуска в зажатом состоянии (10мс)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                
                last_shot_time = time.time()
                
                # 3. Выдерживаем паузу после выстрела (Контроль темпа стрельбы)
                if post_shot_delay > 0:
                    sleep(post_shot_delay + random.uniform(0.005, 0.015))

            except Exception as e:
                logger.error(f"Unexpected error in TriggerBot loop: {e}", exc_info=True)
                sleep(MAIN_LOOP_SLEEP)

    def stop(self) -> None:
        """Stops the TriggerBot and cleans up resources."""
        self.is_running = False
        self.stop_event.set()
        logger.debug("TriggerBot stopped cleanly.")
