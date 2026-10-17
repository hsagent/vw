import os
import threading
import time
import webbrowser
import subprocess
import platform
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk
import requests
import sys
import copy

from watchdog.observers import Observer

# Полностью обновленные и исправленные импорты под архитектуру CS2
from classes.updater import Updater
from classes.utility import Utility
from classes.triggerbot import CS2TriggerBot      
from classes.esp import CS2Overlay
from classes.bunnyhop import CS2Bunnyhop
from classes.noflash import CS2NoFlash
from classes.config_manager import ConfigManager, COLOR_CHOICES
from classes.config_handler import ConfigFileChangeHandler 
from classes.logger import Logger
from classes.memory_manager import MemoryManager
from classes.client_manager import ClientManager

from gui.home_tab import populate_dashboard
from gui.general_settings_tab import populate_general_settings
from gui.trigger_settings_tab import populate_trigger_settings
from gui.overlay_settings_tab import populate_overlay_settings
from gui.additional_settings_tab import populate_additional_settings
from gui.logs_tab import populate_logs
from gui.faq_tab import populate_faq
from gui.notifications_tab import populate_notifications
from gui.supporters_tab import populate_supporters
from gui.theme import (FONT_FAMILY_BOLD, FONT_FAMILY_REGULAR, FONT_SIZE_H2, FONT_SIZE_H4, FONT_SIZE_P,
                         COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_BACKGROUND, COLOR_WIDGET_BACKGROUND, COLOR_ACCENT_FG,
                         BUTTON_STYLE_PRIMARY, BUTTON_STYLE_DANGER)

# Настройка системного логгера
logger = Logger.get_logger(__name__)

