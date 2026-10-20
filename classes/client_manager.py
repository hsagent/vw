import threading
from tkinter import messagebox

from classes.utility import Utility
from classes.logger import Logger
from classes.config_manager import ConfigManager

logger = Logger.get_logger(__name__)

class ClientManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.memory_manager = main_window.memory_manager
        self.features = main_window.features

    def _start_feature(self, feature_name, feature_obj, config):
        """Вспомогательный метод для безопасного запуска отдельной функции в потоке."""
        if not getattr(feature_obj, 'is_running', False):
            try:
                # КРИТИЧЕСКИ ВАЖНО ДЛЯ CS2: Сбрасываем эвент остановки перед стартом цикла
                if hasattr(feature_obj, 'stop_event'):
                    feature_obj.stop_event.clear()
                
                # Применяем актуальные настройки: без этого изменения, сделанные
                # пока функция была остановлена (клавиша, задержки, цвета),
                # не попадали в запускаемый поток.
                if hasattr(feature_obj, 'update_config'):
                    feature_obj.update_config(config)
                else:
                    feature_obj.config = config
                feature_obj.is_running = True
                
                # Создаем и запускаем демон-поток для логики чита
                thread = threading.Thread(target=feature_obj.start, daemon=True)
                thread.start()
                
                setattr(self.main_window, f'{feature_name.lower()}_thread', thread)
                logger.info(f"[Client] Функция {feature_name} успешно запущена.")
                return True
            except Exception:
                feature_obj.is_running = False
                logger.exception(f"Не удалось запустить поток функции: {feature_name}")
                messagebox.showerror(f"{feature_name} Error", f"Failed to start {feature_name}. Check logs.")
        return False

    def _stop_feature(self, feature_name, feature_obj):
        """Вспомогательный метод для корректной остановки и очистки потока."""
        if feature_obj and getattr(feature_obj, 'is_running', False):
            try:
                feature_obj.stop()
                thread = getattr(self.main_window, f'{feature_name.lower()}_thread', None)
                
                # Даем потоку время на завершение операций чтения памяти игры
                if thread and thread.is_alive():
                    thread.join(timeout=1.5)
                    if thread.is_alive():
                        logger.warning(f"[Client] Поток {feature_name} не завершился вовремя.")
                    else:
                        logger.info(f"[Client] Поток {feature_name} успешно остановлен.")
                
                setattr(self.main_window, f'{feature_name.lower()}_thread', None)
                feature_obj.is_running = False
                return True
            except Exception:
                logger.exception(f"Ошибка при плановой остановке функции: {feature_name}")
                feature_obj.is_running = False
        return False
    def start_client(self):
        """Запуск всех выбранных функций на основе настроек General."""
        if not Utility.is_game_running():
            messagebox.showerror("Game Not Running", "Процесс cs2.exe не найден. Запустите Counter-Strike 2 перед стартом.")
            return

        # Инициализируем наш умный MemoryManager (он сам скачает новые оффсеты)
        if not self.memory_manager.initialize():
            messagebox.showerror("Initialization Error", "Не удалось инициализировать чтение памяти. Проверьте соединение с интернетехническими базами дампера.")
            return

        config = ConfigManager.load_config()
        any_feature_started = False

        for config_key, feature_data in self.features.items():
            # Проверяем, включен ли тумблер (Triggerbot, ESP, Bunnyhop) в GUI
            if config.get("General", {}).get(config_key, False):
                feature_name = feature_data["name"]
                feature_obj = feature_data["instance"]
                
                if not getattr(feature_obj, 'is_running', False):
                    if self._start_feature(feature_name, feature_obj, config):
                        any_feature_started = True
                else:
                    logger.info(f"{feature_name} уже активен.")
                    any_feature_started = True

        if any_feature_started:
            self.main_window.update_client_status("Active", "#22c55e")
        else:
            logger.warning("Ни одна функция не выбрана в General.")
            messagebox.showwarning("No Features Enabled", "Пожалуйста, включите хотя бы одну функцию во вкладке General Settings.")

    def stop_client(self):
        """Полная остановка работы софта и выгрузка всех потоков."""
        features_stopped = False

        for feature_data in self.features.values():
            if self._stop_feature(feature_data["name"], feature_data["instance"]):
                features_stopped = True

        if features_stopped:
            self.main_window.update_client_status("Inactive", "#ef4444")
        else:
            logger.debug("Активные функции для остановки отсутствуют.")

    def apply_feature_state_changes(self, old_config, new_config):
        """Включение или выключение функций «на лету» при кликах в GUI."""
        game_running = Utility.is_game_running()

        for key, feature_data in self.features.items():
            old_enabled = old_config["General"].get(key, False)
            new_enabled = new_config["General"].get(key, False)
            is_running = getattr(feature_data["instance"], 'is_running', False)

            if old_enabled == new_enabled:
                continue

            if new_enabled and not is_running:
                if game_running:
                    if self.memory_manager.initialize():
                        self._start_feature(feature_data["name"], feature_data["instance"], new_config)
                    else:
                        logger.error(f"Не удалось инициализировать память для активации: {feature_data['name']}")
                else:
                    logger.warning(f"Невозможно запустить {feature_data['name']}: Игра закрыта.")
            elif not new_enabled and is_running:
                self._stop_feature(feature_data["name"], feature_data["instance"])

    def update_running_feature_configs(self, new_config):
        """Обновление параметров внутри работающих потоков (например, изменение задержки триггера)."""
        any_feature_running = False
        for feature_data in self.features.values():
            instance = feature_data["instance"]
            if getattr(instance, 'is_running', False):
                # Не у всех функций (например, TriggerBot/Bunnyhop) есть update_config
                if hasattr(instance, 'update_config'):
                    instance.update_config(new_config)
                logger.debug(f"Конфигурация для {feature_data['name']} успешно обновлена.")
                any_feature_running = True
        
        status = "Active" if any_feature_running else "Inactive"
        color = "#22c55e" if any_feature_running else "#ef4444"
        self.main_window.update_client_status(status, color)
