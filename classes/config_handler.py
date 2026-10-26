import os
import threading
from watchdog.events import FileSystemEventHandler

from classes.config_manager import ConfigManager
from classes.logger import Logger

# Инициализация логгера для отслеживания событий
logger = Logger.get_logger(__name__)

class ConfigFileChangeHandler(FileSystemEventHandler):
    """
    Обработчик событий файловой системы для отслеживания изменений в config.json.
    Автоматически синхронизирует измененные в GUI настройки с активными потоками CS2.
    """
    def __init__(self, main_window, debounce_interval=0.5):
        """Инициализирует обработчик событий с ссылкой на главное окно."""
        self.main_window = main_window
        self.debounce_interval = debounce_interval
        self.debounce_timer = None
        self._timer_lock = threading.Lock()
        self._closed = False
        self.config_path = os.path.normcase(os.path.abspath(ConfigManager.CONFIG_FILE))

    def _schedule_reload(self, event_path):
        """Планирует перезагрузку, если событие относится к config.json."""
        if not event_path:
            return
        try:
            event_path = os.path.normcase(os.path.abspath(event_path))
            if event_path != self.config_path:
                return
            with self._timer_lock:
                if self._closed:
                    return
                if self.debounce_timer is not None:
                    self.debounce_timer.cancel()
                self.debounce_timer = threading.Timer(self.debounce_interval, self.reload_config)
                self.debounce_timer.daemon = True
                self.debounce_timer.start()
        except (OSError, ValueError):
            logger.debug("Не удалось обработать событие конфигурации: %s", event_path)

    def on_modified(self, event):
        self._schedule_reload(event.src_path)

    def on_created(self, event):
        self._schedule_reload(event.src_path)

    def on_moved(self, event):
        self._schedule_reload(getattr(event, "dest_path", None))

    def cancel(self):
        """Закрывает обработчик и отменяет ожидающую перезагрузку."""
        with self._timer_lock:
            self._closed = True
            if self.debounce_timer is not None:
                self.debounce_timer.cancel()
                self.debounce_timer = None

    def reload_config(self):
        """Сбрасывает кэш памяти, перечитывает диск и обновляет конфигурацию всех потоков."""
        with self._timer_lock:
            self.debounce_timer = None
            if self._closed:
                return
        try:
            logger.info("[ConfigHandler] Обнаружено изменение файла конфигурации. Перезагрузка...")
            
            old_config, new_config = ConfigManager.reload_config()
            
            if hasattr(self.main_window, 'root') and self.main_window.root:
                def apply_changes():
                    if hasattr(self.main_window, 'client_manager') and self.main_window.client_manager:
                        self.main_window.client_manager.apply_feature_state_changes(old_config, new_config)
                        self.main_window.client_manager.update_running_feature_configs(new_config)
                    else:
                        for name in ('triggerbot', 'overlay', 'bunnyhop', 'noflash'):
                            feature = getattr(self.main_window, name, None)
                            if feature and hasattr(feature, 'update_config'):
                                feature.update_config(new_config)
                    self.main_window.update_ui_from_config()
                self.main_window.root.after(0, apply_changes)
                
            logger.info("[ConfigHandler] Все активные функции успешно синхронизированы с новой конфигурацией.")
            
        except Exception as e:
            logger.exception("[ConfigHandler] Не удалось перезагрузить файл конфигурации: %s", e)
