import os
import json
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from classes.config_manager import ConfigManager
from classes.logger import Logger

logger = Logger.get_logger(__name__)

OFFSET_SOURCES = {
    "a2x": {
        "name": "A2X Source", "author": "a2x", "repository": "a2x/cs2-dumper",
        "branch": "main", "offsets_path": "output/offsets.json",
        "offsets_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json",
        "client_dll_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json",
        "buttons_url": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/buttons.json",
    },
    "ivtim": {
        "name": "CS2 Dumper", "author": "ivtim", "repository": "ivtim/cs2-dumper",
        "branch": "main", "offsets_path": "output/offsets.json",
        "offsets_url": "https://raw.githubusercontent.com/ivtim/cs2-dumper/main/output/offsets.json",
        "client_dll_url": "https://raw.githubusercontent.com/ivtim/cs2-dumper/main/output/client_dll.json",
        "buttons_url": "https://raw.githubusercontent.com/ivtim/cs2-dumper/main/output/buttons.json",
    },
    "hanstxx": {
        "name": "CS2 Dumper", "author": "HansTxx", "repository": "HansTxx/cs2-dumper",
        "branch": "master", "offsets_path": "output/offsets.json",
        "offsets_url": "https://raw.githubusercontent.com/HansTxx/cs2-dumper/master/output/offsets.json",
        "client_dll_url": "https://raw.githubusercontent.com/HansTxx/cs2-dumper/master/output/client_dll.json",
        "buttons_url": "https://raw.githubusercontent.com/HansTxx/cs2-dumper/master/output/buttons.json",
    },
    "cesiumoq": {
        "name": "CS2 Dumper (raw, preview)", "author": "cesiumoq", "repository": "cesiumoq/cs2-dumper",
        "branch": "main", "offsets_path": "output/build-14195/raw/offsets.json",
        "offsets_url": "https://raw.githubusercontent.com/cesiumoq/cs2-dumper/main/output/build-14195/raw/offsets.json",
        "client_dll_url": "https://raw.githubusercontent.com/cesiumoq/cs2-dumper/main/output/build-14195/raw/client_dll.json",
        "buttons_url": "https://raw.githubusercontent.com/cesiumoq/cs2-dumper/main/output/build-14195/raw/buttons.json",
    },
}


