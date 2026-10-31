import customtkinter as ctk
from classes.config_manager import ConfigManager
from gui.theme import (FONT_TITLE, FONT_SUBTITLE, FONT_SECTION_TITLE, FONT_SECTION_DESCRIPTION,
                         FONT_ITEM_LABEL, FONT_ITEM_DESCRIPTION, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
                         SECTION_STYLE, SETTING_ITEM_STYLE, CHECKBOX_STYLE, ENTRY_STYLE, COMBOBOX_STYLE)

WEAPON_TYPES = ["Pistols", "Rifles", "Snipers", "SMGs", "Heavy"]

def populate_trigger_settings(main_window, frame):
    """Инициализирует и строит вкладку Trigger Settings."""
    main_window.trigger_settings_frame = frame
    config = ConfigManager.load_config()
    trigger_config = config.get("Trigger", {})

    settings = ctk.CTkScrollableFrame(frame, fg_color="transparent")
    settings.pack(fill="both", expand=True, padx=40, pady=40)
    
    # Оптимизируем скорость и плавность вертикальной прокрутки меню
    settings._parent_canvas.configure(yscrollincrement=12)
    
    create_title_section(settings)
    create_trigger_config_section(main_window, settings, trigger_config)
    create_timing_settings_section(main_window, settings, trigger_config)

def create_title_section(parent):
    """Создает главный заголовок вкладки настроек."""
    title_frame = ctk.CTkFrame(parent, fg_color="transparent")
    title_frame.pack(fill="x", pady=(0, 40))
    
    ctk.CTkLabel(
        title_frame, text="🔫  Trigger Settings", font=FONT_TITLE,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(side="left")
    
    ctk.CTkLabel(
        title_frame, text="Configure your trigger bot preferences", font=FONT_SUBTITLE,
        text_color=COLOR_TEXT_SECONDARY, anchor="w"
    ).pack(side="left", padx=(20, 0), pady=(10, 0))

def create_trigger_config_section(main_window, parent, trigger_config):
    """Создает подраздел основных параметров клавиш и режимов триггера."""
    section = create_section_frame(parent)
    create_section_header(section, "🎯  Configuration", "Control how the trigger responds")
    
    settings_list = [
        ("Trigger Key", "entry", "TriggerKey", "Key to activate trigger (e.g., 'x', 'mouse4')"),
        ("Toggle Mode", "checkbox", "ToggleMode", "Enable toggle mode instead of hold mode"),
        ("Attack Teammates", "checkbox", "AttackOnTeammates", "Allow triggering on teammates")
    ]
    
    for i, (label, widget_type, key, desc) in enumerate(settings_list):
        create_setting_item(
            section, main_window, label, desc, widget_type, key,
            trigger_config, is_last=(i == len(settings_list) - 1)
        )

def create_timing_settings_section(main_window, parent, trigger_config):
    """Создает подраздел настройки задержек выстрела для типов оружия."""
    section = create_section_frame(parent)
    header_frame = create_section_header(section, "⏱️  Timing Settings", "Fine-tune shooting delays per weapon type")

    current_weapon = trigger_config.get("active_weapon_type", "Rifles")
    main_window.active_weapon_type = ctk.StringVar(value=current_weapon)

    weapon_dropdown = ctk.CTkOptionMenu(
        header_frame,
        variable=main_window.active_weapon_type,
        values=WEAPON_TYPES,
        command=lambda e: main_window.update_weapon_settings_display(),
        **COMBOBOX_STYLE
    )
    weapon_dropdown.pack(side="right", padx=(0, 10))

    settings_list = [
        ("Min Shot Delay", "entry", "ShotDelayMin", "Minimum delay before shooting (seconds)"),
        ("Max Shot Delay", "entry", "ShotDelayMax", "Maximum delay before shooting (seconds)"),
        ("Post Shot Delay", "entry", "PostShotDelay", "Delay after shooting (seconds)")
    ]
    
    for i, (label, widget_type, key, desc) in enumerate(settings_list):
        create_setting_item(
            section, main_window, label, desc, widget_type, key,
            trigger_config, is_last=(i == len(settings_list) - 1),
            is_weapon_specific=True,
        )
    main_window.update_weapon_settings_display(trigger_config)
def create_setting_item(
    parent,
    main_window,
    label_text,
    description,
    widget_type,
    key,
    trigger_config,
    is_last=False,
    is_weapon_specific=False,
):
    """Создает стандартизированную строку настройки с отступами."""
    item_frame = ctk.CTkFrame(parent, fg_color="transparent")
    item_frame.pack(fill="x", padx=40, pady=(0, 30 if not is_last else 40))
    
    container = ctk.CTkFrame(item_frame, **SETTING_ITEM_STYLE)
    container.pack(fill="x")
    
    content_frame = ctk.CTkFrame(container, fg_color="transparent")
    content_frame.pack(fill="x", padx=25, pady=25)
    
    create_label_and_description(content_frame, label_text, description)
    create_widget(
        content_frame,
        main_window,
        widget_type,
        key,
        trigger_config,
        is_weapon_specific,
    )

def create_label_and_description(parent, label_text, description):
    """Строит текстовое описание параметра."""
    label_frame = ctk.CTkFrame(parent, fg_color="transparent")
    label_frame.pack(side="left", fill="x", expand=True)
    
    ctk.CTkLabel(
        label_frame, text=label_text, font=FONT_ITEM_LABEL,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(fill="x", pady=(0, 4))
    
    ctk.CTkLabel(
        label_frame, text=description, font=FONT_ITEM_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY, anchor="w", wraplength=400
    ).pack(fill="x")

def create_widget(
    parent,
    main_window,
    widget_type,
    key,
    trigger_config,
    is_weapon_specific,
):
    """Генерирует и привязывает управляющий элемент к форме GUI."""
    widget_frame = ctk.CTkFrame(parent, fg_color="transparent")
    widget_frame.pack(side="right", padx=(30, 0))

    if widget_type == "entry":
        if key == "TriggerKey":
            widget = ctk.CTkEntry(widget_frame, justify="center", **ENTRY_STYLE)
        else:
            widget = ctk.CTkEntry(widget_frame, **ENTRY_STYLE)
            
        widget.bind("<FocusOut>", lambda e: main_window.save_settings())
        widget.bind("<Return>", lambda e: main_window.save_settings())
        
        if is_weapon_specific:
            if key == "ShotDelayMin": main_window.min_delay_entry = widget
            elif key == "ShotDelayMax": main_window.max_delay_entry = widget
            elif key == "PostShotDelay": main_window.post_shot_delay_entry = widget
        else:
            if key == "TriggerKey":
                main_window.trigger_key_entry = widget
                current_key = trigger_config.get("TriggerKey", "x")
                widget.delete(0, "end")
                widget.insert(0, str(current_key))
        widget.pack()

    elif widget_type == "checkbox":
        initial_val = trigger_config.get(key, False)
        var = ctk.BooleanVar(value=initial_val)
        
        if key == "ToggleMode": main_window.toggle_mode_var = var
        elif key == "AttackOnTeammates": main_window.attack_teammates_var = var
        
        widget = ctk.CTkCheckBox(
            widget_frame, text="", variable=var,
            **CHECKBOX_STYLE,
            command=main_window.save_settings
        )
        widget.pack()

def create_section_frame(parent):
    """Возвращает стилизованный контейнер подраздела."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))
    return section

def create_section_header(parent, title, subtitle):
    """Строит верхний информационный маркер блока настроек."""
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
