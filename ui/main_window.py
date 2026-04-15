from PyQt6.QtWidgets import *
from PyQt6.QtCore import QTimer

from core.frp_manager import FRPManager
from core.config_manager import ConfigManager
from ui.widgets.proxy_table import ProxyTable
from core.token_storage import TokenStorage

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
        self.addr.setReadOnly(True)
        self.port.setReadOnly(True)

        layout.addWidget(QLabel("服务器地址"))
        layout.addWidget(self.addr)
        layout.addWidget(QLabel("端口"))
        layout.addWidget(self.port)

        op_layout = QHBoxLayout()

        add_btn = QPushButton("添加隧道")
        self.save_btn = QPushButton("保存配置")

        op_layout.addWidget(add_btn)
        op_layout.addWidget(self.save_btn)

        layout.addLayout(op_layout)

        # ====== proxy表
        self.table = ProxyTable()
        layout.addWidget(self.table)

        # ===== 状态指示器
        status_layout = QHBoxLayout()

        self.status_light = QLabel("●")
        self.status_light.setStyleSheet("color: red; font-size: 20px;")

        self.status_text = QLabel("未运行")

        status_layout.addWidget(QLabel("运行状态:"))
        status_layout.addWidget(self.status_light)
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()

        layout.addLayout(status_layout)

        # ====== 日志窗口
        layout.addWidget(QLabel("运行日志"))

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(200)

        layout.addWidget(self.log_view)

        # ===== 启动/停止按钮
        run_layout = QHBoxLayout()

        self.start_btn = QPushButton("启动")
        self.stop_btn = QPushButton("停止")

        run_layout.addWidget(self.start_btn)
        run_layout.addWidget(self.stop_btn)

        layout.addLayout(run_layout)

        # ======= logout
        self.logout_btn = QPushButton("登出")
        self.logout_btn.setFixedWidth(100)
        layout.addWidget(self.logout_btn)

        # ===== 信号
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.save_btn.clicked.connect(self.save)
        add_btn.clicked.connect(self.add_proxy)
        self.logout_btn.clicked.connect(self.logout)

        # ====== 定时刷新
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(2000)

        self.load()
        self.update_all()
        self.update_buttons()

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
        self.log_view.clear()
        QMessageBox.information(self, "FRP", self.frp.start())
        self.update_all()

    def stop(self):
        msg = self.frp.stop()
        self.log_view.append("=== 已停止 ===")
        QMessageBox.information(self, "FRP", msg)
        self.update_all()

    def update_status(self):
        status = self.frp.conn_status

        if status == "connecting":
            self.status_light.setStyleSheet("color: orange; font-size: 20px;")
            self.status_text.setText("连接中")

        elif status == "connected":
            self.status_light.setStyleSheet("color: green; font-size: 20px;")
            self.status_text.setText("已连接")

        elif status == "failed":
            self.status_light.setStyleSheet("color: red; font-size: 20px;")
            self.status_text.setText("连接失败")

        else:
            self.status_light.setStyleSheet("color: gray; font-size: 20px;")
            self.status_text.setText("未运行")

    def update_all(self):
        self.update_status()
        self.update_logs()
        self.update_buttons()

    def update_logs(self):
        logs = self.frp.logs

        self.log_view.setPlainText("\n".join(logs))
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def add_proxy(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

    def logout(self):
        self.frp.stop()
        TokenStorage.clear()
        from ui.login_window import LoginWindow
        self.login = LoginWindow()
        self.login.show()
        self.close()

    def update_buttons(self):
        status = self.frp.conn_status
        if status in ["connecting", "connected"]:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
    