import os
import threading
from watchdog.events import FileSystemEventHandler

from classes.config_manager import ConfigManager
from classes.logger import Logger

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

class ConfigFileChangeHandler(FileSystemEventHandler):
    """
    A file system event handler for monitoring changes to the configuration file.
    Automatically updates the configuration for all features when the config file is modified.
    """
    def __init__(self, main_window, debounce_interval=0.3):
        """
        Initializes the file change handler with a reference to the main window instance.
        Caches the configuration file path for efficiency.

        Args:
            main_window: Instance of MainWindow managing all features.
            debounce_interval: Time in seconds to debounce file change events.
                               (ИСПРАВЛЕНИЕ: 0.3с оптимально, 1.0s — слишком долгий отклик для чита)
        """
        self.main_window = main_window
        self.debounce_interval = debounce_interval
        self.debounce_timer = None
        self.config_path = ConfigManager.CONFIG_FILE

    def on_modified(self, event):
        """Called when a file or directory is modified."""
        try:
            if event.src_path and os.path.exists(self.config_path) and os.path.samefile(event.src_path, self.config_path):
                if self.debounce_timer is not None:
                    self.debounce_timer.cancel()
                self.debounce_timer = threading.Timer(self.debounce_interval, self.reload_config)
                self.debounce_timer.start()
        except Exception:
            # Защита от краша watchdog, если Windows на наносекунду заблокировала файл
            pass

    def reload_config(self):
        """Reloads the configuration file and updates all feature configurations safely."""
        try:
            logger.debug("Наблюдатель зафиксировал изменение config.json на диске. Перечитываем...")
            
            # Перезагружаем конфигурацию (защищено потоковым Lock внутри ConfigManager)
            new_config = ConfigManager.load_config()
            
            # ИСПРАВЛЕНИЕ: Вместо пассивной подмены словарей вызываем сквозное 
            # обновление через ClientManager. Это мгновенно применит новые задержки/кнопки во всех потоках!
            if hasattr(self.main_window, 'client_manager'):
                self.main_window.client_manager.update_running_feature_configs(new_config)
            else:
                # Резервный откат на случай, если вызов произошел до привязки ClientManager
                if hasattr(self.main_window, 'triggerbot') and hasattr(self.main_window.triggerbot, 'update_config'):
                    self.main_window.triggerbot.update_config(new_config)
                if hasattr(self.main_window, 'overlay') and hasattr(self.main_window.overlay, 'update_config'):
                    self.main_window.overlay.update_config(new_config)
                if hasattr(self.main_window, 'bunnyhop') and hasattr(self.main_window.bunnyhop, 'update_config'):
                    self.main_window.bunnyhop.update_config(new_config)
                if hasattr(self.main_window, 'noflash') and hasattr(self.main_window.noflash, 'update_config'):
                    self.main_window.noflash.update_config(new_config)
            
            # Асинхронно синхронизируем визуальное состояние элементов Tkinter GUI в основном потоке
            if hasattr(self.main_window, 'root') and hasattr(self.main_window, 'update_ui_from_config'):
                self.main_window.root.after(0, self.main_window.update_ui_from_config)
                
            logger.info("Все конфигурации фоновых потоков и GUI успешно обновлены «на лету».")
        except Exception as e:
            logger.exception("Failed to reload configuration from %s: %s", self.config_path, e)
