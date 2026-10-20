import pymem
import pymem.process
import struct
import time
from typing import Dict, Any, Optional

from classes.logger import Logger
from src.offsets import updater

logger = Logger.get_logger(__name__)

# Константы для работы с entity handles
ENTITY_INDEX_MASK = 0x7FFF  # Маска для извлечения индекса из handle
ENTITY_CHUNK_SHIFT = 9  # Сдвиг для вычисления chunk index
ENTITY_CHUNK_SIZE = 0x1FF  # Размер chunk для entity list

class MemoryManager:
    def __init__(self, offsets: dict = None, client_data: dict = None, buttons_data: dict = None) -> None:
        self.pm = None
        self.client_base = None
        self.ent_list = None
        self.dwEntityList = None
        self.dwLocalPlayerPawn = None
        self.dwLocalPlayerController = None
        self.dwViewMatrix = None
        self.dwForceJump = None
        self.m_iHealth = None
        self.m_iTeamNum = None
        self.m_iPawnHealth = None
        self.m_bPawnIsAlive = None
        self.m_iIDEntIndex = None
        self.m_iszPlayerName = None
        self.m_vOldOrigin = None
        self.m_pGameSceneNode = None
        self.m_bDormant = None
        self.m_hPlayerPawn = None
        self.m_flFlashDuration = None
        self.m_pBoneArray = None
        self.m_AttributeManager = None
        self.m_iItemDefinitionIndex = None
        self.m_Item = None
        self.m_pWeaponServices = None
        self.m_hActiveWeapon = None
        self.m_nSubclassID = None
        self.m_szName = None
        self.m_fFlags = None
        # Размер одной записи entity list зависит от сборки CS2: 0x70 (112) на
        # текущей, 0x78 (120) на более старых. Определяется автоматически.
        self.entity_entry_size = 112
        self._stride_detected = False
        # Указатель на entity list меняется при смене карты — обновляем его
        # периодически, иначе ESP/триггер «умирают» после смены уровня.
        self._ent_list_ts = 0.0
        # Кэш для weapon type (оружие меняется редко, не нужно читать каждый кадр)
        self._weapon_cache = {"name": "", "type": "", "timestamp": 0.0}
        self._weapon_cache_ttl = 0.5  # Время жизни кэша в секундах

    def initialize(self) -> bool:
        if not updater.offsets:
            if not updater.fetch_offsets():
                logger.error("Не удалось получить актуальные оффсеты.")
                return False
        if not self.initialize_pymem() or not self.get_client_module():
            return False
        self.load_offsets()
        if self.dwEntityList == 0:
            logger.error("Критическая ошибка: dwEntityList равен 0.")
            return False
        self.ent_list = self.read_longlong(self.client_base + self.dwEntityList)
        self._ent_list_ts = time.monotonic()
        if not self._stride_detected:
            self.detect_entity_entry_size()
            self._stride_detected = True
        return True

    def initialize_pymem(self) -> bool:
        try:
            self.pm = pymem.Pymem("cs2.exe")
            logger.debug("Успешно подключено к cs2.exe.")
            return True
        except pymem.exception.ProcessNotFound:
            logger.error("Процесс cs2.exe не найден. Запустите игру перед стартом.")
            return False
        except Exception as e:
            logger.error(f"Ошибка подключения: {e}")
            return False

    def get_client_module(self) -> bool:
        try:
            client_module = pymem.process.module_from_name(self.pm.process_handle, "client.dll")
            self.client_base = client_module.lpBaseOfDll
            logger.debug(f"client.dll найден: {hex(self.client_base)}")
            return True
        except Exception as e:
            logger.error(f"Модуль client.dll не найден: {e}")
            return False

    def load_offsets(self) -> None:
        logger.info("[Memory] Синхронизация смещений со структурами CS2...")
        self.dwEntityList = updater.get_offset("client.dll", "dwEntityList")
        self.dwLocalPlayerPawn = updater.get_offset("client.dll", "dwLocalPlayerPawn")
        self.dwLocalPlayerController = updater.get_offset("client.dll", "dwLocalPlayerController")
        self.dwViewMatrix = updater.get_offset("client.dll", "dwViewMatrix")
        # Кнопка +jump из buttons.json (не указатель, а значение в client.dll)
        self.dwForceJump = updater.get_button("jump")
        
        # Имена классов — как в актуальном дампе a2x. Старые CCSPlayerPawnBase /
        # CPlayerWeaponServices в client_dll.json больше не существуют, из-за чего
        # get_netvar() молча возвращал 0 и подставлялись устаревшие fallback-смещения.
        self.m_iHealth = updater.get_netvar("C_BaseEntity", "m_iHealth") or 0x34C
        self.m_iTeamNum = updater.get_netvar("C_BaseEntity", "m_iTeamNum") or 0x3E7
        # Данные на контроллере: живы ли и сколько HP у пешки (полезно для dormant)
        self.m_iPawnHealth = updater.get_netvar("CCSPlayerController", "m_iPawnHealth") or 0x938
        self.m_bPawnIsAlive = updater.get_netvar("CCSPlayerController", "m_bPawnIsAlive") or 0x934
        self.m_vOldOrigin = (
            updater.get_netvar("C_BasePlayerPawn", "m_vOldOrigin")
            or updater.get_netvar("C_BaseEntity", "m_vOldOrigin")
            or 0x14A4
        )
        self.m_fFlags = (
            updater.get_netvar("C_BaseEntity", "m_fFlags")
            or updater.get_netvar("C_CSPlayerPawnBase", "m_fFlags")
            or 0x3F4
        )
        self.m_iIDEntIndex = (
            updater.get_netvar("C_CSPlayerPawn", "m_iIDEntIndex")
            or updater.get_netvar("C_CSPlayerPawnBase", "m_iIDEntIndex")
            or 0x36DC
        )
        self.m_flFlashDuration = (
            updater.get_netvar("C_CSPlayerPawnBase", "m_flFlashDuration")
            or updater.get_netvar("C_CSPlayerPawn", "m_flFlashDuration")
            or 0x1510
        )
        self.m_iszPlayerName = updater.get_netvar("CBasePlayerController", "m_iszPlayerName") or 0x6FC
        self.m_hPlayerPawn = updater.get_netvar("CCSPlayerController", "m_hPlayerPawn") or 0x92C
        self.m_pGameSceneNode = updater.get_netvar("C_BaseEntity", "m_pGameSceneNode") or 0x330
        self.m_bDormant = updater.get_netvar("CGameSceneNode", "m_bDormant") or 0x103
        self.m_pBoneArray = (updater.get_netvar("CSkeletonInstance", "m_modelState") or 0x140) + 0x80

        self.m_pWeaponServices = updater.get_netvar("C_BasePlayerPawn", "m_pWeaponServices") or 0x12F0
        self.m_hActiveWeapon = (
            updater.get_netvar("CPlayer_WeaponServices", "m_hActiveWeapon")
            or updater.get_netvar("CPlayerWeaponServices", "m_hActiveWeapon")
            or 0x60
        )
        # Цепочка имя_оружия: weapon -> +m_nSubclassID+8 -> VData -> +m_szName
        self.m_nSubclassID = updater.get_netvar("C_BaseEntity", "m_nSubclassID") or 0x380
        self.m_szName = updater.get_netvar("CCSWeaponBaseVData", "m_szName") or 0x720
        self.m_AttributeManager = updater.get_netvar("C_EconEntity", "m_AttributeManager") or 0x1290
        self.m_Item = updater.get_netvar("C_AttributeContainer", "m_Item") or 0x50
        self.m_iItemDefinitionIndex = updater.get_netvar("C_EconItemView", "m_iItemDefinitionIndex") or 0x1BA

        logger.debug(
            "[Memory] offsets: origin=%#x idEnt=%#x flags=%#x flash=%#x boneArray=%#x",
            self.m_vOldOrigin, self.m_iIDEntIndex, self.m_fFlags,
            self.m_flFlashDuration, self.m_pBoneArray,
        )

    def _ensure_ent_list(self) -> None:
        """Обновляет указатель entity list не чаще раза в 2 секунды."""
        now = time.monotonic()
        if not self.ent_list or now - self._ent_list_ts > 2.0:
            self.ent_list = self.read_longlong(self.client_base + self.dwEntityList)
            self._ent_list_ts = now

    def _read_entity_raw(self, index: int, entry_size: int) -> int:
        """Чтение указателя сущности с явно заданным размером записи."""
        chunk = self.read_longlong(self.ent_list + 8 * ((index & ENTITY_INDEX_MASK) >> ENTITY_CHUNK_SHIFT) + 0x10)
        if not chunk:
            return 0
        return self.read_longlong(chunk + entry_size * (index & ENTITY_CHUNK_SIZE))

    def detect_entity_entry_size(self) -> int:
        """Определяет размер записи entity list (112 или 120) по живым игрокам.

        В разных сборках CS2 структура записи отличается (0x70 / 0x78). При
        неверном размере чтение попадает в середину соседней записи и ESP
        находит только часть игроков или не находит никого.
        """
        best_size = self.entity_entry_size
        best_score = -1
        self._ensure_ent_list()

        # Порог для досрочной остановки - если найдено достаточно игроков
        EARLY_EXIT_THRESHOLD = 5

        for entry_size in (112, 120, 128):
            score = 0
            for index in range(1, 65):
                try:
                    controller = self._read_entity_raw(index, entry_size)
                    if not controller:
                        continue
                    name = self.read_string(controller + self.m_iszPlayerName, 24)
                    if not name or not name.isprintable():
                        continue
                    handle = self.read_int(controller + self.m_hPlayerPawn)
                    if not handle:
                        continue
                    pawn = self._read_entity_raw(handle & ENTITY_INDEX_MASK, entry_size)
                    if not pawn:
                        continue
                    if (
                        self.read_int(pawn + self.m_iTeamNum) in (2, 3)
                        and 0 < self.read_int(pawn + self.m_iHealth) <= 100
                    ):
                        score += 1
                        # Досрочный выход если нашли достаточно игроков
                        if score >= EARLY_EXIT_THRESHOLD:
                            break
                except Exception:
                    continue
            if score > best_score:
                best_size, best_score = entry_size, score
                # Если нашли достаточно игроков, не проверяем остальные размеры
                if best_score >= EARLY_EXIT_THRESHOLD:
                    break

        if best_score > 0:
            if best_size != self.entity_entry_size:
                logger.info(
                    f"[Memory] Размер записи entity list: {best_size} "
                    f"(был {self.entity_entry_size}, найдено игроков: {best_score})"
                )
            self.entity_entry_size = best_size
        return self.entity_entry_size

    def get_entity(self, index: int):
        """Возвращает указатель сущности по её индексу (chunked entity list CS2)."""
        try:
            self._ensure_ent_list()
            if not self.ent_list:
                return None
            return self._read_entity_raw(index, self.entity_entry_size)
        except Exception:
            return None

    def get_fire_logic_data(self) -> dict | None:
        """Данные о сущности под прицелом.

        m_iIDEntIndex содержит ИНДЕКС ПЕШКИ (не контроллера): движок кладёт туда
        entity index из трейса прицела. Поэтому get_entity(entity_id) сразу даёт
        нужный pawn — читать у него m_hPlayerPawn не нужно.
        """
        try:
            player = self.read_longlong(self.client_base + self.dwLocalPlayerPawn)
            if not player:
                return None

            entity_id = self.read_int(player + self.m_iIDEntIndex)
            if entity_id <= 0:  # -1 / 0 = цели под прицелом нет
                return None

            entity_pawn = self.get_entity(entity_id)
            if not entity_pawn:
                return None

            entity_health = self.read_int(entity_pawn + self.m_iHealth)
            # На случай сборок, где m_iIDEntIndex хранит индекс контроллера:
            # у пешки m_hPlayerPawn == 0, поэтому fallback безопасен.
            if not (0 < entity_health <= 100):
                pawn_handle = self.read_int(entity_pawn + self.m_hPlayerPawn)
                if not pawn_handle:
                    return None
                entity_pawn = self.get_entity(pawn_handle & ENTITY_INDEX_MASK)
                if not entity_pawn:
                    return None
                entity_health = self.read_int(entity_pawn + self.m_iHealth)

            if not (0 < entity_health <= 100):
                return None

            return {
                "entity_index": entity_id,
                "entity_team": self.read_int(entity_pawn + self.m_iTeamNum),
                "player_team": self.read_int(player + self.m_iTeamNum),
                "entity_health": entity_health,
                "weapon_type": self.get_weapon_type(),
            }
        except Exception:
            return None

    def get_crosshair_entity_index(self) -> int:
        """Сырое значение m_iIDEntIndex (-1, если цели нет)."""
        try:
            player = self.read_longlong(self.client_base + self.dwLocalPlayerPawn)
            if not player:
                return -1
            return self.read_int(player + self.m_iIDEntIndex)
        except Exception:
            return -1

    def get_weapon_name(self) -> str:
        """Имя активного оружия, например 'weapon_ak47' ('' если недоступно)."""
        try:
            # Проверяем кэш
            now = time.monotonic()
            if self._weapon_cache["name"] and (now - self._weapon_cache["timestamp"]) < self._weapon_cache_ttl:
                return self._weapon_cache["name"]

            player = self.read_longlong(self.client_base + self.dwLocalPlayerPawn)
            if not player:
                return ""
            services = self.read_longlong(player + self.m_pWeaponServices)
            if not services:
                return ""
            handle = self.read_int(services + self.m_hActiveWeapon)
            if not handle or handle == 0xFFFFFFFF:
                return ""
            weapon = self.get_entity(handle & ENTITY_INDEX_MASK)
            if not weapon:
                return ""
            vdata = self.read_longlong(weapon + self.m_nSubclassID + 8)
            if not vdata:
                return ""
            name_ptr = self.read_longlong(vdata + self.m_szName)
            if not name_ptr:
                return ""
            name = self.read_string(name_ptr, 64)

            # Обновляем кэш
            self._weapon_cache["name"] = name
            self._weapon_cache["timestamp"] = now
            return name
        except Exception:
            return ""

    # Категории совпадают с ключами Trigger.WeaponSettings в конфиге
    WEAPON_TYPES = {
        "awp": "Snipers", "ssg08": "Snipers", "scar20": "Snipers", "g3sg1": "Snipers",
        "ak47": "Rifles", "m4a1": "Rifles", "m4a1_silencer": "Rifles",
        "galilar": "Rifles", "famas": "Rifles", "aug": "Rifles", "sg556": "Rifles",
        "mac10": "SMGs", "mp9": "SMGs", "mp7": "SMGs", "mp5sd": "SMGs",
        "p90": "SMGs", "bizon": "SMGs", "ump45": "SMGs",
        "deagle": "Pistols", "elite": "Pistols", "fiveseven": "Pistols",
        "glock": "Pistols", "hkp2000": "Pistols", "usp_silencer": "Pistols",
        "p250": "Pistols", "cz75a": "Pistols", "tec9": "Pistols", "revolver": "Pistols",
        "nova": "Heavy", "xm1014": "Heavy", "mag7": "Heavy", "sawedoff": "Heavy",
        "m249": "Heavy", "negev": "Heavy",
    }

    def get_weapon_type(self) -> str:
        """Категория активного оружия ('Pistols'/'Rifles'/'Snipers'/'SMGs'/'Heavy')."""
        try:
            # Проверяем кэш
            now = time.monotonic()
            if self._weapon_cache["type"] and (now - self._weapon_cache["timestamp"]) < self._weapon_cache_ttl:
                return self._weapon_cache["type"]

            name = self.get_weapon_name().lower()
            if not name:
                return ""
            if name.startswith("weapon_"):
                name = name[7:]
            weapon_type = self.WEAPON_TYPES.get(name, "")

            # Обновляем кэш
            self._weapon_cache["type"] = weapon_type
            return weapon_type
        except Exception:
            return ""

    def write_float(self, address: int, value: float) -> None:
        if not self.pm:
            return
        try:
            self.pm.write_float(address, value)
        except Exception:
            pass

    def write_int(self, address: int, value: int) -> bool:
        if not self.pm:
            return False
        try:
            self.pm.write_int(address, value)
            return True
        except Exception:
            return False

    def read_vec3(self, address: int) -> dict:
        if not self.pm:
            return {"x": 0.0, "y": 0.0, "z": 0.0}
        try:
            return {"x": self.pm.read_float(address), "y": self.pm.read_float(address + 4), "z": self.pm.read_float(address + 8)}
        except Exception:
            return {"x": 0.0, "y": 0.0, "z": 0.0}

    def read_string(self, address: int, max_length: int = 256) -> str:
        if not self.pm or address == 0:
            return ""
        try:
            return self.pm.read_bytes(address, max_length).split(b"\x00")[0].decode("utf-8", errors="replace")
        except Exception:
            return ""

    def read_floats(self, address: int, count: int) -> list:
        if not self.pm:
            return []
        try:
            return list(struct.unpack(f"{count}f", self.pm.read_bytes(address, count * 4)))
        except Exception:
            return []

    def read_int(self, address: int) -> int:
        if not self.pm:
            return 0
        try:
            return self.pm.read_int(address)
        except Exception:
            return 0

    def read_longlong(self, address: int) -> int:
        if not self.pm:
            return 0
        try:
            return self.pm.read_longlong(address)
        except Exception:
            return 0

    @property
    def client_dll_base(self) -> int: 
        return self.client_base
