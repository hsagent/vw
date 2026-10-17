import os
import threading
import sys
import subprocess
import requests
import json
from tkinter import messagebox
from classes.config_manager import ConfigManager
from classes.logger import Logger
from classes.utility import Utility

logger = Logger.get_logger(__name__)

class Updater:
    def __init__(self, main_window):
        self.main_window = main_window
        self.download_url = None
        self.is_prerelease = False

    def check_for_updates(self) -> bool:
        """Проверяет наличие обновлений, если софт запущен в виде скомпилированного .exe."""
        if getattr(sys, 'frozen', False):
            logger.info("[Updater] Запущено из исполняемого файла. Проверка обновлений...")
            try:
                download_url, is_prerelease = Utility.check_for_updates(ConfigManager.VERSION)
                if download_url:
                    self.download_url = download_url
                    self.is_prerelease = is_prerelease
                    return True
            except json.JSONDecodeError:
                logger.warning("[Updater] Сервер обновлений вернул некорректный ответ (JSONDecodeError). Пропуск проверки.")
            except Exception as e:
                logger.warning(f"[Updater] Не удалось проверить обновления (сервер недоступен): {e}")
        else:
            logger.info("[Updater] Запущено из исходного кода. Автоматическая проверка обновлений отключено.")
        return False

    def handle_update(self):
        """Вызывает всплывающее окно с предложением обновиться."""
        if not self.download_url:
            messagebox.showerror("Error", "Нет доступных обновлений.")
            return

        update_type = "pre-release (тестовая)" if self.is_prerelease else "stable (стабильная) версия"
        response = messagebox.askyesno(
            "Доступно обновление", 
            f"Доступна новая {update_type} софта MyProject под CS2. Хотите обновиться прямо сейчас?"
        )
        if response:
            messagebox.showinfo(
                "Обновление", 
                "Скачивание новой версии запущено в фоновом режиме. Программа закроется автоматически для установки."
            )
            threading.Thread(target=self.download_and_update, args=(self.download_url,), daemon=True).start()

    def download_and_update(self, download_url):
        """Скачивает новый .exe файл и передает управление батнику для подмены."""
        try:
            logger.info(f"[Updater] Скачивание обновления из: {download_url}")
            os.makedirs(ConfigManager.UPDATE_DIRECTORY, exist_ok=True)
            
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            current_exe = sys.executable
            exe_name = os.path.basename(current_exe)
            temp_exe = os.path.join(ConfigManager.UPDATE_DIRECTORY, "new_MyProject.exe")
            bat_file = os.path.join(ConfigManager.UPDATE_DIRECTORY, "update.bat")
            
            with open(temp_exe, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info("[Updater] Файл новой версии успешно скачан в локальный кэш.")
            
            with open(bat_file, 'w', encoding='cp866') as f:
                f.write(f'''@echo off
title MyProject Updater
echo Обновление MyProject под CS2...
echo.
echo Ожидание закрытия основного процесса программы...
timeout /t 3 /nobreak >nul

:WAIT_LOOP
tasklist /FI "IMAGENAME eq {exe_name}" 2>NUL | find /I /N "{exe_name}">NUL
if "%ERRORLEVEL%"=="0" (
    echo Программа все еще запущена, ожидание...
    timeout /t 2 /nobreak >nul
    goto WAIT_LOOP
)

echo Создание резервной копии старой версии...
if exist "{current_exe}.backup" del "{current_exe}.backup"
move "{current_exe}" "{current_exe}.backup"

echo Установка обновления...
move "{temp_exe}" "{current_exe}"

echo Запуск обновленного MyProject...
start "" "{current_exe}"

echo Обновление успешно завершено!
timeout /t 3 /nobreak >nul

echo Очистка временных файлов...
del "{current_exe}.backup" 2>nul
del "%~f0" 2>nul
''')
            
            logger.info(f"[Updater] Скрипт автоматизации создан по адресу: {bat_file}")
            subprocess.Popen(bat_file, shell=True)
            self.main_window.root.quit()
            
        except Exception as e:
            logger.error(f"[Updater] Сбой при попытке автоматического обновления: {e}")
            messagebox.showerror("Update Error", f"Не удалось установить обновление: {str(e)}")
