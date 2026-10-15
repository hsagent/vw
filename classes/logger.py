import os
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Optional, List
import sys
import threading

@dataclass
class LoggerConfig:
    """Configuration for the Logger class."""
    log_directory: str = os.path.expanduser(r'~\AppData\Local\NewProjectName\logs')
    max_bytes: int = 5 * 1024 * 1024  # 5MB
    backup_count: int = 5
    clear_on_startup: bool = False     # ИСПРАВЛЕНИЕ: Переводим в False, чтобы не затирать логи крашей прошлых сессий игры!
    console_level: int = logging.INFO
    file_level: int = logging.INFO
    detailed_level: int = logging.DEBUG
    suppress_patterns: List[str] = None
    
    def __post_init__(self):
        """Initialize default suppress patterns if none provided."""
        if self.suppress_patterns is None:
            self.suppress_patterns = [
                "Error drawing entity: 'NoneType' object is not subscriptable",
                "Could not read memory at"  # Подавляем спам при сворачивании игры
            ]

class SuppressErrorFilter(logging.Filter):
    """A logging filter to suppress messages containing specific patterns."""
    def __init__(self, patterns: List[str]):
        super().__init__()
        self.patterns = patterns or []
    
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(pattern in message for pattern in self.patterns)

class Logger:
    """
    A thread-safe singleton logger for the application.
    Features standard, detailed (debug) logging and active thread tracking.
    """
    _config: Optional[LoggerConfig] = None
    _logger_configured: bool = False
    _lock: threading.Lock = threading.Lock()
    
    @classmethod
    def LOG_DIRECTORY(cls) -> str:
        return cls._config.log_directory if cls._config else LoggerConfig().log_directory
    
    @classmethod
    def LOG_FILE(cls) -> str:
        log_dir = cls._config.log_directory if cls._config else LoggerConfig().log_directory
        return os.path.join(log_dir, 'violetwing.log')
    
    @classmethod
    def DETAILED_LOG_FILE(cls) -> str:
        log_dir = cls._config.log_directory if cls._config else LoggerConfig().log_directory
        return os.path.join(log_dir, 'NewProjectName_detailed.log')
    
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
                print(f"Warning: Could not clear log file {log_file}: {e}", file=sys.stderr)
    
    @staticmethod
    def _create_log_directory(directory: str) -> bool:
        try:
            os.makedirs(directory, exist_ok=True)
            return True
        except Exception as e:
            print(f"Error: Could not create log directory {directory}: {e}", file=sys.stderr)
            return False
    
    @staticmethod
    def _create_file_handler(
        log_file: str,
        level: int,
        formatter: logging.Formatter,
        max_bytes: int,
        backup_count: int
    ) -> Optional[RotatingFileHandler]:
        try:
            handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            handler.setLevel(level)
            handler.setFormatter(formatter)
            handler.delay = True  # ИСПРАВЛЕНИЕ: Откладывает открытие файла до первой записи (Фикс блокировок Windows)
            return handler
        except Exception as e:
            print(f"Error: Could not create file handler for {log_file}: {e}", file=sys.stderr)
            return None
    
    @staticmethod
    def setup_logging(config: Optional[LoggerConfig] = None) -> None:
        """Configure logging for the application with rotating file handlers safely."""
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
            Logger._clear_existing_logs([Logger.LOG_FILE(), Logger.DETAILED_LOG_FILE()], cfg.backup_count)
        
        # ИСПРАВЛЕНИЕ: Добавлен вывод имени потока [%(threadName)s] и точный формат времени
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s [%(threadName)s] %(levelname)-8s %(name)s -> %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 1. Основной хэндлер логов (NewProjectName.log)
        standard_handler = Logger._create_file_handler(
            Logger.LOG_FILE(), cfg.file_level, detailed_formatter, cfg.max_bytes, cfg.backup_count
        )
        if standard_handler:
            # Применяем фильтр подавления мусорных ошибок ESP
            standard_handler.addFilter(SuppressErrorFilter(cfg.suppress_patterns))
            root_logger.addHandler(standard_handler)
            
        # 2. Подробный хэндлер логов для дебага памяти (violetwing_detailed.log)
        detailed_handler = Logger._create_file_handler(
            Logger.DETAILED_LOG_FILE(), cfg.detailed_level, detailed_formatter, cfg.max_bytes, cfg.backup_count
        )
        if detailed_handler:
            root_logger.addHandler(detailed_handler)
            
        # 3. Консольный хэндлер (вывод в терминал/CMD)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(cfg.console_level)
        console_handler.setFormatter(detailed_formatter)
        console_handler.addFilter(SuppressErrorFilter(cfg.suppress_patterns))
        root_logger.addHandler(console_handler)
        
        logging.getLogger(__name__).info("NewProjectName sub-logging systems initialized successfully.")

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """Thread-safe factory method to get named logger instances."""
        if not Logger._logger_configured:
            Logger.setup_logging()
        return logging.getLogger(name)

    @staticmethod
    def shutdown() -> None:
        """Flushes and closes all active file streams cleanly."""
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
        root_logger.handlers.clear()
        Logger._logger_configured = False
