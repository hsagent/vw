import customtkinter as ctk
from gui.theme import (
    FONT_TITLE, FONT_SUBTITLE, FONT_SECTION_TITLE, FONT_SECTION_DESCRIPTION,
    FONT_ITEM_LABEL, FONT_ITEM_DESCRIPTION,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
    SECTION_STYLE, SETTING_ITEM_STYLE, ENTRY_STYLE, SLIDER_STYLE
)

def populate_additional_settings(main_window, frame):
    """Populate the additional settings frame with configuration options for Bunnyhop and NoFlash."""
    # Create a scrollable container for settings
    settings = ctk.CTkScrollableFrame(
        frame,
        fg_color="transparent"
    )
    settings.pack(fill="both", expand=True, padx=40, pady=40)
    
    # Configure faster scroll speed by modifying canvas
    settings._parent_canvas.configure(yscrollincrement=5)
    
    # Frame for page title and subtitle
    title_frame = ctk.CTkFrame(settings, fg_color="transparent")
    title_frame.pack(fill="x", pady=(0, 40))
    
    # Settings title with an icon
    title_label = ctk.CTkLabel(
        title_frame,
        text="⚡  Additional Settings",
        font=FONT_TITLE,
        text_color=COLOR_TEXT_PRIMARY,
        anchor="w"
    )
    title_label.pack(side="left")
    
    # Subtitle providing context
    subtitle_label = ctk.CTkLabel(
        title_frame,
        text="Configure Bunnyhop and NoFlash preferences",
        font=FONT_SUBTITLE,
        text_color=COLOR_TEXT_SECONDARY,
        anchor="w"
    )
    subtitle_label.pack(side="left", padx=(20, 0), pady=(10, 0))
    
    # Create sections for Bunnyhop and NoFlash settings
    create_bunnyhop_config_section(main_window, settings)
    create_noflash_config_section(main_window, settings)

def create_bunnyhop_config_section(main_window, parent):
    """Create Bunnyhop configuration section with related settings."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))
    
    header = ctk.CTkFrame(section, fg_color="transparent")
    header.pack(fill="x", padx=40, pady=(40, 30))
    
    ctk.CTkLabel(
        header,
        text="🐰  Bunnyhop Configuration",
        font=FONT_SECTION_TITLE,
        text_color=COLOR_TEXT_PRIMARY,
        anchor="w"
    ).pack(side="left")
    
    ctk.CTkLabel(
        header,
        text="Control Bunnyhop behavior",
        font=FONT_SECTION_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY,
        anchor="e"
    ).pack(side="right")
    
    settings_list = [
        ("Jump Key", "entry", "JumpKey", "Key to activate Bunnyhop (e.g., 'space' or 'mouse4')"),
        ("Jump Delay", "entry", "JumpDelay", "Delay between simulated jumps in ticks/seconds (0.01-0.5)")
    ]
    
    for i, (label_text, widget_type, key, description) in enumerate(settings_list):
        item_frame = create_setting_item(
            section, 
            label_text, 
            description, 
            widget_type, 
            key, 
            main_window,
            is_last=(i == len(settings_list) - 1)
        )
def create_noflash_config_section(main_window, parent):
    """Create NoFlash configuration section with related settings."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))
    
    header = ctk.CTkFrame(section, fg_color="transparent")
    header.pack(fill="x", padx=40, pady=(40, 30))
    
    ctk.CTkLabel(
        header,
        text="🌞  NoFlash Configuration",
        font=FONT_SECTION_TITLE,
        text_color=COLOR_TEXT_PRIMARY,
        anchor="w"
    ).pack(side="left")
    
    ctk.CTkLabel(
        header,
        text="Control flash suppression behavior",
        font=FONT_SECTION_DESCRIPTION,
        text_color=COLOR_TEXT_SECONDARY,
        anchor="e"
    ).pack(side="right")
    
    # ИСПРАВЛЕНИЕ: Описание изменено на секунды ослепления для синхронизации с памятью игры
    settings_list = [
        ("Flash Suppression Strength", "slider", "FlashSuppressionStrength", "Maximum flash duration in seconds (0.0s = Full NoFlash, 4.5s = Default)")
    ]
    
    for i, (label_text, widget_type, key, description) in enumerate(settings_list):
        item_frame = create_setting_item(
            section, 
            label_text, 
            description, 
            widget_type, 
            key, 
            main_window,
            is_last=(i == len(settings_list) - 1)
        )

