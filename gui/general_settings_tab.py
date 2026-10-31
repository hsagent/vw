import customtkinter as ctk
import json
import os
from pathlib import Path
from tkinter import filedialog, messagebox
from classes.config_manager import ConfigManager
from src.offsets import updater
from gui.theme import (
    FONT_TITLE, FONT_SUBTITLE, FONT_SECTION_TITLE, FONT_SECTION_DESCRIPTION,
    FONT_ITEM_LABEL, FONT_ITEM_DESCRIPTION, FONT_WIDGET,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_ACCENT_FG, COLOR_ACCENT_HOVER,
    SECTION_STYLE, SETTING_ITEM_STYLE, CHECKBOX_STYLE, COMBOBOX_STYLE,
    BUTTON_STYLE_PRIMARY, BUTTON_STYLE_DANGER
)

# --- Константы интерфейса ---
FEATURE_SETTINGS = [
    ("Enable Trigger", "checkbox", "Trigger", "Toggle the trigger bot feature"),
    ("Enable Overlay", "checkbox", "Overlay", "Toggle the ESP overlay feature"),
    ("Enable Bunnyhop", "checkbox", "Bunnyhop", "Toggle the bunnyhop feature"),
    ("Enable Noflash", "checkbox", "Noflash", "Toggle the noflash feature")
]

OFFSET_FILES = [
    ("Offsets File", "offsets.json", "Select offsets.json file", "OffsetsFile"),
    ("Client DLL File", "client_dll.json", "Select client_dll.json file", "ClientDLLFile"),
    ("Buttons File", "buttons.json", "Select buttons.json file", "ButtonsFile")
]


def _validate_selected_offset_file(file_path, config_key):
    """Проверяет выбранный JSON до сохранения пути в конфигурации."""
    try:
        with open(file_path, "r", encoding="utf-8-sig") as file:
            payload = json.load(file)

        if config_key == "OffsetsFile":
            offsets_data = payload.get("client.dll", {}) if isinstance(payload, dict) else {}
            required = {
                "dwEntityList",
                "dwLocalPlayerPawn",
                "dwLocalPlayerController",
                "dwViewMatrix",
            }
            valid = (
                isinstance(offsets_data, dict)
                and required.issubset(offsets_data)
                and all(isinstance(offsets_data[key], int) and offsets_data[key] > 0 for key in required)
            )
        elif config_key == "ClientDLLFile":
            client_data = payload.get("client.dll", payload) if isinstance(payload, dict) else {}
            valid = (
                isinstance(client_data, dict)
                and isinstance(client_data.get("classes"), dict)
                and bool(client_data["classes"])
            )
        else:
            buttons_data = payload.get("client.dll", payload) if isinstance(payload, dict) else {}
            valid = (
                isinstance(buttons_data, dict)
                and isinstance(buttons_data.get("jump"), int)
                and buttons_data["jump"] > 0
            )

        if not valid:
            raise ValueError("Unexpected JSON structure")
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        messagebox.showerror(
            "Invalid Offsets File",
            f"The selected file is not a valid {config_key} JSON file.\n\n{e}",
        )
        return False

