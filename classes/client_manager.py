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

    def _any_feature_running(self):
        for feature_data in self.features.values():
            if getattr(feature_data["instance"], "is_running", False):
                return True
            thread = getattr(
                self.main_window,
                f'{feature_data["name"].lower()}_thread',
                None,
            )
            if thread and thread.is_alive():
                return True
        return False

    def _initialize_memory_if_needed(self):
        if self._any_feature_running() and self.memory_manager.pm is not None:
            return True
        return self.memory_manager.initialize()

    def _start_feature(self, feature_name, feature_obj, config):
        """Вспомогательный метод для безопасного запуска отдельной функции в потоке."""
        thread_attr = f'{feature_name.lower()}_thread'
        existing_thread = getattr(self.main_window, thread_attr, None)
        if existing_thread and existing_thread.is_alive():
            logger.warning(
                "[Client] Поток %s уже работает или ещё завершается; повторный запуск отменён.",
                feature_name,
            )
            return False
        if existing_thread is not None:
            setattr(self.main_window, thread_attr, None)

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
                
                thread = threading.Thread(
                    target=feature_obj.start,
                    daemon=True,
                    name=f"{feature_name}Worker",
                )
                setattr(self.main_window, thread_attr, thread)
                thread.start()
                logger.info(f"[Client] Функция {feature_name} успешно запущена.")
                return True
            except Exception:
                feature_obj.is_running = False
                logger.exception(f"Не удалось запустить поток функции: {feature_name}")
                messagebox.showerror(f"{feature_name} Error", f"Failed to start {feature_name}. Check logs.")
        return False

    def _stop_feature(self, feature_name, feature_obj):
        """Останавливает функцию, сохраняя ссылку на ещё живой поток."""
        thread_attr = f'{feature_name.lower()}_thread'
        thread = getattr(self.main_window, thread_attr, None)
        if not feature_obj:
            return False
        if not getattr(feature_obj, 'is_running', False) and not (
            thread and thread.is_alive()
        ):
            if thread is not None:
                setattr(self.main_window, thread_attr, None)
            return False

        try:
            feature_obj.stop()
            if thread and thread.is_alive():
                thread.join(timeout=1.5)
                if thread.is_alive():
                    logger.warning(
                        "[Client] Поток %s не завершился вовремя; ссылка сохранена.",
                        feature_name,
                    )
                    return False

            setattr(self.main_window, thread_attr, None)
            feature_obj.is_running = False
            logger.info(f"[Client] Поток {feature_name} успешно остановлен.")
            return True
        except Exception:
            logger.exception(f"Ошибка при плановой остановке функции: {feature_name}")
            return False
    def start_client(self):
        """Запуск всех выбранных функций на основе настроек General."""
        if not Utility.is_game_running():
            messagebox.showerror("Game Not Running", "Процесс cs2.exe не найден. Запустите Counter-Strike 2 перед стартом.")
            return

        # Инициализируем наш умный MemoryManager (он сам скачает новые оффсеты)
        config = ConfigManager.load_config()
        enabled_features = [
            feature_data
            for config_key, feature_data in self.features.items()
            if config.get("General", {}).get(config_key, False)
        ]
        if not enabled_features:
            self.stop_client()
            logger.warning("Ни одна функция не выбрана в General.")
            messagebox.showwarning(
                "No Features Enabled",
                "Пожалуйста, включите хотя бы одну функцию во вкладке General Settings.",
            )
            return

        if not self._initialize_memory_if_needed():
            messagebox.showerror(
                "Initialization Error",
                "Не удалось получить доступ к памяти CS2 или загрузить выбранные offsets.\n\n"
                "Проверьте источник offsets и локальные JSON-файлы, запустите программу "
                "от имени администратора и дождитесь полной загрузки игры."
            )
            return

        any_feature_started = False

        for feature_data in enabled_features:
            feature_name = feature_data["name"]
            feature_obj = feature_data["instance"]
            thread = getattr(
                self.main_window,
                f'{feature_name.lower()}_thread',
                None,
            )

            if thread and thread.is_alive():
                logger.info(f"{feature_name} уже активен или завершается.")
                any_feature_started = True
            elif not getattr(feature_obj, 'is_running', False):
                if self._start_feature(feature_name, feature_obj, config):
                    any_feature_started = True
            else:
                logger.info(f"{feature_name} уже активен.")
                any_feature_started = True

        if any_feature_started:
            self.main_window.update_client_status("Active", "#22c55e")
        else:
            self.stop_client()
            logger.error("Не удалось запустить ни одной выбранной функции.")
            messagebox.showerror(
                "Feature Start Error",
                "Не удалось запустить выбранные функции. Проверьте журнал приложения.",
            )

    def stop_client(self):
        """Полная остановка работы софта и выгрузка всех потоков."""
        features_stopped = False
        unfinished = []

        for feature_data in self.features.values():
            if self._stop_feature(feature_data["name"], feature_data["instance"]):
                features_stopped = True
            thread = getattr(
                self.main_window,
                f'{feature_data["name"].lower()}_thread',
                None,
            )
            if thread and thread.is_alive():
                unfinished.append(feature_data["name"])

        if unfinished:
            logger.warning(
                "[Client] Не завершились потоки: %s",
                ", ".join(unfinished),
            )
            return False

        self.memory_manager.close()
        if features_stopped:
            self.main_window.update_client_status("Inactive", "#ef4444")
        else:
            logger.debug("Активные функции для остановки отсутствуют.")
        return True

    def apply_feature_state_changes(self, old_config, new_config):
        """Включение или выключение функций «на лету» при кликах в GUI."""
        game_running = Utility.is_game_running()

        for key, feature_data in self.features.items():
            old_enabled = old_config["General"].get(key, False)
            new_enabled = new_config["General"].get(key, False)
            instance = feature_data["instance"]
            thread = getattr(
                self.main_window,
                f'{feature_data["name"].lower()}_thread',
                None,
            )
            is_running = getattr(instance, 'is_running', False) or bool(
                thread and thread.is_alive()
            )

            if old_enabled == new_enabled:
                continue

            if new_enabled:
                if is_running:
                    logger.warning(
                        "[Client] %s ещё работает или завершается; повторный запуск отменён.",
                        feature_data["name"],
                    )
                    continue
                if game_running:
                    if self._initialize_memory_if_needed():
                        self._start_feature(feature_data["name"], instance, new_config)
                    else:
                        logger.error(f"Не удалось инициализировать память для активации: {feature_data['name']}")
                else:
                    logger.warning(f"Невозможно запустить {feature_data['name']}: Игра закрыта.")
            elif is_running:
                self._stop_feature(feature_data["name"], instance)

        if not self._any_feature_running():
            self.memory_manager.close()

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
