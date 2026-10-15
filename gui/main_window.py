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

from watchdog.observers import Observer

from classes.updater import Updater
from classes.utility import Utility
from classes.triggerbot import CS2TriggerBot
from classes.overlay import CS2Overlay
from classes.bunnyhop import CS2Bunnyhop
from classes.noflash import CS2NoFlash
from classes.config_manager import ConfigManager, COLOR_CHOICES
from classes.file_watcher import ConfigFileChangeHandler
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

logger = Logger.get_logger(__name__)

class MainWindow:
    def __init__(self):
        """Initialize the main application window and setup UI components."""
        self.repo_url = "https://github.com"
        self.trigger_thread = None
        self.overlay_thread = None
        self.bunnyhop_thread = None
        self.noflash_thread = None
        self.observer = None
        self.log_timer = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()

        # Безопасно загружаем смещения памяти
        self.offsets, self.client_data, self.buttons_data = self.fetch_offsets_or_warn()

        # Строим единый менеджер памяти
        self.memory_manager = MemoryManager(self.offsets, self.client_data, self.buttons_data)

        # Инициализируем модули чита
        self.initialize_features()
        
        self.root.title("VioletWing")
        self.root.resizable(True, True)
        self.root.minsize(1400, 800)

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (1400 // 2)
        y = (self.root.winfo_screenheight() // 2) - (800 // 2)
        self.root.geometry(f"1400x800+{x}+{y}")
        
        try:
            self.root.iconbitmap(Utility.resource_path('src/img/icon.ico'))
        except Exception:
            pass
            
        if platform.system() == "Windows":
            import ctypes
            gdi32 = ctypes.WinDLL('gdi32')
            font_files = [
                'src/fonts/Manrope-Regular.ttf', 'src/fonts/Manrope-Bold.ttf',
                'src/fonts/JetBrainsMono-Regular.ttf', 'src/fonts/JetBrainsMono-Bold.ttf'
            ]
            for font_file in font_files:
                font_path = Utility.resource_path(font_file)
                if os.path.exists(font_path): gdi32.AddFontResourceW(font_path)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        
        self.updater = Updater(self)
        self.setup_ui()
        self.init_config_watcher()
        self.start_log_timer()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.client_manager = ClientManager(self)
    def initialize_features(self):
        """Initialize all feature instances and create a centralized feature registry."""
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
            logger.info("All features initialized successfully.")
        except Exception:
            logger.exception("Failed to initialize features.")
            messagebox.showerror("Initialization Error", "Failed to initialize features. Check logs for details.")

    def setup_ui(self):
        """Setup the modern user interface components."""
        self.create_modern_header()
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
        
        title_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        title_frame.pack(side="left")
        
        ctk.CTkLabel(title_frame, text="Violet", font=(FONT_FAMILY_BOLD, FONT_SIZE_H2, "bold"), text_color=COLOR_ACCENT_FG).pack(side="left")
        ctk.CTkLabel(title_frame, text="Wing", font=(FONT_FAMILY_BOLD, FONT_SIZE_H2, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(side="left", padx=(5, 0))
        
        version_badge = ctk.CTkFrame(left_frame, fg_color=("#f3e8ff", "#2d1b4e"), corner_radius=12, height=28)
        version_badge.pack(side="left", padx=(15, 0))
        
        ctk.CTkLabel(version_badge, text=f"{ConfigManager.VERSION}", font=(FONT_FAMILY_BOLD, 12, "bold"), text_color=COLOR_ACCENT_FG, padx=12, pady=4).pack()
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
        self.status_label = ctk.CTkLabel(self.status_frame, text="Inactive", font=(FONT_FAMILY_BOLD, FONT_SIZE_H4, "bold"), text_color=BUTTON_STYLE_DANGER["fg_color"])
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
                social_frame, text=data["text"], image=ctk_image, compound="left",
                command=lambda u=data["url"]: webbrowser.open(u),
                height=32, corner_radius=16, fg_color=data["fg_color"], hover_color=data["hover_color"],
                border_width=1 if "border_color" in data else 0, border_color=data.get("border_color"),
                font=(FONT_FAMILY_BOLD, FONT_SIZE_H4)
            )
            btn.pack(side="left", padx=(0, 8) if i < len(social_buttons_data) - 1 else (0, 0))
        return social_frame

    def create_update_button(self, parent):
        """Create the update button if an update is available."""
        try:
            image = Image.open(Utility.resource_path(f'src/img/update_icon.png'))
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(24, 24))
        except Exception:
            ctk_image = None

        if hasattr(self, 'updater') and self.updater.check_for_updates():
            update_btn = ctk.CTkButton(
                parent, text="Update Available!", image=ctk_image, command=self.updater.handle_update,
                width=120, height=32, corner_radius=16,
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
            "dashboard": populate_dashboard,
            "general_settings": populate_general_settings,
            "trigger_settings": populate_trigger_settings,
            "overlay_settings": populate_overlay_settings,
            "additional_settings": populate_additional_settings,
            "logs": populate_logs,
            "faq": populate_faq,
            "notifications": populate_notifications,
            "supporters": populate_supporters,
        }

        self.tab_frames = {}
        for key, populate_func in self.tab_views.items():
            frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
            self.tab_frames[key] = frame
            populate_func(self, frame)

        self.current_view = None
        self.switch_view("dashboard")

    def create_sidebar(self, parent):
        """Create modern sidebar navigation."""
        sidebar = ctk.CTkFrame(parent, width=280, corner_radius=0, fg_color=COLOR_BACKGROUND)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        self.nav_items = [
            ("Dashboard", "dashboard", "🏠"), ("General Settings", "general_settings", "⚙️"),
            ("Trigger Settings", "trigger_settings", "🔫"), ("Overlay Settings", "overlay_settings", "🌍"),
            ("Additional Settings", "additional_settings", "⚡"), ("Logs", "logs", "📋"),
            ("FAQ", "faq", "❓"), ("Notifications", "notifications", "🔔"), ("Supporters", "supporters", "🤝"),
        ]

        self.nav_buttons = {}
        ctk.CTkFrame(sidebar, height=30, fg_color="transparent").pack(fill="x")

        for name, key, icon in self.nav_items:
            btn = ctk.CTkButton(
                sidebar, text=f"{icon}  {name}", command=lambda k=key: self.switch_view(k),
                width=240, height=50, corner_radius=12, fg_color="transparent",
                hover_color=COLOR_WIDGET_BACKGROUND, text_color=COLOR_TEXT_SECONDARY,
                font=(FONT_FAMILY_BOLD, FONT_SIZE_H4), anchor="w",
            )
            btn.pack(pady=(0, 8), padx=20, fill="x")
            self.nav_buttons[key] = btn
        self.set_active_nav("dashboard")

    def set_active_nav(self, active_key):
        """Set the active navigation button with visual feedback."""
        for key, btn in self.nav_buttons.items():
            if key == active_key:
                btn.configure(fg_color=COLOR_ACCENT_FG, text_color=COLOR_TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_SECONDARY, hover_color=COLOR_WIDGET_BACKGROUND)

    def switch_view(self, view_key):
        """Switch between different views by showing the appropriate frame."""
        if self.current_view == view_key: return
        if self.current_view and self.current_view in self.tab_frames:
            self.tab_frames[self.current_view].pack_forget()

        self.current_view = view_key
        self.set_active_nav(view_key)
        if view_key in self.tab_frames:
            self.tab_frames[view_key].pack(fill="both", expand=True)
    def fetch_offsets_or_warn(self):
        """Attempt to fetch offsets; warn the user and return empty dictionaries on failure."""
        try:
            offsets, client_data, buttons_data = Utility.fetch_offsets()
            if offsets is None or client_data is None or buttons_data is None:
                raise ValueError("Failed to fetch offsets from the server.")
            return offsets, client_data, buttons_data
        except Exception:
            logger.exception("Failed to fetch offsets from the server.")
            messagebox.showerror("Offset Error", "Failed to fetch offsets. Check logs for details.")
            return {}, {}, {}

    def update_client_status(self, status, color):
        """Update client status in header and dashboard."""
        self.status_label.configure(text=status, text_color=color)
        for widget in self.status_frame.winfo_children():
            if isinstance(widget, ctk.CTkFrame) and widget.cget("width") == 12:
                widget.configure(fg_color=color)
                break
        if hasattr(self, 'bot_status_label'):
            self.bot_status_label.configure(text=status, text_color=color)

    def start_client(self):
        self.client_manager.start_client()

    def stop_client(self):
        self.client_manager.stop_client()

    def update_weapon_settings_display(self):
        """Update UI fields based on the selected weapon type."""
        weapon_type = self.active_weapon_type.get()
        settings = self.triggerbot.config['Trigger']['WeaponSettings'].get(weapon_type, {})
        
        if hasattr(self, 'min_delay_entry'):
            self.min_delay_entry.delete(0, "end")
            self.min_delay_entry.insert(0, str(settings.get('ShotDelayMin', 15)))
        if hasattr(self, 'max_delay_entry'):
            self.max_delay_entry.delete(0, "end")
            self.max_delay_entry.insert(0, str(settings.get('ShotDelayMax', 35)))
        if hasattr(self, 'post_shot_delay_entry'):
            self.post_shot_delay_entry.delete(0, "end")
            self.post_shot_delay_entry.insert(0, str(settings.get('PostShotDelay', 100)))

    def save_settings(self, show_message=False):
        """Save the configuration settings and apply to relevant features safely."""
        try:
            self.validate_inputs()
            config = ConfigManager.load_config()
            old_config = config.copy()

            self.update_config_from_ui(config)
            ConfigManager.save_config(config, log_info=False)
            
            if hasattr(self, 'client_manager'):
                self.client_manager.apply_feature_state_changes(old_config, config)
                self.client_manager.update_running_feature_configs(config)

            if show_message:
                messagebox.showinfo("Settings Saved", "Configuration has been saved successfully.")
        except ValueError as e:
            messagebox.showerror("Invalid Input", str(e))
        except Exception:
            logger.exception("An unexpected error occurred while saving settings.")
            messagebox.showerror("Error", "An unexpected error occurred. Check logs for details.")

    def restart_affected_features(self, old_config, new_config):
        """Safe thread state updates via centralized client manager."""
        if hasattr(self, 'client_manager'):
            self.client_manager.apply_feature_state_changes(old_config, new_config)

    def update_config_from_ui(self, config):
        self._update_general_config_from_ui(config)
        self._update_trigger_config_from_ui(config)
        self._update_overlay_config_from_ui(config)
        self._update_additional_config_from_ui(config)

    def _update_general_config_from_ui(self, config):
        settings = config["General"]
        if hasattr(self, 'trigger_var'): settings["Trigger"] = self.trigger_var.get()
        if hasattr(self, 'overlay_var'): settings["Overlay"] = self.overlay_var.get()
        if hasattr(self, 'bunnyhop_var'): settings["Bunnyhop"] = self.bunnyhop_var.get()
        if hasattr(self, 'noflash_var'): settings["Noflash"] = self.noflash_var.get()
        if hasattr(self, 'offset_source_var') and hasattr(self, 'offset_source_mapping'):
            settings["OffsetSource"] = self.offset_source_mapping.get(self.offset_source_var.get(), "a2x")

    def _update_trigger_config_from_ui(self, config):
        settings = config["Trigger"]
        if hasattr(self, 'trigger_key_entry'): settings["TriggerKey"] = self.trigger_key_entry.get().strip()
        if hasattr(self, 'toggle_mode_var'): settings["ToggleMode"] = self.toggle_mode_var.get()
        if hasattr(self, 'attack_teammates_var'): settings["AttackOnTeammates"] = self.attack_teammates_var.get()
        if hasattr(self, 'active_weapon_type'):
            w_type = self.active_weapon_type.get()
            settings['active_weapon_type'] = w_type
            w_set = settings['WeaponSettings'].get(w_type, {})
            try:
                if hasattr(self, 'min_delay_entry'): w_set['ShotDelayMin'] = int(self.min_delay_entry.get())
                if hasattr(self, 'max_delay_entry'): w_set['ShotDelayMax'] = int(self.max_delay_entry.get())
                if hasattr(self, 'post_shot_delay_entry'): w_set['PostShotDelay'] = int(self.post_shot_delay_entry.get())
            except ValueError: pass
            settings['WeaponSettings'][w_type] = w_set
    def _update_overlay_config_from_ui(self, config):
        settings = config["Overlay"]
        widgets = getattr(self, 'overlay_widgets', {})
        def get_val(key, v_type):
            if key in widgets:
                if v_type == "var" and "variable" in widgets[key]: return widgets[key]["variable"].get()
                if v_type == "widget" and "widget" in widgets[key]: return widgets[key]["widget"].get()
            return None

        for k in ["enable_box", "enable_skeleton", "draw_snaplines", "draw_health_numbers", "draw_nicknames", "use_transliteration", "draw_teammates"]:
            val = get_val(k, "var")
            if val is not None: settings[k] = val
        for k in ["box_line_thickness", "target_fps"]:
            val = get_val(k, "widget")
            if val is not None: settings[k] = val
        for k, d_col in {"box_color_hex": "#FFA500", "snaplines_color_hex": "#FFFFFF", "text_color_hex": "#FFFFFF", "teammate_color_hex": "#00FFFF"}.items():
            val = get_val(k, "widget")
            if val is not None: settings[k] = COLOR_CHOICES.get(val, d_col)

    def _update_additional_config_from_ui(self, config):
        b_set = config.get("Bunnyhop", {})
        if hasattr(self, 'jump_key_entry'): b_set["JumpKey"] = self.jump_key_entry.get().strip()
        try:
            if hasattr(self, 'jump_delay_entry'): b_set["JumpDelay"] = float(self.jump_delay_entry.get())
        except ValueError: pass
        n_set = config.get("NoFlash", {})
        if hasattr(self, 'FlashSuppressionStrength_slider'): n_set["FlashSuppressionStrength"] = self.FlashSuppressionStrength_slider.get()

    def validate_inputs(self):
        if hasattr(self, 'trigger_key_entry') and not self.trigger_key_entry.get().strip(): raise ValueError("Trigger key cannot be empty.")
        if hasattr(self, 'jump_key_entry') and not self.jump_key_entry.get().strip(): raise ValueError("Jump key cannot be empty.")

    def reset_to_default_settings(self):
        if not messagebox.askyesno("Reset Settings", "Are you sure you want to reset all settings to defaults?"): return
        try:
            self.stop_client()
            new_config = ConfigManager.DEFAULT_CONFIG.copy()
            self.triggerbot.config = new_config
            self.overlay.config = new_config
            self.bunnyhop.config = new_config
            self.noflash.config = new_config
            self.update_ui_from_config()
            ConfigManager.save_config(new_config)
        except Exception: logger.exception("Failed to reset settings.")

    def update_ui_from_config(self):
        self._update_general_settings_ui_from_config()
        self._update_trigger_settings_ui_from_config()
        self._update_overlay_settings_ui_from_config()
        self._update_additional_settings_ui_from_config()

    def _update_general_settings_ui_from_config(self):
        settings = self.triggerbot.config["General"]
        if hasattr(self, 'trigger_var'): self.trigger_var.set(settings["Trigger"])
        if hasattr(self, 'overlay_var'): self.overlay_var.set(settings["Overlay"])
        if hasattr(self, 'bunnyhop_var'): self.bunnyhop_var.set(settings["Bunnyhop"])
        if hasattr(self, 'noflash_var'): self.noflash_var.set(settings["Noflash"])

    def _update_trigger_settings_ui_from_config(self):
        settings = self.triggerbot.config["Trigger"]
        if hasattr(self, 'trigger_key_entry'):
            self.trigger_key_entry.delete(0, "end")
            self.trigger_key_entry.insert(0, settings["TriggerKey"])
        if hasattr(self, 'toggle_mode_var'): self.toggle_mode_var.set(settings["ToggleMode"])
        if hasattr(self, 'attack_teammates_var'): self.attack_teammates_var.set(settings["AttackOnTeammates"])
        if hasattr(self, 'active_weapon_type'):
            self.active_weapon_type.set(settings.get('active_weapon_type', 'Rifles'))
            self.update_weapon_settings_display()

    def _update_overlay_settings_ui_from_config(self):
        settings = self.overlay.config["Overlay"]
        if hasattr(self, 'enable_box_var'): self.enable_box_var.set(settings["enable_box"])
        if hasattr(self, 'enable_skeleton_var'): self.enable_skeleton_var.set(settings["enable_skeleton"])
        if hasattr(self, 'box_line_thickness_slider'): self.box_line_thickness_slider.set(settings["box_line_thickness"])
        if hasattr(self, 'box_color_hex_combo'): self.box_color_hex_combo.set(Utility.get_color_name_from_hex(settings["box_color_hex"]))
        if hasattr(self, 'draw_snaplines_var'): self.draw_snaplines_var.set(settings["draw_snaplines"])

    def _update_additional_settings_ui_from_config(self):
        b_set = self.bunnyhop.config.get("Bunnyhop", {})
        if hasattr(self, 'jump_key_entry'):
            self.jump_key_entry.delete(0, "end")
            self.jump_key_entry.insert(0, b_set.get("JumpKey", "space"))
        if hasattr(self, 'jump_delay_entry'):
            self.jump_delay_entry.delete(0, "end")
            self.jump_delay_entry.insert(0, str(b_set.get("JumpDelay", 0.015)))
        n_set = self.noflash.config.get("NoFlash", {})
        if hasattr(self, 'FlashSuppressionStrength_slider'): self.FlashSuppressionStrength_slider.set(n_set.get("FlashSuppressionStrength", 0.0))

    def open_config_directory(self):
        if platform.system() == "Windows": os.startfile(ConfigManager.CONFIG_DIRECTORY)

    def init_config_watcher(self):
        try:
            event_handler = ConfigFileChangeHandler(self)
            self.observer = Observer()
            self.observer.schedule(event_handler, path=ConfigManager.CONFIG_DIRECTORY, recursive=False)
            self.observer.start()
        except Exception: logger.exception("Failed to initialize config file watcher.")

    def start_log_timer(self):
        def read_log_file():
            try:
                log_f = os.path.join(ConfigManager.CONFIG_DIRECTORY, "Logs", "violetwing.log")
                if hasattr(self, 'log_text') and os.path.exists(log_f):
                    with open(log_f, 'r', encoding='utf-8') as f: log_content = f.read()
                    self.root.after(0, self.update_log_display, log_content)
            except Exception: pass
            self.log_timer = self.root.after(2000, read_log_file)
        read_log_file()

    def update_log_display(self, log_content):
        try:
            if hasattr(self, 'log_text') and self.log_text.winfo_exists():
                if self.log_text.get("1.0", "end-1c") == log_content: return
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.insert("1.0", log_content)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except Exception: pass

    def run(self):
        self.root.mainloop()

    def on_closing(self):
        self.cleanup()
        self.root.destroy()

    def cleanup(self):
        try:
            self.stop_client()
            if hasattr(self, 'observer') and self.observer:
                self.observer.stop()
                self.observer.join()
            if self.log_timer: self.root.after_cancel(self.log_timer)
        except Exception: pass