class OffsetManager:
    def __init__(self, source_name="a2x", config_path="sources.json"):
        self.source_name = source_name
        self.config_path = config_path
        
        self.urls = {}
        
        self.offsets = {}
        self.client = {}
        self.buttons = {}
        self._loaded_source = None
        self._fetch_lock = threading.RLock()
        self._load_urls_from_config()

    def _load_urls_from_config(self):
        """Загружает ссылки на репозитории из файла конфигурации источников."""
        source = OFFSET_SOURCES.get(self.source_name, {})
        self.urls = {
            name: source[key]
            for name, key in (
                ("offsets", "offsets_url"),
                ("client", "client_dll_url"),
                ("buttons", "buttons_url"),
            )
            if key in source
        }
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            if self.source_name in config_data:
                src = config_data[self.source_name]
                urls = {
                    "offsets": src["offsets_url"],
                    "client": src["client_dll_url"],
                    "buttons": src["buttons_url"],
                }
                if all(isinstance(url, str) and url for url in urls.values()):
                    self.urls = urls
        except Exception:
            pass

    def _clear_snapshot(self):
        self.offsets, self.client, self.buttons = {}, {}, {}
        self._loaded_source = None

    def _cache_directory(self):
        if self.source_name not in OFFSET_SOURCES:
            raise ValueError("Unknown offset source")
        cache_dir = Path(ConfigManager.OFFSETS_DIRECTORY)
        return cache_dir if self.source_name == "a2x" else cache_dir / self.source_name

    def invalidate(self) -> None:
        """Помечает текущий снимок устаревшим после изменения GUI-настроек."""
        with self._fetch_lock:
            self._loaded_source = None

    def fetch_offsets(self) -> bool:
        """Загружает источник offsets, выбранный в конфигурации."""
        return self.load_configured_offsets()

    def _fetch_offsets_locked(self) -> bool:
        """Скачивает актуальные оффсеты и принудительно сохраняет их в папку AppData."""
        try:
            print(f"[Offsets] Загрузка смещений из источника {self.source_name}...")
            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(
                    lambda url: requests.get(url, timeout=10, verify=True),
                    (self.urls[name] for name in ("offsets", "client", "buttons"))
                ))
            if all(response.ok for response in responses):
                offsets, client, buttons = (response.json() for response in responses)
                if not self._validate_payloads(offsets, client, buttons):
                    raise ValueError("Некорректная структура JSON оффсетов")
                cache_dir = self._cache_directory()
                cache_dir.mkdir(parents=True, exist_ok=True)
                for filename, payload in (
                    ("offsets.json", offsets),
                    ("client_dll.json", client),
                    ("buttons.json", buttons),
                ):
                    with (cache_dir / filename).open("w", encoding="utf-8") as file:
                        json.dump(payload, file, indent=2)

                self.offsets, self.client, self.buttons = offsets, client, buttons
                self._loaded_source = self.source_name
                print(f"[Offsets] Файлы успешно скачаны и сохранены в: {cache_dir}")
                return True
            else:
                print(f"[Offsets] Ошибка серверов GitHub. Коды: {', '.join(str(r.status_code) for r in responses)}")
                return self.load_cached_offsets()
        except Exception as e:
            print(f"[Offsets] Критическая ошибка при сохранении смещений в AppData: {e}")
            return self.load_cached_offsets()

    @staticmethod
    def _validate_payloads(offsets, client, buttons) -> bool:
        offsets_data = offsets.get("client.dll", {}) if isinstance(offsets, dict) else {}
        required_offsets = {
            "dwEntityList",
            "dwLocalPlayerPawn",
            "dwLocalPlayerController",
            "dwViewMatrix",
        }
        client_data = client.get("client.dll", client) if isinstance(client, dict) else {}
        buttons_data = buttons.get("client.dll", buttons) if isinstance(buttons, dict) else {}
        return (
            isinstance(offsets_data, dict)
            and required_offsets.issubset(offsets_data)
            and all(isinstance(offsets_data[key], int) and offsets_data[key] > 0 for key in required_offsets)
            and isinstance(client_data, dict)
            and isinstance(client_data.get("classes"), dict)
            and bool(client_data["classes"])
            and isinstance(buttons_data, dict)
            and isinstance(buttons_data.get("jump"), int)
            and buttons_data["jump"] > 0
        )

    @staticmethod
    def _configured_local_paths(general_config):
        """Возвращает нормализованные пути локальных файлов из config.json."""
        defaults = {
            "offsets": Path(ConfigManager.OFFSETS_DIRECTORY) / "offsets.json",
            "client": Path(ConfigManager.OFFSETS_DIRECTORY) / "client_dll.json",
            "buttons": Path(ConfigManager.OFFSETS_DIRECTORY) / "buttons.json",
        }
        return {
            "offsets": Path(general_config.get("OffsetsFile") or defaults["offsets"]).expanduser(),
            "client": Path(general_config.get("ClientDLLFile") or defaults["client"]).expanduser(),
            "buttons": Path(general_config.get("ButtonsFile") or defaults["buttons"]).expanduser(),
        }

    def load_configured_offsets(self, force_reload: bool = False) -> bool:
        """Загружает источник, выбранный в General.OffsetSource."""
        with self._fetch_lock:
            config = ConfigManager.load_config()
            general = config.get("General", {})
            source = general.get("OffsetSource", self.source_name)

            if source == "local":
                if not force_reload and self._loaded_source == "local" and self.offsets and self.client and self.buttons:
                    return True
                return self._load_local_offsets_locked(general)

            if not isinstance(source, str) or source not in OFFSET_SOURCES:
                self._clear_snapshot()
                logger.error("[Offsets] Неизвестный источник: %s", source)
                return False

            if source != self.source_name:
                self.source_name = source
                self._load_urls_from_config()
            if self._loaded_source != source:
                self._clear_snapshot()

            if not force_reload and self._loaded_source == source and self.offsets and self.client and self.buttons:
                return True
            return self._fetch_offsets_locked()

    def _load_local_offsets_locked(self, general_config) -> bool:
        """Читает и проверяет три выбранных пользователем JSON-файла."""
        paths = self._configured_local_paths(general_config)
        try:
            missing = [str(path) for path in paths.values() if not path.is_file()]
            if missing:
                raise FileNotFoundError("Не найдены файлы: " + ", ".join(missing))

            payloads = {}
            for name, path in paths.items():
                with path.open("r", encoding="utf-8-sig") as file:
                    payloads[name] = json.load(file)

            if not self._validate_payloads(
                payloads["offsets"],
                payloads["client"],
                payloads["buttons"],
            ):
                raise ValueError("Некорректная структура файлов offsets/client_dll/buttons")

            self.offsets = payloads["offsets"]
            self.client = payloads["client"]
            self.buttons = payloads["buttons"]
            self._loaded_source = "local"
            logger.info(
                "[Offsets] Используются локальные файлы: %s; %s; %s",
                paths["offsets"],
                paths["client"],
                paths["buttons"],
            )
            return True
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self._clear_snapshot()
            logger.error("[Offsets] Не удалось загрузить локальные файлы: %s", e)
            return False

    def load_cached_offsets(self) -> bool:
        """Загружает ранее сохранённые оффсеты из AppData (работа без сети)."""
        with self._fetch_lock:
            try:
                cache_dir = self._cache_directory()
                payloads = []
                for filename in ("offsets.json", "client_dll.json", "buttons.json"):
                    with (cache_dir / filename).open("r", encoding="utf-8-sig") as file:
                        payloads.append(json.load(file))
                if self._validate_payloads(*payloads):
                    self.offsets, self.client, self.buttons = payloads
                    self._loaded_source = self.source_name
                    print(f"[Offsets] Сеть недоступна — использован локальный кэш: {cache_dir}")
                    return True
            except Exception as e:
                print(f"[Offsets] Локальный кэш смещений недоступен: {e}")
            self._clear_snapshot()
            return False
    def get_offset(self, module: str, name: str) -> int:
        """Получает базовый оффсет (например, dwEntityList)."""
        try:
            return self.offsets[module][name]
        except KeyError:
            print(f"[Offsets] Не найден базовый оффсет: {module} -> {name}")
            return 0

    def get_netvar(self, class_name: str, var_name: str) -> int:
        """Получает смещение сетевой переменной с авто-подбором префиксов класса."""
        try:
            client_data = self.client.get("client.dll", self.client)
            classes_node = client_data.get("classes", client_data)
            
            # Расширенный список вариантов мутаций классов в CS2
            variants = [class_name]
            if class_name.startswith("C_"):
                variants.extend([class_name[2:], "C" + class_name[2:], "CC" + class_name[2:]])
            elif class_name.startswith("CCS"):
                variants.extend(["C_CS" + class_name[3:], "CS" + class_name[3:]])
            elif class_name.startswith("C"):
                variants.extend(["C_" + class_name[1:], class_name[1:]])

            # Ищем совпадение в структуре JSON
            for name in variants:
                if name in classes_node:
                    class_info = classes_node[name]
                    if isinstance(class_info, dict):
                        fields_node = class_info.get("fields", class_info)
                        if isinstance(fields_node, dict) and var_name in fields_node:
                            return fields_node[var_name]
                        if var_name in class_info:
                            return class_info[var_name]
                            
        except Exception:
            pass
            
        return 0


    def get_button(self, button_name: str) -> int:
        """Получает смещение кнопки (например, jump или attack)."""
        try:
            return self.buttons["client.dll"][button_name]
        except KeyError:
            try:
                return self.buttons[button_name]
            except KeyError:
                print(f"[Offsets] Не найдена кнопка: {button_name}")
                return 0

# Экземпляр менеджера для использования в других файлах проекта
updater = OffsetManager(source_name="a2x", config_path="sources.json")