def create_section_header(parent, title, subtitle):
    """Создает стандартизированный заголовок подраздела настроек."""
    header = ctk.CTkFrame(parent, fg_color="transparent")
    header.pack(fill="x", padx=40, pady=(40, 30))

    ctk.CTkLabel(
        header, text=title, font=FONT_SECTION_TITLE,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(side="left")

    ctk.CTkLabel(
        header, text=subtitle, font=FONT_SECTION_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY, anchor="e"
    ).pack(side="right")
    
    return header

def populate_general_settings(main_window, frame):
    """Инициализирует и строит вкладку General Settings."""
    config = ConfigManager.load_config()
    general_config = config.get("General", {})
    settings = ctk.CTkScrollableFrame(frame, fg_color="transparent")
    settings.pack(fill="both", expand=True, padx=40, pady=40)
    
    # Увеличиваем скорость прокрутки scrollable фрейма
    settings._parent_canvas.configure(yscrollincrement=12)

    title_frame = ctk.CTkFrame(settings, fg_color="transparent")
    title_frame.pack(fill="x", pady=(0, 40))

    ctk.CTkLabel(
        title_frame, text="⚙️  General Settings", font=FONT_TITLE,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(side="left")

    ctk.CTkLabel(
        title_frame, text="Configure main application features", font=FONT_SUBTITLE,
        text_color=COLOR_TEXT_SECONDARY, anchor="w"
    ).pack(side="left", padx=(20, 0), pady=(10, 0))

    create_features_section(main_window, settings, general_config)
    create_offsets_section(main_window, settings, general_config)
    create_reset_section(main_window, settings)

def create_reset_section(main_window, parent):
    """Секция сброса и открытия локальных папок конфигурации."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))

    create_section_header(section, "⚙️  Configuration Management", "Manage configuration files and settings")

    button_frame = ctk.CTkFrame(section, fg_color="transparent")
    button_frame.pack(fill="x", padx=40, pady=(0, 40))

    ctk.CTkButton(
        button_frame, text="📁  Open Config Directory", width=280,
        command=main_window.open_config_directory, **BUTTON_STYLE_PRIMARY
    ).pack(side="left", padx=(0, 20))

    ctk.CTkButton(
        button_frame, text="🔄  Reset All Settings", width=280,
        command=main_window.reset_to_default_settings, **BUTTON_STYLE_DANGER
    ).pack(side="left")
def create_features_section(main_window, parent, general_config):
    """Создает секцию включения и выключения основных функций софта."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))

    create_section_header(section, "🔧  Feature Configuration", "Enable or disable main application features")

    for i, (label, widget, key, desc) in enumerate(FEATURE_SETTINGS):
        create_setting_item(
            parent=section,
            label_text=label,
            description=desc,
            widget_type=widget,
            key=key,
            main_window=main_window,
            general_config=general_config,
            is_last=(i == len(FEATURE_SETTINGS) - 1)
        )

def create_offsets_section(main_window, parent, general_config):
    """Создает секцию выбора источника смещений (дампера) и локальных файлов."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))

    header = create_section_header(section, "📡  Offsets Configuration", "Configure offset source and local files")

    # Переведено на стабильный локальный маппинг дамперов под CS2, чтобы GUI никогда не зависал
    source_mapping = {
        "A2X Авто-Дампер (Рекомендуется)": "a2x",
        "Локальные файлы конфигурации (.json)": "local"
    }
    
    main_window.offset_source_mapping = source_mapping
    dropdown_values = list(source_mapping.keys())

    current_source = general_config.get("OffsetSource", "a2x")
    current_display = next((name for name, sid in source_mapping.items() if sid == current_source), dropdown_values[0])

    main_window.offset_source_var = ctk.StringVar(value=current_display)
    
    ctk.CTkOptionMenu(
        header,
        variable=main_window.offset_source_var,
        values=dropdown_values,
        command=lambda dn: update_offset_source(main_window, source_mapping[dn]),
        **COMBOBOX_STYLE
    ).pack(side="right", padx=(0, 10))

    main_window.local_files_frame = ctk.CTkFrame(section, fg_color="transparent")
    if current_source == "local":
        main_window.local_files_frame.pack(fill="x", padx=40, pady=(0, 40))

    main_window.local_file_paths = {}
    for label, filename, desc, config_key in OFFSET_FILES:
        create_file_selector(
            main_window,
            main_window.local_files_frame,
            label,
            filename,
            desc,
            config_key,
            general_config,
        )

def create_file_selector(
    main_window,
    parent,
    label_text,
    filename,
    description,
    config_key,
    general_config,
):
    """Создает элемент выбора конкретного JSON-файла смещений с диска."""
    item_frame = ctk.CTkFrame(parent, fg_color="transparent")
    item_frame.pack(fill="x", padx=0, pady=(0, 10))
    
    container = ctk.CTkFrame(item_frame, **SETTING_ITEM_STYLE)
    container.pack(fill="x")

    content_frame = ctk.CTkFrame(container, fg_color="transparent")
    content_frame.pack(fill="x", padx=25, pady=15)

    label_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    label_frame.pack(side="left", fill="x", expand=True)

    ctk.CTkLabel(
        label_frame, text=label_text, font=FONT_ITEM_LABEL,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(fill="x", pady=(0, 4))

    ctk.CTkLabel(
        label_frame, text=description, font=FONT_ITEM_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY, anchor="w", wraplength=400
    ).pack(fill="x")

    button_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    button_frame.pack(side="right", padx=(30, 0))

    def select_file():
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            initialdir=Path(ConfigManager.CONFIG_DIRECTORY)
        )
        if file_path:
            if not _validate_selected_offset_file(file_path, config_key):
                return
            config = ConfigManager.load_config()
            config.setdefault("General", {})[config_key] = file_path
            if not ConfigManager.save_config(config, log_info=False):
                messagebox.showerror(
                    "Save Error",
                    f"Failed to save path for {filename}.",
                )
                return
            main_window.local_file_paths[filename] = file_path
            file_button.configure(text=f"Selected: {os.path.basename(file_path)}")
            updater.invalidate()

    current_file = general_config.get(config_key, "")
    button_text = f"Selected: {os.path.basename(current_file)}" if current_file and os.path.exists(current_file) else f"Select {filename}"

    file_button = ctk.CTkButton(
        button_frame, text=button_text, font=FONT_WIDGET, corner_radius=10,
        fg_color=COLOR_ACCENT_FG, hover_color=COLOR_ACCENT_HOVER, command=select_file
    )
    file_button.pack()

def update_offset_source(main_window, selected_source_id):
    """Обновляет источник смещений в конфигурации и переключает видимость фреймов."""
    if selected_source_id == "local":
        config = ConfigManager.load_config()
        general = config.get("General", {})
        missing = [
            label
            for label, _, _, key in OFFSET_FILES
            if not Path(general.get(key, "")).is_file()
        ]
        if missing:
            messagebox.showerror(
                "Local Offsets Missing",
                "Select all required local files before enabling the local source:\n\n"
                + "\n".join(missing),
            )
            current_display = next(
                name
                for name, source_id in main_window.offset_source_mapping.items()
                if source_id == "a2x"
            )
            main_window.offset_source_var.set(current_display)
            return

    if not ConfigManager.set_value(
        "General",
        "OffsetSource",
        value=selected_source_id,
    ):
        messagebox.showerror("Save Error", "Failed to save the offsets source.")
        return

    # Сбрасываем данные текущего источника: следующий запуск клиента гарантированно
    # загрузит выбранные файлы или сетевой a2x, а не старый снимок.
    updater.invalidate()

    messagebox.showwarning(
        "Restart Required", 
        "Offset source has been changed. Please restart the application for the changes to take effect."
    )

    if selected_source_id == "local":
        main_window.local_files_frame.pack(fill="x", padx=40, pady=(0, 40))
    else:
        main_window.local_files_frame.pack_forget()

def create_setting_item(
    parent,
    label_text,
    description,
    widget_type,
    key,
    main_window,
    general_config,
    is_last=False,
):
    """Универсальный элемент строки настроек с текстовым описанием и чекбоксом."""
    item_frame = ctk.CTkFrame(parent, fg_color="transparent")
    item_frame.pack(fill="x", padx=40, pady=(0, 30 if not is_last else 40))
    
    container = ctk.CTkFrame(item_frame, **SETTING_ITEM_STYLE)
    container.pack(fill="x")
    
    content_frame = ctk.CTkFrame(container, fg_color="transparent")
    content_frame.pack(fill="x", padx=25, pady=25)
    
    label_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    label_frame.pack(side="left", fill="x", expand=True)
    
    ctk.CTkLabel(
        label_frame, text=label_text, font=FONT_ITEM_LABEL,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(fill="x", pady=(0, 4))
    
    ctk.CTkLabel(
        label_frame, text=description, font=FONT_ITEM_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY, anchor="w", wraplength=400
    ).pack(fill="x")
    
    widget_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    widget_frame.pack(side="right", padx=(30, 0))
    
    if widget_type == "checkbox":
        initial_val = general_config.get(key, False)
        var = ctk.BooleanVar(value=initial_val)
        
        ctk.CTkCheckBox(
            widget_frame, text="", variable=var,
            command=lambda: main_window.save_settings(show_message=False),
            **CHECKBOX_STYLE
        ).pack()
        
        setattr(main_window, f"{key.lower()}_var", var)
    else:
        raise ValueError(f"Unsupported widget type: {widget_type}")
