import sys
import os
from PyQt6.QtWidgets import QApplication

from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from core.token_storage import TokenStorage
from core.token_holder import TokenHolder
from core.jwt_utils import get_uid_from_token

from core.api_client import APIs
from core.config_manager import ConfigManager
from core.paths import ensure_resources, resource_dir

if __name__ == "__main__":
    ensure_resources()
    app = QApplication(sys.argv)
    token = TokenStorage.load()

    if token:
        TokenHolder.set_token(token, 0)
        TokenHolder.set_uid(get_uid_from_token(token))
        config_mgr = ConfigManager(os.path.join(resource_dir(), "frpc.toml"))

        config_mgr.update_token_from_api(token)
        window = MainWindow()
    else:
        window = LoginWindow()

    window.show()

    sys.exit(app.exec())