class MainWindow:
    def __init__(self):
        """Инициализация главного окна приложения My Project под Counter-Strike 2."""
        self.repo_url = "https://github.com"
        self.trigger_thread = None
        self.overlay_thread = None
        self.bunnyhop_thread = None
        self.noflash_thread = None
        self.observer = None
        self.log_timer = None

        # Конфигурация темного интерфейса CustomTkinter
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()

        # Создаем экземпляр нашего нового отказоустойчивого MemoryManager
        self.memory_manager = MemoryManager()

        # Инициализируем реестр функций
        self.initialize_features()
        self.root.title("My Project - Source 2 Edition")
        self.root.resizable(True, True)
        self.root.minsize(1400, 800)

        # Выравнивание окна по центру экрана
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (1400 // 2)
        y = (self.root.winfo_screenheight() // 2) - (800 // 2)
        self.root.geometry(f"1400x800+{x}+{y}")
        
        try:
            self.root.iconbitmap(Utility.resource_path('src/img/icon.ico'))
        except Exception:
            pass
        
        # Подгрузка шрифтов Manrope и JetBrainsMono на Windows системах
        if platform.system() == "Windows":
            import ctypes
            gdi32 = ctypes.WinDLL('gdi32')
            font_files = [
                'src/fonts/Manrope-Regular.ttf',
                'src/fonts/Manrope-Bold.ttf',
                'src/fonts/JetBrainsMono-Regular.ttf',
                'src/fonts/JetBrainsMono-Bold.ttf'
            ]
            for font_file in font_files:
                font_path = Utility.resource_path(font_file)
                if os.path.exists(font_path):
                    gdi32.AddFontResourceW(font_path)
        
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        
        self.updater = Updater(self)
        self.client_manager = ClientManager(self)
        self.setup_ui()
        self.init_config_watcher()
        self.start_log_timer()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def initialize_features(self):
        """Создает экземпляры классов функций чита и регистрирует их."""
        try:
            self.triggerbot = CS2TriggerBot(self.memory_manager)
            self.overlay = CS2Overlay(self.memory_manager)
            self.bunnyhop = CS2Bunnyhop(self.memory_manager)
            self.noflash = CS2NoFlash(self.memory_manager)

            self.features = {
                "Trigger": {"name": "TriggerBot", "instance": self.triggerbot, "class": CS2TriggerBot},
                "Overlay": {"name": "Overlay", "instance": self.overlay, "class": CS2Overlay},
                "Bunnyhop": {"name": "Bunnyhop", "instance": self.bunnyhop, "class": CS2Bunnyhop},
                "Noflash": {"name": "Noflash", "instance": self.noflash, "class": CS2NoFlash},
            }
            logger.info("Все функции чита успешно проинициализированы.")
        except Exception:
            logger.exception("Не удалось инициализировать функциональные классы.")
            messagebox.showerror("Initialization Error", "Failed to initialize features. Check logs.")
    def setup_ui(self):
        """Setup the modern user interface components."""
        # Create a modern header with branding and controls
        self.create_modern_header()
        
        # Create the main content area including sidebar navigation
        self.create_main_content()

    def create_modern_header(self):
        """Create a sleek modern header with gradient-like appearance."""
        header_container = ctk.CTkFrame(self.root, height=80, corner_radius=0, fg_color=("#1a1a1a", "#0d1117"))
        header_container.grid(row=0, column=0, sticky="ew")
        header_container.grid_propagate(False)
        header_container.grid_columnconfigure(1, weight=1)

        self.create_header_left(header_container)
        self.create_header_right(header_container)

    def create_header_left(self, parent):
        """Create the left side of the header with title and version badge."""
        left_frame = ctk.CTkFrame(parent, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="w", padx=30, pady=15)
        
        # Title container
        title_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        title_frame.pack(side="left")
        
        # Title name
        ctk.CTkLabel(
            title_frame, 
            text="My", 
            font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H2, "bold"), 
            text_color=COLOR_ACCENT_FG[0]
        ).pack(side="left")
        
        ctk.CTkLabel(
            title_frame, 
            text="Project", 
            font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H2, "bold"), 
            text_color=COLOR_TEXT_PRIMARY[1]
        ).pack(side="left", padx=(5, 0))
        
        # Version badge
        version_badge = ctk.CTkFrame(
            left_frame,
            fg_color=("#f3e8ff", "#2d1b4e"),
            corner_radius=12,
            height=28
        )
        version_badge.pack(side="left", padx=(15, 0))
        
        ctk.CTkLabel(
            version_badge,
            text=f"{ConfigManager.VERSION}",
            font=(FONT_FAMILY_BOLD[0], 12, "bold"),
            text_color=COLOR_ACCENT_FG[0],
            padx=12,
            pady=4
        ).pack()

    def create_header_right(self, parent):
        """Create the right side of the header with status, social buttons, and update button."""
        right_frame = ctk.CTkFrame(parent, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e", padx=30, pady=15)
        
        self.create_status_indicator(right_frame)
        social_frame = self.create_social_buttons(right_frame)
        self.create_update_button(social_frame)

    def create_status_indicator(self, parent):
        """Create the status indicator widget."""
        self.status_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.status_frame.pack(side="right", padx=(20, 0))
        
        ctk.CTkFrame(self.status_frame, width=12, height=12, corner_radius=6, fg_color="#ef4444").pack(side="left", pady=(0, 2))
        self.status_label = ctk.CTkLabel(self.status_frame, text="Inactive", font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H4, "bold"), text_color=BUTTON_STYLE_DANGER["fg_color"][0])
        self.status_label.pack(side="left", padx=(8, 0))

    def create_social_buttons(self, parent):
        """Create and pack the social media buttons."""
        social_frame = ctk.CTkFrame(parent, fg_color="transparent")
        social_frame.pack(side="right")

        social_buttons_data = [
            {"text": "GitHub", "icon": "github", "url": "https://github.com", "fg_color": "#2c3e50", "hover_color": "#34495e", "border_color": "#34495e"},
            {"text": "Telegram", "icon": "telegram", "url": "https://t.me", "fg_color": "#29A9EA", "hover_color": "#279cdb"},
        ]

        for i, data in enumerate(social_buttons_data):
            try:
                image = Image.open(Utility.resource_path(f'src/img/{data["icon"]}_icon.png'))
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(24, 24))
            except Exception:
                ctk_image = None

            btn = ctk.CTkButton(
                social_frame,
                text=data["text"],
                image=ctk_image,
                compound="left",
                command=lambda u=data["url"]: webbrowser.open(u),
                height=32,
                corner_radius=16,
                fg_color=data["fg_color"],
                hover_color=data["hover_color"],
                border_width=1 if "border_color" in data else 0,
                border_color=data.get("border_color"),
                font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H4)
            )
            btn.pack(side="left", padx=(0, 8) if i < len(social_buttons_data) - 1 else (0, 0))
        
        return social_frame

    def create_update_button(self, parent):
        """Create the update button if an update is available."""
        try:
            image = Image.open(Utility.resource_path('src/img/update_icon.png'))
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(24, 24))
        except Exception:
            ctk_image = None

        if self.updater.check_for_updates():
            update_btn = ctk.CTkButton(
                parent,
                text="Pre-release Available!" if self.updater.is_prerelease else "Update Available!",
                image=ctk_image,
                command=self.updater.handle_update,
                width=120,
                height=32,
                corner_radius=16,
                fg_color="#ef4444" if not self.updater.is_prerelease else "#f59e0b",
                hover_color="#dc2626" if not self.updater.is_prerelease else "#d97706",
                font=("Chivo", 14)
            )
            update_btn.pack(side="left", padx=(8, 0))
    def create_main_content(self):
        """Create the main content area with a modern layout."""
        main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        main_container.grid(row=1, column=0, sticky="nsew")
        main_container.grid_columnconfigure(1, weight=1)
        main_container.grid_rowconfigure(0, weight=1)

        self.create_sidebar(main_container)

        self.content_frame = ctk.CTkFrame(main_container, corner_radius=0, fg_color=COLOR_BACKGROUND)
        self.content_frame.grid(row=0, column=1, sticky="nsew")

        self.tab_views = {
            "dashboard": self.populate_dashboard,
            "general_settings": self.populate_general_settings,
            "trigger_settings": self.populate_trigger_settings,
            "overlay_settings": self.populate_overlay_settings,
            "additional_settings": self.populate_additional_settings,
            "logs": self.populate_logs,
            "faq": self.populate_faq,
            "notifications": self.populate_notifications,
            "supporters": self.populate_supporters,
        }

        self.tab_frames = {}
        for key, populate_func in self.tab_views.items():
            frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
            self.tab_frames[key] = frame
            populate_func(frame)

        self.current_view = None
        self.switch_view("dashboard")

    def create_sidebar(self, parent):
        """Create modern sidebar navigation."""
        sidebar = ctk.CTkFrame(parent, width=280, corner_radius=0, fg_color=COLOR_BACKGROUND)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        self.nav_items = [
            ("Dashboard", "dashboard", "🏠"),
            ("General Settings", "general_settings", "⚙️"),
            ("Trigger Settings", "trigger_settings", "🔫"),
            ("Overlay Settings", "overlay_settings", "🌍"),
            ("Additional Settings", "additional_settings", "⚡"),
            ("Logs", "logs", "📋"),
            ("FAQ", "faq", "❓"),
            ("Notifications", "notifications", "🔔"),
            ("Supporters", "supporters", "🤝"),
        ]

        self.nav_buttons = {}
        ctk.CTkFrame(sidebar, height=30, fg_color="transparent").pack(fill="x")

        for name, key, icon in self.nav_items:
            btn = ctk.CTkButton(
                sidebar,
                text=f"{icon}  {name}",
                command=lambda k=key: self.switch_view(k),
                width=240,
                height=50,
                corner_radius=12,
                fg_color="transparent",
                hover_color=COLOR_WIDGET_BACKGROUND,
                text_color=COLOR_TEXT_SECONDARY,
                font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H4),
                anchor="w",
            )
            btn.pack(pady=(0, 8), padx=20, fill="x")
            self.nav_buttons[key] = btn

        self.set_active_nav("dashboard")

    def set_active_nav(self, active_key):
        """Set the active navigation button with visual feedback."""
        for key, btn in self.nav_buttons.items():
            if key == active_key:
                # Highlight the active button
                btn.configure(
                    fg_color=COLOR_ACCENT_FG,
                    text_color=COLOR_TEXT_PRIMARY
                )
            else:
                # Reset inactive buttons to default style
                btn.configure(
                    fg_color="transparent",
                    text_color=COLOR_TEXT_SECONDARY,
                    hover_color=COLOR_WIDGET_BACKGROUND
                )

    def switch_view(self, view_key):
        """Switch between different views by showing the appropriate frame."""
        if self.current_view == view_key:
            return

        if self.current_view and self.current_view in self.tab_frames:
            self.tab_frames[self.current_view].pack_forget()

        self.current_view = view_key
        self.set_active_nav(view_key)

        if view_key in self.tab_frames:
            self.tab_frames[view_key].pack(fill="both", expand=True)

    def populate_dashboard(self, frame):
        """Populate the dashboard frame with controls and stats."""
        populate_dashboard(self, frame)

    def populate_general_settings(self, frame):
        """Populate the general settings frame with configuration options."""
        populate_general_settings(self, frame)

    def populate_trigger_settings(self, frame):
        """Populate the trigger settings frame with configuration options."""
        populate_trigger_settings(self, frame)

    def populate_overlay_settings(self, frame):
        """Populate the overlay settings frame with configuration options."""
        populate_overlay_settings(self, frame)

    def populate_additional_settings(self, frame):
        """Populate the additional settings frame with configuration options for Bunnyhop and NoFlash."""
        populate_additional_settings(self, frame)

    def populate_logs(self, frame):
        """Populate the logs frame with log display."""
        populate_logs(self, frame)

    def populate_faq(self, frame):
        """Populate the FAQ frame with questions and answers."""
        populate_faq(self, frame)
    
    def populate_notifications(self, frame):
        """Populate the notifications frame with notification settings."""
        populate_notifications(self, frame)

    def populate_supporters(self, frame):
        """Populate the supporters frame with supporter data."""
        populate_supporters(self, frame)
    def update_client_status(self, status, color):
        """Обновляет текстовый статус чита и цвет индикатора."""
        self.status_label.configure(text=status, text_color=color)
        for w in self.status_frame.winfo_children():
            if isinstance(w, ctk.CTkFrame) and w.cget("width") == 12:
                w.configure(fg_color=color)
                break
        if hasattr(self, 'bot_status_label'):
            self.bot_status_label.configure(text=status, text_color=color)

    def start_client(self): self.client_manager.start_client()
    def stop_client(self): self.client_manager.stop_client()

    def update_weapon_settings_display(self):
        """Синхронизирует отображение задержек триггербота для выбранного типа оружия."""
        try:
            from classes.config_manager import ConfigManager
            
            # Получаем текущий выбранный в выпадающем списке тип оружия (например, 'Rifles')
            wt = self.active_weapon_type.get()
            
            # Безопасно загружаем всю структуру конфигурации
            full_config = ConfigManager.load_config()
            
            # Вытаскиваем специфичные задержки для этого оружия из правильного узла JSON
            trigger_settings = full_config.get('Trigger', {})
            weapon_settings = trigger_settings.get('WeaponSettings', {}).get(wt, {})

            # Заполняем текстовые поля ввода в GUI актуальными значениями
            for entry, key, default_val in [
                (getattr(self, 'min_delay_entry', None), 'ShotDelayMin', "0.01"),
                (getattr(self, 'max_delay_entry', None), 'ShotDelayMax', "0.05"),
                (getattr(self, 'post_shot_delay_entry', None), 'PostShotDelay', "0.1")
            ]:
                if entry is not None: 
                    val = weapon_settings.get(key, default_val)
                    entry.delete(0, "end")
                    entry.insert(0, str(val))
                    
        except Exception as e:
            logger.error(f"[GUI] Ошибка при обновлении отображения настроек оружия: {e}")

    def save_settings(self, show_message=False):
        """Сохраняет измененные в GUI настройки и применяет их в потоки."""
        try:
            self.validate_inputs()
            config = ConfigManager.load_config()
            old_config = config.copy()

            self.update_config_from_ui(config)
            ConfigManager.save_config(config, log_info=False)
            
            self.client_manager.apply_feature_state_changes(old_config, config)
            self.client_manager.update_running_feature_configs(config)

            if show_message: messagebox.showinfo("Saved", "Настройки сохранены!")
        except ValueError as e: messagebox.showerror("Invalid Input", str(e))
        except Exception: logger.exception("Ошибка сохранения настроек.")

    def update_config_from_ui(self, config):
        """Собирает значения из всех вкладок интерфейса."""
        g, t = config["General"], config["Trigger"]
        if hasattr(self, 'trigger_var'): g["Trigger"] = self.trigger_var.get()
        if hasattr(self, 'overlay_var'): g["Overlay"] = self.overlay_var.get()
        if hasattr(self, 'bunnyhop_var'): g["Bunnyhop"] = self.bunnyhop_var.get()
        if hasattr(self, 'noflash_var'): g["Noflash"] = self.noflash_var.get()
        
        if hasattr(self, 'trigger_key_entry'): t["TriggerKey"] = self.trigger_key_entry.get().strip()
        if hasattr(self, 'toggle_mode_var'): t["ToggleMode"] = self.toggle_mode_var.get()
        if hasattr(self, 'attack_teammates_var'): t["AttackOnTeammates"] = self.attack_teammates_var.get()

        if hasattr(self, 'active_weapon_type'):
            wt = self.active_weapon_type.get(); t['active_weapon_type'] = wt
            ws = t['WeaponSettings'].get(wt, {})
            try:
                if hasattr(self, 'min_delay_entry'): ws['ShotDelayMin'] = float(self.min_delay_entry.get())
                if hasattr(self, 'max_delay_entry'): ws['ShotDelayMax'] = float(self.max_delay_entry.get())
                if hasattr(self, 'post_shot_delay_entry'): ws['PostShotDelay'] = float(self.post_shot_delay_entry.get())
            except ValueError: pass
            t['WeaponSettings'][wt] = ws

        bh, nf = config.get("Bunnyhop", {}), config.get("NoFlash", {})
        if hasattr(self, 'jump_key_entry'): bh["JumpKey"] = self.jump_key_entry.get().strip()
        try:
            if hasattr(self, 'jump_delay_entry'): bh["JumpDelay"] = float(self.jump_delay_entry.get())
        except ValueError: pass
        if hasattr(self, 'FlashSuppressionStrength_slider'): nf["FlashSuppressionStrength"] = self.FlashSuppressionStrength_slider.get()

        self.update_overlay_config_from_ui(config)

    def update_overlay_config_from_ui(self, config):
        """Переносит значения виджетов вкладки Overlay в конфигурацию."""
        overlay_cfg = config.setdefault("Overlay", {})
        for key, info in getattr(self, 'overlay_widgets', {}).items():
            widget = info.get("widget")
            variable = info.get("variable")
            try:
                if variable is not None:
                    value = variable.get()
                elif widget is None:
                    continue
                elif key.endswith("_hex"):
                    # В комбобоксе хранится название цвета, в конфиге — HEX
                    selected = widget.get()
                    value = COLOR_CHOICES.get(selected, selected)
                else:
                    value = widget.get()
            except Exception:
                continue

            if key == "target_fps":
                try:
                    value = int(round(float(value)))
                except (TypeError, ValueError):
                    continue
            elif key == "box_line_thickness":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

            overlay_cfg[key] = value

    def validate_inputs(self):
        """Проверяет корректность введенных пользователем данных."""
        if hasattr(self, 'trigger_key_entry') and not self.trigger_key_entry.get().strip(): raise ValueError("Клавиша триггера пустая.")
        if hasattr(self, 'jump_key_entry') and not self.jump_key_entry.get().strip(): raise ValueError("Клавиша бхопа пустая.")
    def reset_to_default_settings(self):
        """Сбрасывает все параметры на значения по умолчанию."""
        if not messagebox.askyesno("Сброс", "Вы уверены, что хотите сбросить все настройки на дефолтные? Это остановит функции."):
            return
        try:
            self.stop_client()
            new_config = copy.deepcopy(ConfigManager.DEFAULT_CONFIG)
            
            self.triggerbot.config = new_config
            self.overlay.config = new_config
            self.bunnyhop.config = new_config
            self.noflash.config = new_config
            
            ConfigManager.save_config(new_config)
            self.update_ui_from_config()
            messagebox.showinfo("Reset", "Все настройки успешно сброшены!")
        except Exception:
            logger.exception("Ошибка при сбросе настроек на дефолт.")
            messagebox.showerror("Error", "Failed to reset settings. Check logs.")

    def update_ui_from_config(self):
        """Обновляет элементы GUI из текущего конфига."""
        config = ConfigManager.load_config()
        settings = config.get("General", {})
        if hasattr(self, 'trigger_var'): self.trigger_var.set(settings["Trigger"])
        if hasattr(self, 'overlay_var'): self.overlay_var.set(settings["Overlay"])
        if hasattr(self, 'bunnyhop_var'): self.bunnyhop_var.set(settings["Bunnyhop"])
        if hasattr(self, 'noflash_var'): self.noflash_var.set(settings["Noflash"])

        t_settings = config.get("Trigger", {})
        if hasattr(self, 'trigger_key_entry'):
            self.trigger_key_entry.delete(0, "end")
            self.trigger_key_entry.insert(0, t_settings["TriggerKey"])
        if hasattr(self, 'toggle_mode_var'): self.toggle_mode_var.set(t_settings["ToggleMode"])
        if hasattr(self, 'attack_teammates_var'): self.attack_teammates_var.set(t_settings["AttackOnTeammates"])
        if hasattr(self, 'active_weapon_type'):
            self.active_weapon_type.set(t_settings.get('active_weapon_type', 'Rifles'))
            self.update_weapon_settings_display()

        bh_settings = config.get("Bunnyhop", {})
        if hasattr(self, 'jump_key_entry'):
            self.jump_key_entry.delete(0, "end")
            self.jump_key_entry.insert(0, bh_settings.get("JumpKey", "space"))
        if hasattr(self, 'jump_delay_entry'):
            self.jump_delay_entry.delete(0, "end")
            self.jump_delay_entry.insert(0, str(bh_settings.get("JumpDelay", 0.01)))

        nf_settings = config.get("NoFlash", {})
        if hasattr(self, 'FlashSuppressionStrength_slider'):
            self.FlashSuppressionStrength_slider.set(nf_settings.get("FlashSuppressionStrength", 0.0))

        # Синхронизируем виджеты вкладки Overlay (иначе после reset/внешнего
        # изменения config.json GUI показывал старые значения и затирал их обратно)
        overlay_settings = config.get("Overlay", {})
        for key, info in getattr(self, 'overlay_widgets', {}).items():
            if key not in overlay_settings:
                continue
            widget = info.get("widget")
            variable = info.get("variable")
            value = overlay_settings[key]
            try:
                if variable is not None:
                    variable.set(bool(value))
                elif widget is None:
                    continue
                elif key.endswith("_hex"):
                    widget.set(Utility.get_color_name_from_hex(str(value)))
                else:
                    widget.set(float(value))
            except Exception:
                continue

    def open_config_directory(self):
        """Открывает папку с файлом конфигурации софта."""
        if platform.system() == "Windows":
            os.startfile(ConfigManager.CONFIG_DIRECTORY)

    def init_config_watcher(self):
        """Запускает слежение за изменениями config.json на диске."""
        try:
            event_handler = ConfigFileChangeHandler(self)
            self.observer = Observer()
            self.observer.schedule(event_handler, path=ConfigManager.CONFIG_DIRECTORY, recursive=False)
            self.observer.start()
            logger.info("Слежение за файлом конфигурации успешно запущено.")
        except Exception:
            logger.exception("Ошибка инициализации слежения за конфигурацией.")

    def start_log_timer(self):
        """Запускает цикличный таймер для вывода логов на вкладку софта."""
        def read_log_file():
            try:
                log_path = Logger.LOG_FILE()
                if hasattr(self, 'log_text') and os.path.exists(log_path):
                    size = os.path.getsize(log_path)
                    position = getattr(self, 'last_log_position', 0) or 0
                    if size < position:  # лог пересоздан/ротирован
                        position = 0
                    if size > position:
                        with open(log_path, 'rb') as f:
                            f.seek(position)
                            chunk = f.read()
                        self.last_log_position = size
                        self.root.after(0, self.append_log_display, chunk.decode('utf-8', errors='replace'))
            except Exception:
                pass
            self.log_timer = self.root.after(1000, read_log_file)
        read_log_file()

    def append_log_display(self, text):
        """Дописывает новые строки лога в текстовое поле (без перечитывания всего файла)."""
        if not text:
            return
        try:
            if hasattr(self, 'log_text') and self.log_text.winfo_exists():
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                if not text.endswith("\n"):
                    text += "\n"
                self.log_text.configure(state="normal")
                self.log_text.insert("end", text)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except Exception:
            pass

    def run(self):
        """Запуск главного Tkinter цикла."""
        self.root.mainloop()

    def on_closing(self):
        """Срабатывает при закрытии крестика окна софта."""
        self.cleanup()
        self.root.destroy()

    def cleanup(self):
        """Очищает занятые потоки и таймеры перед выходом."""
        try:
            self.stop_client()
            if hasattr(self, 'observer') and self.observer:
                self.observer.stop()
                self.observer.join()
            if self.log_timer:
                self.root.after_cancel(self.log_timer)
        except Exception:
            pass

if __name__ == "__main__":
    # Безопасно инициализируем и запускаем логгер проекта перед стартом GUI
    Logger.setup_logging()
    app = MainWindow()
    app.run()
