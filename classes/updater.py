import logging
logger = logging.getLogger(__name__)

class Updater:
    def __init__(self, main_window):
        self.main_window = main_window
        self.is_prerelease = False
    def check_for_updates(self):
        logger.debug("Auto-update checks are skipped running from source code.")
        return False
    def handle_update(self):
        pass
