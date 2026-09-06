from PyQt6.QtWidgets import *
import os
from services.api_client import ApiClient
from core.token_holder import TokenHolder
from ui.main_window import MainWindow
from core.token_storage import TokenStorage
from core.config_manager import ConfigManager
from core.paths import resource_dir
from core.jwt_utils import get_uid_from_token


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

        token = TokenStorage.load()
        if token:
            from core.token_holder import TokenHolder
            TokenHolder.set_token(token, 0)

            self.main = MainWindow()
            self.main.show()
            self.close()

    def login(self):
        self.api.login(self.user.text(), self.pwd.text(), self.on_result)


    def on_result(self, data):
        if data.get("code") == 0:
            token = data["token"]
            from core.token_holder import TokenHolder

            TokenHolder.set_token(data["token"], data["expires_in"])
            TokenHolder.set_uid(get_uid_from_token(token))
            TokenStorage.save(token, expires_in_days=7)


            # 登录成功后立即从 API 拉取 frp token 写入 frpc.toml,保证开箱即用
            try:
                cfg = ConfigManager(os.path.join(resource_dir(), "frpc.toml"))
                cfg.update_token_from_api(token)
            except Exception as e:
                print("更新 frp token 失败:", e)

            self.main = MainWindow()
            self.main.show()
            self.close()
        else:
            QMessageBox.warning(self, "失败", data.get("message"))