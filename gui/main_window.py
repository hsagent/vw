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

        # Шаг 1. Безопасно выкачиваем JSON дампы с офсетами
        self.offsets, self.client_data, self.buttons_data = self.fetch_offsets_or_warn()

        # Шаг 2. Строим единый менеджер памяти для всех подсистем
        self.memory_manager = MemoryManager(self.offsets, self.client_data, self.buttons_data)

        # Шаг 3. Инициализируем исполнительные механизмы чита
        self.initialize_features()
        
        self.root.title("VioletWing — CS2 Tool")
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
        
        # Шаг 4. Привязываем ClientManager к собранному окну
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
        
        ctk.CTkLabel(title_frame, text="Violet", font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H2, "bold"), text_color=COLOR_ACCENT_FG[0]).pack(side="left")
        ctk.CTkLabel(title_frame, text="Wing", font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H2, "bold"), text_color=COLOR_TEXT_PRIMARY[1]).pack(side="left", padx=(5, 0))
        
        version_badge = ctk.CTkFrame(left_frame, fg_color=("#f3e8ff", "#2d1b4e"), corner_radius=12, height=28)
        version_badge.pack(side="left", padx=(15, 0))
        
        ctk.CTkLabel(version_badge, text=f"{ConfigManager.VERSION}", font=(FONT_FAMILY_BOLD[0], 12, "bold"), text_color=COLOR_ACCENT_FG[0], padx=12, pady=4).pack()

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
                social_frame, text=data["text"], image=ctk_image, compound="left",
                command=lambda u=data["url"]: webbrowser.open(u),
                height=32, corner_radius=16, fg_color=data["fg_color"], hover_color=data["hover_color"],
                border_width=1 if "border_color" in data else 0, border_color=data.get("border_color"),
                font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H4)
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
                font=(FONT_FAMILY_BOLD[0], FONT_SIZE_H4), anchor="w",
            )
            btn.pack(pady=(0, 8), padx=20, fill="x")
            self.nav_buttons[key] = btn
        self.set_active_nav("dashboard")

    def set_active_nav(self, active_key):
        """Set the active navigation button with visual feedback."""
        for key, btn in self.nav_buttons.items():
            if key == active_key:
                btn.configure(fg_color=COLOR_ACCENT_FG, text_color=COLOR_TEXT_PRIMARY[1])
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
