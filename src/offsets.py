import os
import json
import threading
import requests

from classes.config_manager import ConfigManager

class OffsetManager:
    def __init__(self, source_name="a2x", config_path="sources.json"):
        self.source_name = source_name
        self.config_path = config_path
        
        # Ссылки на репозиторий дампера a2x
        self.urls = {
            "offsets": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json",
            "client": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json",
            "buttons": "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/buttons.json"
        }
        
        self.offsets = {}
        self.client = {}
        self.buttons = {}
        self._fetch_lock = threading.Lock()
        self._load_urls_from_config()

    def _load_urls_from_config(self):
        """Загружает ссылки на репозитории из файла конфигурации источников."""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            if self.source_name in config_data:
                src = config_data[self.source_name]
                self.urls["offsets"] = src["offsets_url"]
                self.urls["client"] = src["client_dll_url"]
                self.urls["buttons"] = src["buttons_url"]
        except Exception:
            pass
    def fetch_offsets(self) -> bool:
        """Потокобезопасная загрузка: prefetch из main.py и старт клиента
        могут запросить оффсеты одновременно."""
        with self._fetch_lock:
            if self.offsets and self.client:
                return True
            return self._fetch_offsets_locked()

    def _fetch_offsets_locked(self) -> bool:
        """Скачивает актуальные оффсеты и принудительно сохраняет их в папку AppData."""
        try:
            print("[Offsets] Загрузка актуальных смещений с серверов дампера...")
            r_off = requests.get(self.urls["offsets"], timeout=10)
            r_cli = requests.get(self.urls["client"], timeout=10)
            r_but = requests.get(self.urls["buttons"], timeout=10)

            if r_off.status_code == 200 and r_cli.status_code == 200 and r_but.status_code == 200:
                self.offsets = r_off.json()
                self.client = r_cli.json()
                self.buttons = r_but.json()
                
                # Папка хранения — та же, что и у конфигурации приложения
                appdata_target_dir = ConfigManager.OFFSETS_DIRECTORY
                
                # Гарантируем, что вся цепочка папок создана в системе
                os.makedirs(appdata_target_dir, exist_ok=True)
                
                # Записываем три файла на жесткий диск
                with open(os.path.join(appdata_target_dir, "offsets.json"), "w", encoding="utf-8") as f:
                    json.dump(self.offsets, f, indent=2)
                with open(os.path.join(appdata_target_dir, "client_dll.json"), "w", encoding="utf-8") as f:
                    json.dump(self.client, f, indent=2)
                with open(os.path.join(appdata_target_dir, "buttons.json"), "w", encoding="utf-8") as f:
                    json.dump(self.buttons, f, indent=2)
                    
                print(f"[Offsets] Файлы успешно скачаны и сохранены в: {appdata_target_dir}")
                return True
            else:
                print(f"[Offsets] Ошибка серверов GitHub. Коды: {r_off.status_code}, {r_cli.status_code}, {r_but.status_code}")
                return self.load_cached_offsets()
        except Exception as e:
            print(f"[Offsets] Критическая ошибка при сохранении смещений в AppData: {e}")
            return self.load_cached_offsets()

    def load_cached_offsets(self) -> bool:
        """Загружает ранее сохранённые оффсеты из AppData (работа без сети)."""
        cache_dir = ConfigManager.OFFSETS_DIRECTORY
        try:
            with open(os.path.join(cache_dir, "offsets.json"), "r", encoding="utf-8") as f:
                self.offsets = json.load(f)
            with open(os.path.join(cache_dir, "client_dll.json"), "r", encoding="utf-8") as f:
                self.client = json.load(f)
            with open(os.path.join(cache_dir, "buttons.json"), "r", encoding="utf-8") as f:
                self.buttons = json.load(f)
            if self.offsets and self.client:
                print(f"[Offsets] Сеть недоступна — использован локальный кэш: {cache_dir}")
                return True
        except Exception as e:
            print(f"[Offsets] Локальный кэш смещений недоступен: {e}")
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
