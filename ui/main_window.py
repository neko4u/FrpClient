from PyQt6.QtWidgets import *
from PyQt6.QtCore import QTimer

from core.frp_manager import FRPManager
from core.config_manager import ConfigManager
from ui.widgets.proxy_table import ProxyTable
from core.token_storage import TokenStorage
from ui.login_window import LoginWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("FRP 面板")
        self.setGeometry(100, 100, 900, 700)

        self.frp = FRPManager(
            "resources/frpc.exe",
            "resources/frpc.toml"
        )
        self.cfg = ConfigManager("resources/frpc.toml")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ===== 基础配置
        self.addr = QLineEdit()
        self.port = QLineEdit()

        layout.addWidget(QLabel("服务器地址"))
        layout.addWidget(self.addr)
        layout.addWidget(QLabel("端口"))
        layout.addWidget(self.port)

        # ====== proxy表
        self.table = ProxyTable()
        layout.addWidget(self.table)

        add_btn = QPushButton("添加隧道")
        layout.addWidget(add_btn)

        # ======= 控制按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动")
        self.stop_btn = QPushButton("停止")
        self.save_btn = QPushButton("保存配置")
        self.logout_btn = QPushButton("登出")

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addWidget(self.logout_btn)

        layout.addLayout(btn_layout)

        # ===== 状态
        self.status = QLabel("状态: 未运行")
        layout.addWidget(self.status)

        # ===== 信号
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.save_btn.clicked.connect(self.save)
        add_btn.clicked.connect(self.add_proxy)
        self.logout_btn.clicked.connect(self.logout)

        # ====== 定时刷新
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(2000)

        self.load()

    def load(self):
        addr, port = self.cfg.get_basic()
        self.addr.setText(addr)
        self.port.setText(str(port))
        self.table.load(self.cfg.get_proxies())

    def save(self):
        self.cfg.set_basic(self.addr.text(), self.port.text())
        self.cfg.set_proxies(self.table.get_data())
        QMessageBox.information(self, "成功", "已保存")

    def start(self):
        QMessageBox.information(self, "FRP", self.frp.start())

    def stop(self):
        QMessageBox.information(self, "FRP", self.frp.stop())

    def update_status(self):
        self.status.setText(self.frp.status())

    def add_proxy(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

    def logout(self):
        self.frp.stop()
        TokenStorage.clear()
        self.login = LoginWindow()
        self.login.show()
        self.close()