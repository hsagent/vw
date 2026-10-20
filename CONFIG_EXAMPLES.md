# 📝 Примеры новых опций конфигурации

## NoFlash - Конфигурируемый offset

Если NoFlash не работает в вашей версии CS2, попробуйте изменить offset:

### config.json
```json
{
  "NoFlash": {
    "FlashSuppressionStrength": 255.0,
    "FlashMaxAlphaOffset": -4
  }
}
```

### Возможные значения:
- `-4` - стандартный (по умолчанию)
- `+4` - альтернативный для старых билдов
- `-8` - для экспериментов
- `+8` - для экспериментов

### Как найти правильное значение:
1. Запустите CS2 в тренировочном режиме
2. Бросьте флешку себе под ноги
3. Включите NoFlash с разными offset значениями
4. Правильное значение = белый экран исчезает или становится прозрачным

---

## Performance Tuning

### Weapon Cache TTL
По умолчанию: `0.5` секунды

Если хотите увеличить точность определения смены оружия (за счет CPU):

**Файл:** `classes/memory_manager.py:47`
```python
self._weapon_cache_ttl = 0.1  # Обновление каждые 100ms
```

### Entity Detection Threshold
По умолчанию: `5` игроков для досрочной остановки

Для маленьких серверов (1v1, 2v2):

**Файл:** `classes/memory_manager.py:175`
```python
EARLY_EXIT_THRESHOLD = 2
```

### Bunnyhop Poll Rate
По умолчанию: `0.005` (200 Hz)

Для 64 tick серверов можно снизить:

**Файл:** `classes/bunnyhop.py:104`
```python
time.sleep(0.008)  # 125 Hz для 64 tick
```

Для 128 tick оставьте как есть или даже увеличьте частоту:
```python
time.sleep(0.003)  # 333 Hz для 128 tick (больше CPU)
```

---

## Troubleshooting

### Problem: ESP не находит игроков
**Решение:** Проверьте entity_entry_size

Добавьте в `memory_manager.py:209` после строки `return self.entity_entry_size`:
```python
logger.info(f"Current entity_entry_size: {self.entity_entry_size}")
```

Возможные значения: 112, 120, 128

### Problem: Triggerbot стреляет слишком быстро
**Решение:** Увеличьте задержки в config.json

```json
{
  "Trigger": {
    "WeaponSettings": {
      "Rifles": {
        "ShotDelayMin": 0.05,
        "ShotDelayMax": 0.10,
        "PostShotDelay": 0.08
      }
    }
  }
}
```

### Problem: Высокая нагрузка на CPU
**Решение:** Снизьте FPS оверлея

```json
{
  "Overlay": {
    "target_fps": 30
  }
}
```

### Problem: Requests SSL errors
**Решение:** Если firewall блокирует SSL проверку

**Файл:** `classes/utility.py:55-57` (НЕ РЕКОМЕНДУЕТСЯ!)
```python
r_off = requests.get(source_config["offsets_url"], timeout=10, verify=False)
```

**ВНИМАНИЕ:** Отключение SSL проверки снижает безопасность!

---

## Advanced: Custom Constants

### Entity Chunk Configuration
**Файл:** `classes/memory_manager.py:12-15`

Если в будущих билдах CS2 изменится структура entity list:

```python
ENTITY_INDEX_MASK = 0x7FFF   # Маска индекса (15 бит)
ENTITY_CHUNK_SHIFT = 9       # Сдвиг для chunk (512 entities per chunk)
ENTITY_CHUNK_SIZE = 0x1FF    # Размер chunk (511)
```

### Player Flags
**Файл:** `classes/bunnyhop.py:12`

```python
FL_ONGROUND = 1 << 0   # На земле
FL_DUCKING = 1 << 1    # Присел (для будущих функций)
FL_WATERJUMP = 1 << 2  # В воде
FL_FROZEN = 1 << 5     # Заморожен
```

---

## Debug Mode

Для отладки добавьте в начало `main.py`:

```python
import logging
Logger.setup_logging(level=logging.DEBUG)
```

Это включит детальное логирование всех операций.

---

## Performance Monitoring

Добавьте счетчик FPS в ESP:

**Файл:** `classes/esp.py:450` (после `start_time = time.time()`):

```python
frame_count = 0
last_fps_log = time.time()

# ... в цикле после рендеринга:

frame_count += 1
if time.time() - last_fps_log >= 5.0:
    fps = frame_count / 5.0
    logger.info(f"ESP FPS: {fps:.1f}")
    frame_count = 0
    last_fps_log = time.time()
```

---

**Последнее обновление:** v1.2.9.4  
**Дата:** 2026-10-20
