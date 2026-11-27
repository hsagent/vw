# Changelog v1.2.3.0

## Changes

- Renamed feature modules: `bunnyhop.py` to `sp.py`, `esp.py` to `es.py`,
  `noflash.py` to `nf.py`, `trigger_bot.py` to `tri_c.py`, and `triggerbot.py` to `tric.py`.
- Renamed `trigger_settings_tab.py` to `tric_settings_tab.py` and updated imports and documentation.
- Downloaded offset data now stays in memory without writing JSON files to disk.
- Removed disk cache fallback and added separate memory snapshots for each repository.
- Remove legacy `off.json` and `offsets.json` files from the managed cache when loading a network source.
- An internet connection is required to load network offsets after restarting the application.

## Validation

- 67 unit tests passed for the module renames and memory-only offset loading.
