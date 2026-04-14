import sys
from PyQt6.QtWidgets import QApplication
from ui.login_window import LoginWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    win = LoginWindow()
    win.show()

    sys.exit(app.exec())