def create_setting_item(parent, label_text, description, widget_type, key, main_window, is_last=False):
    """Create a standardized setting item with improved styling."""
    item_frame = ctk.CTkFrame(parent, fg_color="transparent")
    item_frame.pack(fill="x", padx=40, pady=(0, 30 if not is_last else 40))
    
    container = ctk.CTkFrame(item_frame, **SETTING_ITEM_STYLE)
    container.pack(fill="x", pady=(0, 0))
    
    content_frame = ctk.CTkFrame(container, fg_color="transparent")
    content_frame.pack(fill="x", padx=25, pady=25)
    
    label_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    label_frame.pack(side="left", fill="x", expand=True)
    
    ctk.CTkLabel(label_frame, text=label_text, font=FONT_ITEM_LABEL, text_color=COLOR_TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(0, 4))
    ctk.CTkLabel(label_frame, text=description, font=FONT_ITEM_DESCRIPTION, text_color=COLOR_TEXT_SECONDARY, anchor="w", wraplength=400).pack(fill="x")
    
    widget_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
    widget_frame.pack(side="right", padx=(30, 0))
    
    if widget_type == "entry":
        widget = ctk.CTkEntry(widget_frame, justify="center", **ENTRY_STYLE)
        if key == "JumpKey":
            main_window.jump_key_entry = widget
            widget.insert(0, main_window.bunnyhop.config.get('Bunnyhop', {}).get('JumpKey', 'space'))
            widget.bind("<FocusOut>", lambda e: main_window.save_settings())
            widget.bind("<Return>", lambda e: main_window.save_settings())
        elif key == "JumpDelay":
            main_window.jump_delay_entry = widget
            widget.insert(0, str(main_window.bunnyhop.config.get('Bunnyhop', {}).get('JumpDelay', 0.015)))
            widget.bind("<FocusOut>", lambda e: main_window.save_settings())
            widget.bind("<Return>", lambda e: main_window.save_settings())
        widget.pack()
    
    elif widget_type == "slider":
        slider_container = ctk.CTkFrame(widget_frame, fg_color="transparent")
        slider_container.pack()
        
        value_frame = ctk.CTkFrame(slider_container, corner_radius=8, fg_color=("#e2e8f0", "#374151"), width=60, height=35)
        value_frame.pack(side="right", padx=(15, 0))
        value_frame.pack_propagate(False)
        
        value_label = ctk.CTkLabel(
            value_frame,
            text=f"{main_window.noflash.config['NoFlash'].get(key, 0.0):.1f}s",
            font=FONT_ITEM_LABEL,
            text_color=COLOR_TEXT_PRIMARY
        )
        value_label.pack(expand=True)
        
        # ИСПРАВЛЕНИЕ: Диапазон слайдера изменен на 0.0 - 5.0 секунд ослепления 
        # (вместо старых некорректных 0-100 процентов)
        widget = ctk.CTkSlider(
            slider_container,
            from_=0.0,
            to=5.0,
            number_of_steps=50,
            command=lambda e: update_slider_value(e, key, main_window),
            **SLIDER_STYLE
        )
        widget.set(main_window.noflash.config["NoFlash"].get(key, 0.0))
        widget.pack(side="left")
        
        widget.value_label = value_label
        main_window.__setattr__(f"{key}_slider", widget)
        main_window.__setattr__(f"{key}_value_label", value_label)

    return item_frame

def update_slider_value(event, key, main_window):
    """Update the slider value label and save settings."""
    slider_attr = main_window.__getattribute__(f"{key}_slider")
    value = round(slider_attr.get(), 1)
    slider_attr.value_label.configure(text=f"{value:.1f}s")
    
    # Записываем значение и делаем бесшумное сохранение без фризов
    if main_window.noflash.config["NoFlash"][key] != value:
        main_window.noflash.config["NoFlash"][key] = value
        main_window.save_settings(show_message=False)
