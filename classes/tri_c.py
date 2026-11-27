import threading, time, random, ctypes, winsound
from typing import Optional, Dict, Any
from classes.config_manager import ConfigManager
from classes.memory_manager import MemoryManager
from classes.logger import Logger
from classes.utility import Utility
logger = Logger.get_logger(__name__)
MAIN_LOOP_SLEEP = 0.001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
class CS2TriggerBot:
    def __init__(self, memory_manager: MemoryManager):
        self.config = ConfigManager.load_config()
        self.memory_manager = memory_manager
        self.is_running = False
        self.stop_event = threading.Event()
        self.toggle_state = False
        self.current_weapon_settings = None
        self.last_weapon_type = None
        self.load_configuration()
    def load_configuration(self):
        settings = self.config['Trigger']
        self.trigger_key = settings['TriggerKey']
        self.toggle_mode = settings['ToggleMode']
        self.attack_on_teammates = settings['AttackOnTeammates']
        self.weapon_settings_cache = settings["WeaponSettings"]
        self.mouse_button_map = {"mouse1": 0x01, "mouse2": 0x02, "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}
        if self.trigger_key in self.mouse_button_map:
            self._trigger_vk_code = self.mouse_button_map[self.trigger_key]
        else:
            self._trigger_vk_code = Utility.get_vk_code(self.trigger_key)
    def update_config(self, config):
        self.config = config
        self.load_configuration()
    def play_toggle_sound(self, state):
        try:
            def play_sound(): winsound.Beep(1000 if state else 500, 150)
            threading.Thread(target=play_sound, daemon=True).start()
        except Exception: pass
    def is_trigger_key_pressed(self):
        return bool(ctypes.windll.user32.GetAsyncKeyState(self._trigger_vk_code) & 0x8000)
    def should_trigger(self, entity_team, player_team, entity_health):
        return (self.attack_on_teammates or entity_team != player_team) and 0 < entity_health <= 100
    def get_weapon_settings(self, weapon_type):
        if weapon_type != self.last_weapon_type:
            self.current_weapon_settings = self.weapon_settings_cache.get(weapon_type, self.weapon_settings_cache.get("Rifles", {}))
            self.last_weapon_type = weapon_type
        return self.current_weapon_settings
    def start(self):
        self.is_running = True
        self.stop_event.clear()
        while not self.stop_event.is_set():
            try:
                if not Utility.is_game_active():
                    time.sleep(0.05)
                    continue
                key_pressed = self.is_trigger_key_pressed()
                if self.toggle_mode:
                    trigger_ready = self.toggle_state
                else:
                    trigger_ready = key_pressed
                if not trigger_ready:
                    time.sleep(MAIN_LOOP_SLEEP)
                    continue
                data = self.memory_manager.get_fire_logic_data()
                if not data or not self.should_trigger(data["entity_team"], data["player_team"], data["entity_health"]):
                    time.sleep(MAIN_LOOP_SLEEP)
                    continue
                w_set = self.get_weapon_settings(data.get("weapon_type", "Rifles"))
                time.sleep(w_set.get('ShotDelayMin', 10) / 1000.0)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.01)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(w_set.get('PostShotDelay', 100) / 1000.0)
            except Exception:
                time.sleep(MAIN_LOOP_SLEEP)
    def stop(self):
        self.is_running = False
        self.stop_event.set()
