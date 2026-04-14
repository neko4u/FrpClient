import sys
from PyQt6.QtWidgets import QApplication

from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from core.token_storage import TokenStorage
from core.token_holder import TokenHolder

if __name__ == "__main__":
    app = QApplication(sys.argv)
    token = TokenStorage.load()

    if token:
        TokenHolder.set_token(token, 0)
        window = MainWindow()
    else:
        window = LoginWindow()

    window.show()

    sys.exit(app.exec())