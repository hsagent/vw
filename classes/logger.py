import os
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Optional, List
import sys
import threading

@dataclass
class LoggerConfig:
    """Конфигурация для системы логирования My Project."""
    log_directory: str = os.path.expanduser(r'~\AppData\Local\My Project\logs')
    max_bytes: int = 5 * 1024 * 1024  # 5MB
    backup_count: int = 3             # Уменьшено до 3 для экономии места
    clear_on_startup: bool = True
    console_level: int = logging.INFO
    file_level: int = logging.INFO
    detailed_level: int = logging.DEBUG
    suppress_patterns: List[str] = None
    
    def __post_init__(self):
        """Инициализирует паттерны фильтрации мусора памяти CS2, чтобы не проседал FPS."""
        if self.suppress_patterns is None:
            self.suppress_patterns = [
                "Could not read memory at",          # Пропуски чтения при перезапуске раунда
                "Failed to read int at address",     # Ошибки пустых указателей (смена карты)
                "Failed to read longlong",           # Штатные промахи EntityList
                "Error drawing entity",              # Ошибки отрисовки мертвых игроков
                "is not subscriptable",              # Старые ошибки разбора
                # Русскоязычные аналоги — иначе спам от циклов функций
                "Ошибка отрисовки сущности",
                "Ошибка в основном цикле оверлея pyMeow",
                "Ошибка в цикле TriggerBot",
                "Ошибка в цикле Bunnyhop",
                "Ошибка в цикле NoFlash",
                "Непредвиденная ошибка в цикле NoFlash",
            ]

class SuppressErrorFilter(logging.Filter):
    """Фильтр для предотвращения записи цикличных ошибок чтения памяти в логи."""
    def __init__(self, patterns: List[str]):
        super().__init__()
        self.patterns = patterns or []
    
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # Если сообщение содержит хоть один мусорный паттерн — блокируем его запись
        return not any(pattern in message for pattern in self.patterns)
class Logger:
    """Потокобезопасный синглтон-логгер для внешнего софта CS2."""
    _config: Optional[LoggerConfig] = None
    _logger: Optional[logging.Logger] = None
    _logger_configured: bool = False
    _lock: threading.Lock = threading.Lock()
    
    @classmethod
    def LOG_DIRECTORY(cls) -> str:
        return cls._config.log_directory if cls._config else LoggerConfig().log_directory
    
    @classmethod
    def LOG_FILE(cls) -> str:
        log_dir = cls._config.log_directory if cls._config else LoggerConfig().log_directory
        return os.path.join(log_dir, 'myproject.log')
    
    @classmethod
    def DETAILED_LOG_FILE(cls) -> str:
        log_dir = cls._config.log_directory if cls._config else LoggerConfig().log_directory
        return os.path.join(log_dir, 'myproject_detailed.log')
    
    @staticmethod
    def _clear_existing_logs(log_files: List[str], backup_count: int) -> None:
        for log_file in log_files:
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.truncate(0)
                    for i in range(1, backup_count + 1):
                        backup_file = f"{log_file}.{i}"
                        if os.path.exists(backup_file):
                            os.remove(backup_file)
            except (OSError, PermissionError) as e:
                print(f"Warning: Не удалось очистить лог {log_file}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Unexpected error: {e}", file=sys.stderr)
    
    @staticmethod
    def _create_log_directory(directory: str) -> bool:
        try:
            os.makedirs(directory, exist_ok=True)
            return True
        except Exception as e:
            print(f"Error: Ошибка создания папки логов {directory}: {e}", file=sys.stderr)
            return False
    
    @staticmethod
    def _create_file_handler(log_file: str, level: int, formatter: logging.Formatter, max_bytes: int, backup_count: int) -> Optional[RotatingFileHandler]:
        try:
            handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
            handler.setLevel(level)
            handler.setFormatter(formatter)
            return handler
        except Exception as e:
            print(f"Error: Ошибка создания хендлера для {log_file}: {e}", file=sys.stderr)
            return None
    
    @staticmethod
    def setup_logging(config: Optional[LoggerConfig] = None) -> None:
        """Потокобезопасная настройка системы логирования приложения."""
        with Logger._lock:
            if Logger._logger_configured:
                return
            Logger._logger_configured = True
            Logger._config = config or LoggerConfig()
            cfg = Logger._config
        
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.DEBUG)
        
        if not Logger._create_log_directory(cfg.log_directory):
            return
        
        if cfg.clear_on_startup:
            log_files = [Logger.LOG_FILE(), Logger.DETAILED_LOG_FILE()]
            Logger._clear_existing_logs(log_files, cfg.backup_count)
        
        standard_formatter = logging.Formatter(fmt='[%(asctime)s] [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        detailed_formatter = logging.Formatter(fmt='[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(threadName)s] [%(name)s:%(lineno)d] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        
        # Создаем общий фильтр подавления мусора
        suppress_filter = SuppressErrorFilter(cfg.suppress_patterns) if cfg.suppress_patterns else None
        
        # Стандартный лог-файл
        file_handler = Logger._create_file_handler(Logger.LOG_FILE(), cfg.file_level, standard_formatter, cfg.max_bytes, cfg.backup_count)
        if file_handler:
            if suppress_filter: file_handler.addFilter(suppress_filter)
            root_logger.addHandler(file_handler)
        
        # Подробный лог-файл
        detailed_handler = Logger._create_file_handler(Logger.DETAILED_LOG_FILE(), cfg.detailed_level, detailed_formatter, cfg.max_bytes, cfg.backup_count)
        if detailed_handler:
            if suppress_filter: detailed_handler.addFilter(suppress_filter)
            root_logger.addHandler(detailed_handler)
        
        # Вывод в консоль
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(cfg.console_level)
        stream_handler.setFormatter(standard_formatter)
        if suppress_filter: 
            stream_handler.addFilter(suppress_filter)
        root_logger.addHandler(stream_handler)
        
        logger = Logger.get_logger()
        logger.info("Система логирования успешно запущена и защищена от спама памяти.")
    
    @staticmethod
    def get_logger(name: Optional[str] = None) -> logging.Logger:
        if name:
            return logging.getLogger(name)
        if Logger._logger is None:
            with Logger._lock:
                if Logger._logger is None:
                    Logger._logger = logging.getLogger(__name__)
        return Logger._logger
    
    @staticmethod
    def shutdown() -> None:
        logger = Logger.get_logger()
        logger.info("Завершение работы системы логирования.")
        logging.shutdown()
    
    @staticmethod
    def clear_logs() -> None:
        cfg = Logger._config or LoggerConfig()
        log_files = [Logger.LOG_FILE(), Logger.DETAILED_LOG_FILE()]
        Logger._clear_existing_logs(log_files, cfg.backup_count)
        logger = Logger.get_logger()
        logger.info("Логи очищены вручную.")
