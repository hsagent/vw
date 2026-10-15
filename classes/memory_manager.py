import pymem
import pymem.process
import struct
from typing import Optional, Dict

from classes.logger import Logger
from classes.utility import Utility

# Initialize the logger for consistent logging
logger = Logger.get_logger(__name__)

class MemoryManager:
    def __init__(self, offsets: dict, client_data: dict, buttons_data: dict) -> None:
        """Initialize MemoryManager with offsets and client data."""
        self.offsets = offsets
        self.client_data = client_data
        self.buttons_data = buttons_data
        self.pm: Optional[pymem.Pymem] = None
        self.client_base: Optional[int] = None
        self.ent_list: Optional[int] = None  # Cache for entity list pointer
        self.config = None  # Configuration cache
        
        # Offset attributes
        self.dwEntityList = None
        self.dwLocalPlayerPawn = None
        self.dwLocalPlayerController = None
        self.dwViewMatrix = None
        self.m_iHealth = None
        self.m_iTeamNum = None
        self.m_iIDEntIndex = None
        self.m_iszPlayerName = None
        self.m_vOldOrigin = None
        self.m_pGameSceneNode = None
        self.m_bDormant = None
        self.m_hPlayerPawn = None
        self.m_flFlashDuration = None
        self.m_pBoneArray = None
        self.dwForceJump = None
        self.m_AttributeManager = None
        self.m_iItemDefinitionIndex = None
        self.m_Item = None
        self.m_pWeaponServices = None
        self.m_hActiveWeapon = None

    def initialize(self) -> bool:
        """
        Initialize memory access by attaching to the process and setting up necessary data.
        Returns True if successful, False otherwise.
        """
        if not self.initialize_pymem() or not self.get_client_module():
            return False
            
        self.load_offsets()
        if self.dwEntityList is None:  # Ensure offsets were loaded successfully
            return False
            
        try:
            self.ent_list = self.read_longlong(self.client_base + self.dwEntityList)
            return self.ent_list is not None and self.ent_list > 0
        except Exception as e:
            logger.error(f"Failed to read entity list root pointer: {e}")
            return False

    def initialize_pymem(self) -> bool:
        """Attach pymem to the game process."""
        try:
            self.pm = pymem.Pymem("cs2.exe")
            logger.debug("Successfully attached to cs2.exe process.")
            return True
        except pymem.exception.ProcessNotFound:
            logger.error("cs2.exe process not found. Ensure the game is running.")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while attaching to cs2.exe: {e}")
            return False

    def get_client_module(self) -> bool:
        """Retrieve the client.dll module base address."""
        try:
            client_module = pymem.process.module_from_name(self.pm.process_handle, "client.dll")
            self.client_base = client_module.lpBaseOfDll
            logger.debug("client.dll module found and base address retrieved.")
            return True
        except pymem.exception.ModuleNotFoundError:
            logger.error("client.dll not found. Ensure it is loaded.")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while retrieving client.dll module: {e}")
            return False

    def load_offsets(self) -> None:
        """Load memory offsets from Utility.extract_offsets."""
        extracted = Utility.extract_offsets(self.offsets, self.client_data, self.buttons_data)
        if extracted:
            self.dwEntityList = extracted["dwEntityList"]
            self.dwLocalPlayerPawn = extracted["dwLocalPlayerPawn"]
            self.dwLocalPlayerController = extracted["dwLocalPlayerController"]
            self.dwViewMatrix = extracted["dwViewMatrix"]
            self.dwForceJump = extracted["dwForceJump"]
            self.m_iHealth = extracted["m_iHealth"]
            self.m_iTeamNum = extracted["m_iTeamNum"]
            self.m_iIDEntIndex = extracted["m_iIDEntIndex"]
            self.m_iszPlayerName = extracted["m_iszPlayerName"]
            self.m_vOldOrigin = extracted["m_vOldOrigin"]
            self.m_pGameSceneNode = extracted["m_pGameSceneNode"]
            self.m_bDormant = extracted["m_bDormant"]
            self.m_hPlayerPawn = extracted["m_hPlayerPawn"]
            self.m_flFlashDuration = extracted["m_flFlashDuration"]
            self.m_pBoneArray = extracted["m_pBoneArray"]
            self.m_AttributeManager = extracted["m_AttributeManager"]
            self.m_iItemDefinitionIndex = extracted["m_iItemDefinitionIndex"]
            self.m_Item = extracted["m_Item"]
            self.m_pWeaponServices = extracted["m_pWeaponServices"]
            self.m_hActiveWeapon = extracted["m_hActiveWeapon"]
        else:
            logger.error("Failed to initialize offsets from extracted data.")

    # ==========================================
    # КРИТИЧЕСКИЕ МЕТОДЫ ЧТЕНИЯ И ЗАПИСИ ПАМЯТИ (RPM / WPM)
    # ==========================================
    def read_int(self, address: int) -> int:
        try:
            return self.pm.read_int(address)
        except Exception:
            return 0

    def read_longlong(self, address: int) -> int:
        try:
            return self.pm.read_longlong(address)
        except Exception:
            return 0

    def read_vec3(self, address: int) -> Dict[str, float]:
        try:
            data = self.pm.read_bytes(address, 12)
            x, y, z = struct.unpack('fff', data)
            return {"x": x, "y": y, "z": z}
        except Exception:
            return {"x": 0.0, "y": 0.0, "z": 0.0}

    def read_string(self, address: int, max_length: int = 128) -> str:
        try:
            # Читаем указатель на строку или саму строку в зависимости от контекста
            str_ptr = self.read_longlong(address)
            if not str_ptr:
                return ""
            return self.pm.read_string(str_ptr, max_length)
        except Exception:
            return ""

    def write_int(self, address: int, value: int) -> bool:
        try:
            self.pm.write_int(address, value)
            return True
        except Exception:
            return False

    # ==========================================
    # ИСПРАВЛЕННАЯ ЛОГИКА СДВИГОВ СУЩНОСТЕЙ
    # ==========================================
    def get_entity(self, index: int) -> Optional[int]:
        """Retrieve an entity from the entity list using Source 2 grid logic."""
        try:
            if not self.ent_list:
                return None
            list_offset = 0x8 * (index >> 9)
            ent_entry = self.read_longlong(self.ent_list + list_offset + 0x10)
            if not ent_entry:
                return None
            # Исправление: шаг сетки равен строго 120 байтам
            entity_offset = 120 * (index & 0x1FF)
            return self.read_longlong(ent_entry + entity_offset)
        except Exception as e:
            logger.debug(f"Error reading entity: {e}")
            return None

    def get_fire_logic_data(self) -> dict | None:
        """Retrieve data necessary for firing logic."""
        try:
            player = self.read_longlong(self.client_base + self.dwLocalPlayerPawn)
            if not player:
                return None
                
            entity_id = self.read_int(player + self.m_iIDEntIndex)

            if entity_id > 0:
                entity = self.get_entity(entity_id)
                if entity:
                    entity_team = self.read_int(entity + self.m_iTeamNum)
                    player_team = self.read_int(player + self.m_iTeamNum)
                    entity_health = self.read_int(entity + self.m_iHealth)
                    weapon_type = self.get_weapon_type()
                    return {
                        "entity_team": entity_team,
                        "player_team": player_team,
                        "entity_health": entity_health,
                        "weapon_type": weapon_type
                    }
            return None
        except Exception as e:
            logger.error(f"Error in fire logic: {e}")
            return None

    def get_weapon_type(self) -> str:
        """Get the type of the currently equipped weapon with fixed index math."""
        try:
            player = self.read_longlong(self.client_base + self.dwLocalPlayerPawn)
            if not player: return "Rifles"

            weapon_services_ptr = self.read_longlong(player + self.m_pWeaponServices)
            if not weapon_services_ptr: return "Rifles"

            weapon_handle = self.read_int(weapon_services_ptr + self.m_hActiveWeapon)
            if not weapon_handle or weapon_handle == -1: return "Rifles"

            weapon_id = weapon_handle & 0xFFFF
            list_entry = self.read_longlong(self.ent_list + 8 * ((weapon_id & 0x7FFF) >> 9) + 16)
            if not list_entry: return "Rifles"

            # Исправление: здесь шаг сетки также равен 120 байтам
            weapon_entity_ptr = self.read_longlong(list_entry + 120 * (weapon_id & 0x1FF))
            if not weapon_entity_ptr: return "Rifles"

            attribute_manager_ptr = self.read_longlong(weapon_entity_ptr + self.m_AttributeManager)
            if not attribute_manager_ptr: return "Rifles"

            item_ptr = self.read_longlong(attribute_manager_ptr + self.m_Item)
            if not item_ptr: return "Rifles"

            item_id = self.read_int(item_ptr + self.m_iItemDefinitionIndex)

            # Таблица маппинга ID предметов под категории конфигурации
            weapon_map = {
                1: "Pistols", 2: "Pistols", 3: "Pistols", 4: "Pistols", 30: "Pistols", 
                32: "Pistols", 36: "Pistols", 61: "Pistols", 63: "Pistols",
                7: "Snipers", 8: "Snipers", 40: "Snipers", 38: "Snipers",
