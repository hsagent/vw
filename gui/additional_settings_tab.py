import customtkinter as ctk
from classes.config_manager import ConfigManager
from classes.logger import Logger
from gui.theme import (
    FONT_TITLE, FONT_SUBTITLE, FONT_SECTION_TITLE, FONT_SECTION_DESCRIPTION,
    FONT_ITEM_LABEL, FONT_ITEM_DESCRIPTION,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
    SECTION_STYLE, SETTING_ITEM_STYLE, ENTRY_STYLE, SLIDER_STYLE
)

logger = Logger.get_logger(__name__)

def populate_additional_settings(main_window, frame):
    """Инициализирует и строит вкладку дополнительных настроек Bunnyhop и NoFlash."""
    settings = ctk.CTkScrollableFrame(frame, fg_color="transparent")
    settings.pack(fill="both", expand=True, padx=40, pady=40)
    
    # Оптимизируем скорость вертикальной прокрутки меню
    settings._parent_canvas.configure(yscrollincrement=12)
    
    title_frame = ctk.CTkFrame(settings, fg_color="transparent")
    title_frame.pack(fill="x", pady=(0, 40))
    
    ctk.CTkLabel(
        title_frame, text="⚡  Additional Settings", font=FONT_TITLE,
        text_color=COLOR_TEXT_PRIMARY, anchor="w"
    ).pack(side="left")
    
    ctk.CTkLabel(
        title_frame, text="Configure Bunnyhop and NoFlash preferences", font=FONT_SUBTITLE,
        text_color=COLOR_TEXT_SECONDARY, anchor="w"
    ).pack(side="left", padx=(20, 0), pady=(10, 0))
    
    # Генерируем подразделы функций
    create_bunnyhop_config_section(main_window, settings)
    create_noflash_config_section(main_window, settings)

def create_bunnyhop_config_section(main_window, parent):
    """Создает подраздел конфигурации Bunnyhop."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))
    
    header = ctk.CTkFrame(section, fg_color="transparent")
    header.pack(fill="x", padx=40, pady=(40, 30))
    
    ctk.CTkLabel(header, text="🐰  Bunnyhop Configuration", font=FONT_SECTION_TITLE, text_color=COLOR_TEXT_PRIMARY, anchor="w").pack(side="left")
    ctk.CTkLabel(header, text="Control Bunnyhop behavior", font=FONT_SECTION_DESCRIPTION, text_color=COLOR_TEXT_SECONDARY, anchor="e").pack(side="right")
    
    settings_list = [
        ("Jump Key", "entry", "JumpKey", "Key to activate Bunnyhop (e.g., 'space' or 'mouse4')"),
        ("Jump Delay", "entry", "JumpDelay", "Delay between jumps in seconds (0.01-0.5)")
    ]
    
    for i, (label_text, widget_type, key, description) in enumerate(settings_list):
        create_setting_item(section, label_text, description, widget_type, key, main_window, is_last=(i == len(settings_list) - 1))

def create_noflash_config_section(main_window, parent):
    """Создает подраздел конфигурации NoFlash."""
    section = ctk.CTkFrame(parent, **SECTION_STYLE)
    section.pack(fill="x", pady=(0, 30))
    
    header = ctk.CTkFrame(section, fg_color="transparent")
    header.pack(fill="x", padx=40, pady=(40, 30))
    
    ctk.CTkLabel(header, text="🌞  NoFlash Configuration", font=FONT_SECTION_TITLE, text_color=COLOR_TEXT_PRIMARY, anchor="w").pack(side="left")
    ctk.CTkLabel(header, text="Control flash suppression behavior", font=FONT_SECTION_DESCRIPTION, text_color=COLOR_TEXT_SECONDARY, anchor="e").pack(side="right")
    
    settings_list = [
        ("Flash Suppression Strength", "slider", "FlashSuppressionStrength", "Strength of flash suppression (0.0-255.0) | 255.0 = Default, 0.0 = Safe NoFlash")
    ]
    
    for i, (label_text, widget_type, key, description) in enumerate(settings_list):
        create_setting_item(section, label_text, description, widget_type, key, main_window, is_last=(i == len(settings_list) - 1))
def create_setting_item(parent, label_text, description, widget_type, key, main_window, is_last=False):
    """Создает стандартизированную строку настройки с текстовым описанием и виджетом."""
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
            current_key = ConfigManager.get_value("Bunnyhop", "JumpKey", default="space")
            widget.delete(0, "end")
            widget.insert(0, str(current_key))
            widget.bind("<FocusOut>", lambda e: main_window.save_settings())
            widget.bind("<Return>", lambda e: main_window.save_settings())
        elif key == "JumpDelay":
            main_window.jump_delay_entry = widget
            current_delay = ConfigManager.get_value("Bunnyhop", "JumpDelay", default=0.01)
            widget.delete(0, "end")
            widget.insert(0, str(current_delay))
            widget.bind("<FocusOut>", lambda e: main_window.save_settings())
            widget.bind("<Return>", lambda e: main_window.save_settings())
        widget.pack()
    
    elif widget_type == "slider":
        slider_container = ctk.CTkFrame(widget_frame, fg_color="transparent")
        slider_container.pack()
        
        value_frame = ctk.CTkFrame(slider_container, corner_radius=8, fg_color=("#e2e8f0", "#374151"), width=60, height=35)
        value_frame.pack(side="right", padx=(15, 0))
        value_frame.pack_propagate(False)
        
        # Получаем значение альфа-канала ослепления из конфига (дефолт 255.0 - обычный белый экран)
        current_strength = float(ConfigManager.get_value("NoFlash", "FlashSuppressionStrength", default=255.0))
        
        value_label = ctk.CTkLabel(value_frame, text=f"{current_strength:.0f}", font=FONT_ITEM_LABEL, text_color=COLOR_TEXT_PRIMARY)
        value_label.pack(expand=True)
        
        # Диапазон изменен до 255.0 под логику m_flFlashMaxAlpha в Source 2
        widget = ctk.CTkSlider(
            slider_container,
            from_=0.0,
            to=255.0,
            number_of_steps=255,
            command=lambda e: update_slider_value(e, key, main_window),
            **SLIDER_STYLE
        )
        widget.set(current_strength)
        widget.pack(side="left")
        
        widget.value_label = value_label
        main_window.__setattr__(f"{key}_slider", widget)
        main_window.__setattr__(f"{key}_value_label", value_label)

    return item_frame

def update_slider_value(value, key, main_window):
    """Обновляет числовой маркер ползунка и безопасно сохраняет настройки NoFlash."""
    slider = getattr(main_window, f"{key}_slider", None)
    if slider and hasattr(slider, 'value_label'):
        slider.value_label.configure(text=f"{value:.0f}")
        
        # Откладываем запись до окончания движения, чтобы не писать JSON
        # на каждый пиксель перемещения ползунка.
        timer = getattr(main_window, "_noflash_save_timer", None)
        if timer is not None:
            main_window.root.after_cancel(timer)
        def save_value():
            saved = ConfigManager.set_value("NoFlash", key, value=float(value))
            if not saved:
                logger.error("Не удалось сохранить параметр NoFlash.%s", key)
                return
            if hasattr(main_window, 'client_manager'):
                current_config = ConfigManager.load_config()
                main_window.client_manager.update_running_feature_configs(current_config)
        main_window._noflash_save_timer = main_window.root.after(250, save_value)
