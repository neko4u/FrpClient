from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt
import os
from services.api_client import ApiClient
from core.token_holder import TokenHolder
from ui.main_window import MainWindow
from core.token_storage import TokenStorage
from core.config_manager import ConfigManager
from core.paths import resource_dir
from core.jwt_utils import get_uid_from_token
from ui.frosted import apply_frosted

INPUT_QSS = """
QLineEdit{
    background:#ffffff;
    border:1px solid #e1e5ec;
    border-radius:10px;
    padding:0 16px;
    font-size:14px;
    color:#2b3445;
}
QLineEdit:focus{border:1px solid #12b7f5;}
QLineEdit:disabled{background:#f2f4f7;color:#aab2bf;}
"""

BUTTON_QSS = """
QPushButton{
    background:#12b7f5;
    color:#ffffff;
    border:none;
    border-radius:10px;
    font-size:16px;
    font-weight:bold;
}
QPushButton:hover{background:#3cc4f8;}
QPushButton:pressed{background:#0ea5df;}
QPushButton:disabled{background:#9fd9f2;color:#ffffff;}
"""


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.api = ApiClient()

        self.setWindowTitle("登录")

        # 磨砂玻璃: 客户区透出系统材质, 系统标题栏与按钮保留
        apply_frosted(self)

        self.setFixedSize(420, 560)          # QQ 登录窗尺寸量级

        layout = QVBoxLayout(self)
        layout.setContentsMargins(46, 30, 46, 40)
        layout.setSpacing(0)

        # ===== 顶部标题区 =====
        self.logo = QLabel("sorielconnection")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setStyleSheet(
            "font-size:24px;font-weight:bold;color:#1a2b4b;background:transparent;")
        layout.addWidget(self.logo)


        layout.addSpacing(36)

        # ===== 用户名 =====
        self.user = QLineEdit()
        self.user.setPlaceholderText("用户名")
        self.user.setFixedHeight(46)
        self.user.setStyleSheet(INPUT_QSS)
        layout.addWidget(self.user)

        layout.addSpacing(16)

        # ===== 密码 =====
        self.pwd = QLineEdit()
        self.pwd.setPlaceholderText("密码")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd.setFixedHeight(46)
        self.pwd.setStyleSheet(INPUT_QSS)
        layout.addWidget(self.pwd)

        layout.addSpacing(28)

        # ===== 登录按钮 =====
        self.btn = QPushButton("登录")
        self.btn.setFixedHeight(46)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(BUTTON_QSS)
        layout.addWidget(self.btn)

        layout.addStretch()


        self.btn.clicked.connect(self.login)

        token = TokenStorage.load()
        if token:
            from core.token_holder import TokenHolder
            TokenHolder.set_token(token, 0)

            self.main = MainWindow()
            self.main.show()
            self.close()

    def login(self):
        # 请求期间禁用交互, 防止重复提交/误操作
        self._set_busy(True)
        self.api.login(self.user.text(), self.pwd.text(), self.on_result)

    def _set_busy(self, busy):
        """busy=True: 禁用输入与按钮并显示'登录中...'; False: 恢复"""
        for w in (self.user, self.pwd, self.btn):
            w.setEnabled(not busy)
        if busy:
            self.btn.setText("登录中...")
        else:
            self.btn.setText("登录")

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
            # 失败: 恢复交互并提示
            self._set_busy(False)
            QMessageBox.warning(self, "失败", data.get("message"))
