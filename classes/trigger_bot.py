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

logger = Logger.get_logger(__name__)
MAIN_LOOP_SLEEP = 0.001 

# Низкоуровневые константы WinAPI для эмуляции мыши
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class CS2TriggerBot:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.trigger_active = False
        self.toggle_state = False
        
        self.current_weapon_settings: Optional[Dict[str, Any]] = None
        self.last_weapon_type: Optional[str] = None
        self._vk_code_cache = {}
        
        self.load_configuration()
        logger.info("Низкоуровневый TriggerBot успешно инициализирован.")

    def load_configuration(self) -> None:
        settings = self.config['Trigger']
        self.trigger_key = settings['TriggerKey']
        self.toggle_mode = settings['ToggleMode']
        self.attack_on_teammates = settings['AttackOnTeammates']
        self.weapon_settings_cache = settings["WeaponSettings"]
        
        self.current_weapon_settings = None
        self.last_weapon_type = None

        self.mouse_button_map = {
            "mouse3": 0x04,  # VK_MBUTTON
            "mouse4": 0x05,  # VK_XBUTTON1
            "mouse5": 0x06,  # VK_XBUTTON2
        }

        self.is_mouse_trigger = self.trigger_key in self.mouse_button_map
        
        if self.is_mouse_trigger:
            self._trigger_vk_code = self.mouse_button_map[self.trigger_key]
        else:
            self._trigger_vk_code = Utility.get_vk_code(self.trigger_key)

    def update_config(self, config):
        self.config = config
        self.load_configuration()
        logger.debug("TriggerBot configuration updated.")

    def play_toggle_sound(self, state: bool) -> None:
        try:
            def play_sound():
                winsound.Beep(1000 if state else 500, 150)
            threading.Thread(target=play_sound, daemon=True).start()
        except Exception as e:
            logger.error(f"Error playing toggle sound: {e}")

    def should_trigger(self, entity_team: int, player_team: int, entity_health: int) -> bool:
        return (self.attack_on_teammates or entity_team != player_team) and 0  Dict[str, Any]:
        if weapon_type != self.last_weapon_type:
            self.current_weapon_settings = self.weapon_settings_cache.get(
                weapon_type, self.weapon_settings_cache.get("Rifles", {})
            )
            self.last_weapon_type = weapon_type
        return self.current_weapon_settings

    def is_trigger_key_pressed(self) -> bool:
        # Универсальная и быстрая проверка клавиш клавиатуры и мыши через GetAsyncKeyState
        return bool(ctypes.windll.user32.GetAsyncKeyState(self._trigger_vk_code) & 0x8000)

    def start(self) -> None:
        """Запуск основного цикла TriggerBot."""
        self.is_running = True
        is_game_active = Utility.is_game_active
        sleep = time.sleep
        get_fire_logic_data = self.memory_manager.get_fire_logic_data
        
        # Переключатель для режима ToggleMode
        last_toggle_press = 0

        while not self.stop_event.is_set():
            try:
                if not is_game_active():
                    sleep(0.1)
                    continue

                # Обработка режимов удержания и переключения клавиши
                key_pressed = self.is_trigger_key_pressed()
                
                if self.toggle_mode:
                    if key_pressed and (time.time() - last_toggle_press > 0.3):
                        self.toggle_state = not self.toggle_state
                        self.play_toggle_sound(self.toggle_state)
                        last_toggle_press = time.time()
                    trigger_ready = self.toggle_state
                else:
                    trigger_ready = key_pressed

                if not trigger_ready:
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Читаем данные из памяти игры
                data = get_fire_logic_data()
                if not data:
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Проверяем, враг ли перед нами
                if not self.should_trigger(data["entity_team"], data["player_team"], data["entity_health"]):
                    sleep(MAIN_LOOP_SLEEP)
                    continue

                # Получаем задержки выстрела из конфигурации оружия
                weapon_type = data.get("weapon_type", "Rifles")
                settings = self.get_weapon_settings(weapon_type)
                
                shot_delay_min = settings.get("ShotDelayMin", 10) / 1000.0
                shot_delay_max = settings.get("ShotDelayMax", 30) / 1000.0
                post_shot_delay = settings.get("PostShotDelay", 100) / 1000.0

                # 1. Задержка перед выстрелом (имитация реакции человека)
                delay = random.uniform(shot_delay_min, shot_delay_max)
                if delay > 0:
                    sleep(delay)

                # 2. Низкоуровневый клик мыши через WinAPI (Не блокируется CS2)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                sleep(0.01)  # Время удержания ЛКМ нажатой
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

                # 3. Задержка после выстрела для контроля темпа
                sleep(post_shot_delay + random.uniform(0.01, 0.03))

            except Exception as e:
                logger.error(f"Ошибка в основном цикле триггербота: {e}", exc_info=True)
                sleep(MAIN_LOOP_SLEEP)

    def stop(self) -> None:
        """Остановка триггербота."""
        self.is_running = False
        self.stop_event.set()
        logger.debug("TriggerBot stopped.")
