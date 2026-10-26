import sys
import webbrowser
from tkinter import messagebox

from classes.config_manager import ConfigManager
from classes.logger import Logger
from classes.utility import Utility

logger = Logger.get_logger(__name__)


class Updater:
    def __init__(self, main_window):
        self.main_window = main_window
        self.release_url = None
        self.latest_version = None
        self.is_prerelease = False

    def check_for_updates(self) -> bool:
        """Проверяет GitHub и сохраняет ссылку на страницу нового релиза."""
        if not getattr(sys, "frozen", False):
            logger.info("[Updater] Запущено из исходного кода. Автоматическая проверка обновлений отключена.")
            return False

        logger.info("[Updater] Запущено из исполняемого файла. Проверка обновлений...")
        release = Utility.check_for_updates(ConfigManager.VERSION)
        if not release or not release["update_available"]:
            return False

        self.release_url = release["release_url"]
        self.latest_version = release["latest_version"]
        self.is_prerelease = release["is_prerelease"]
        return True

    def handle_update(self):
        """Предлагает открыть проверенную страницу релиза для ручной установки."""
        if not self.release_url:
            messagebox.showerror("Error", "Нет доступных обновлений.")
            return

        update_type = "тестовая" if self.is_prerelease else "стабильная"
        response = messagebox.askyesno(
            "Доступно обновление",
            f"Доступна новая {update_type} версия {self.latest_version}.\n\n"
            "Открыть официальную страницу релиза в браузере?",
        )
        if response:
            logger.info("[Updater] Открытие страницы релиза: %s", self.release_url)
            if not webbrowser.open(self.release_url):
                messagebox.showerror("Update Error", "Не удалось открыть страницу релиза в браузере.")
