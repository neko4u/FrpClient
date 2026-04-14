from PyQt6.QtWidgets import *
from services.api_client import ApiClient
from core.token_holder import TokenHolder
from ui.main_window import MainWindow

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.api = ApiClient()

        self.setWindowTitle("登录")

        layout = QVBoxLayout(self)

        self.user = QLineEdit()
        self.user.setPlaceholderText("用户名")

        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn = QPushButton("登录")

        layout.addWidget(self.user)
        layout.addWidget(self.pwd)
        layout.addWidget(self.btn)

        self.btn.clicked.connect(self.login)

    def login(self):
        self.api.login(self.user.text(), self.pwd.text(), self.on_result)

    def on_result(self, data):
        if data.get("code") == 0:
            TokenHolder.set_token(data["token"], data["expires_in"])
            self.main = MainWindow()
            self.main.show()
            self.close()
        else:
            QMessageBox.warning(self, "失败", data.get("message"))