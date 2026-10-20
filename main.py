import os
import sys
import signal
import threading
from pathlib import Path

# ЖЕСТКИЙ ФИКС ПУТЕЙ: вычисляем абсолютный путь к папке проекта на диске
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from classes.logger import Logger
from classes.config_manager import ConfigManager
from src.offsets import updater
from gui.main_window import MainWindow

def setup_signal_handlers(logger):
    """Настраивает обработчики системных сигналов ОС для чистого закрытия софта."""
    def signal_handler(signum, frame):
        logger.info(f"[Main] Получен системный сигнал {signum}. Экстренное завершение работы софта...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def main():
    """Главная точка входа в приложение My Project CS2."""    
    # 1. Настройка глобальной системы логирования
    try:
        Logger.setup_logging()
        logger = Logger.get_logger(__name__)
    except Exception as e:
        print(f"Fatal Error: Не удалось запустить систему логирования: {e}", file=sys.stderr)
        sys.exit(1)

    setup_signal_handlers(logger)

    # 2. Вывод текущей версии сборки софта
    try:
        version = ConfigManager.VERSION
        logger.info("My Project запущен. Версия сборки: %s", version)
    except Exception as e:
        logger.warning("Не удалось прочитать информацию о версии: %s", e)

    # 3. КРИТИЧЕСКИ ДЛЯ CS2: фоновый сбор смещений памяти, чтобы не блокировать
    # запуск GUI, если GitHub/дампер отвечает медленно.
    def prefetch_offsets():
        try:
            logger.info("[Offsets] Синхронизация сетевых структур с авто-дампером a2x...")
            if not updater.fetch_offsets():
                logger.warning("[Offsets] Не удалось обновить оффсеты через сеть. Софт задействует локальный кэш.")
        except Exception as e:
            logger.error(f"[Offsets] Ошибка при инициализации смещений дампера: {e}")

    threading.Thread(target=prefetch_offsets, daemon=True).start()

    logger.info("Запуск графического интерфейса пользователя...")

    exit_code = 0
    window = None

    try:
        # 4. Инициализация и запуск основного окна customtkinter
        window = MainWindow()
        logger.debug("Главное окно GUI успешно создано")
        window.run()
        logger.debug("Основной поток приложения завершил работу без ошибок")
    except KeyboardInterrupt:
        logger.info("Работа приложения прервана пользователем (Ctrl+C)")
        exit_code = 0  
    except ImportError as e:
        logger.exception("Критическая ошибка импорта модулей. Убедитесь, что все зависимости (pymem, pyMeow, customtkinter, orjson, watchdog, pynput) установлены.")
        exit_code = 2
    except Exception as e:
        logger.exception("Непредвиденное исключение в главном цикле приложения.")
        exit_code = 1
    finally:
        # 5. Гарантированная выгрузка занятых ресурсов памяти и потоков
        if window and hasattr(window, 'cleanup'):
            try:
                logger.debug("Очистка занятых потоков функций и закрытие Overlay...")
                window.cleanup()
            except Exception as cleanup_error:
                logger.warning("Ошибка при закрытии ресурсов окна: %s", cleanup_error)
        
        logger.debug("Программа My Project полностью закрыта")
        
        # Сохраняем буфер логов на диск перед выходом
        try:
            Logger.shutdown()
        except Exception:
            pass  

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
