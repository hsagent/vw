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
        """
        Инициализирует обработчик событий с ссылкой на главное окно.
        """
        self.main_window = main_window
        self.debounce_interval = debounce_interval
        self.debounce_timer = None
        self.config_path = ConfigManager.CONFIG_FILE

    def on_modified(self, event):
        """Вызывается операционной системой, когда файл конфигурации изменяется."""
        if event.src_path and os.path.exists(self.config_path):
            try:
                # Проверяем, что изменен именно наш файл конфигурации
                if os.path.samefile(event.src_path, self.config_path):
                    if self.debounce_timer is not None:
                        self.debounce_timer.cancel()
                    
                    # Запускаем таймер задержки перед обновлением данных
                    self.debounce_timer = threading.Timer(self.debounce_interval, self.reload_config)
                    self.debounce_timer.start()
            except Exception:
                # Исключаем падение, если файл был временно заблокирован другим процессом
                pass

    def reload_config(self):
        """Сбрасывает кэш памяти, перечитывает диск и обновляет конфигурацию всех потоков."""
        try:
            logger.info("[ConfigHandler] Обнаружено изменение файла конфигурации. Перезагрузка...")
            
            # Сохраняем старый конфиг для вычисления дельты изменений
            old_config = ConfigManager.load_config()
            
            # ФИКС: Принудительно зануляем кэш в ОЗУ, чтобы прочитать новые данные с диска
            ConfigManager._config_cache = None
            
            # Загружаем уже обновленный с диска JSON
            new_config = ConfigManager.load_config()
            
            # 1. Задействуем ClientManager для безопасного обновления запущенных потоков
            if hasattr(self.main_window, 'client_manager') and self.main_window.client_manager:
                # Передаем изменения для включения/выключения функций «на лету»
                self.main_window.client_manager.apply_feature_state_changes(old_config, new_config)
                # Передаем обновленные настройки (задержки, клавиши) внутрь активных циклов
                self.main_window.client_manager.update_running_feature_configs(new_config)
            else:
                # Резервный вариант прямого обновления, если ClientManager не инициализирован
                if hasattr(self.main_window, 'triggerbot') and self.main_window.triggerbot:
                    self.main_window.triggerbot.update_config(new_config)
                if hasattr(self.main_window, 'overlay') and self.main_window.overlay:
                    self.main_window.overlay.update_config(new_config)
                if hasattr(self.main_window, 'bunnyhop') and self.main_window.bunnyhop:
                    self.main_window.bunnyhop.update_config(new_config)
                if hasattr(self.main_window, 'noflash') and self.main_window.noflash:
                    self.main_window.noflash.update_config(new_config)

            # 2. Безопасно обновляем элементы интерфейса GUI в основном потоке Tkinter
            if hasattr(self.main_window, 'root') and self.main_window.root:
                self.main_window.root.after(0, self.main_window.update_ui_from_config)
                
            logger.info("[ConfigHandler] Все активные функции успешно синхронизированы с новой конфигурацией.")
            
        except Exception as e:
            logger.exception("[ConfigHandler] Не удалось перезагрузить файл конфигурации: %s", e)
