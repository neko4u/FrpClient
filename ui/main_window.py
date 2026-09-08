"""FRPClient 主窗口（会话层版）

布局（后续还会大改排版，核心功能与结构保留）：
  顶栏:  [剩余时间模块]  ...  [开启时长/暂停时长按钮]  [头像占位]
  中部:  FRP 连接区（连接/断开按钮 + 状态）
  下部:  隧道配置表 + 日志

交互规则:
  1. "开启时长"  = 建立 Django 会话(开始计费) —— 必须先开启, 才能连 FRP
  2. "暂停时长"  = 若 FRP 已连则先断开 frpc, 再关闭 Django 会话(结算)
  3. "连接/断开" = 控制 frpc(仅当 Django 会话 active 时才允许连接)
  4. 程序启动查 Django status: 有活跃会话则自动恢复倒计时
"""
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt
import os

from core.frp_manager import FRPManager
from core.config_manager import ConfigManager
from core.paths import resource_dir
from core.token_holder import TokenHolder
from core.token_storage import TokenStorage
from core.session_manager import SessionManager
from ui.widgets.proxy_table import ProxyTable


def fmt_remaining(sec):
    """秒 -> 'x天x时x分x秒'（0 -> '0秒'）"""
    sec = max(0, int(sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}天")
    if h or d:
        parts.append(f"{h}时")
    if m or h or d:
        parts.append(f"{m}分")
    parts.append(f"{s}秒")
    return "".join(parts)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FRP 面板")
        self.setGeometry(100, 100, 900, 700)

        # ===== 核心管理器 =====
        self.session = SessionManager()   # Django 会话(计费)
        self.frp = FRPManager(
            os.path.join(resource_dir(), "frpc.exe"),
            os.path.join(resource_dir(), "frpc.toml"),
            TokenHolder.get_uid()
        )
        self.cfg = ConfigManager(os.path.join(resource_dir(), "frpc.toml"))
        self.current_status = "stopped"   # frp 状态

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)

        # ================= 顶栏: 服务器信息 + (右侧) 剩余时间/时长按钮/头像 =================
        top = QHBoxLayout()

        # 左侧: 服务器信息
        self.addr_label = QLabel("服务器: -")
        top.addWidget(self.addr_label)

        top.addStretch()   # 把右侧内容推到右边

        # 剩余时间模块（右侧，时长按钮左侧）
        time_box = QHBoxLayout()
        time_box.addWidget(QLabel("剩余可用时长:"))
        self.time_label = QLabel("--")
        self.time_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        time_box.addWidget(self.time_label)
        top.addLayout(time_box)

        # 开启时长 / 暂停时长 按钮（Django 会话）
        self.session_btn = QPushButton("开启时长")
        self.session_btn.setFixedHeight(36)
        self.session_btn.setMinimumWidth(120)
        top.addWidget(self.session_btn)

        # 头像占位（后续再做）
        self.avatar_label = QLabel("")
        self.avatar_label.setFixedSize(36, 36)
        self.avatar_label.setStyleSheet(
            "border: 1px solid #ccc; border-radius: 18px;")
        top.addWidget(self.avatar_label)

        root.addLayout(top)

        # ================= FRP 连接区 =================
        frp_row = QHBoxLayout()
        frp_row.addWidget(QLabel("FRP 隧道:"))

        self.frp_btn = QPushButton("连接")
        self.frp_btn.setFixedWidth(140)
        frp_row.addWidget(self.frp_btn)

        self.status_light = QLabel("●")
        self.status_light.setStyleSheet("color: gray; font-size: 18px;")
        frp_row.addWidget(self.status_light)
        self.status_text = QLabel("未连接")
        frp_row.addWidget(self.status_text)

        frp_row.addStretch()
        self.user_label = QLabel("用户: -")
        frp_row.addWidget(self.user_label)
        root.addLayout(frp_row)

        # ================= 隧道配置(后续大改可挪 tab) =================
        self.table = ProxyTable()
        root.addWidget(self.table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加隧道")
        self.save_btn = QPushButton("保存配置")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch()
        self.logout_btn = QPushButton("登出")
        btn_row.addWidget(self.logout_btn)
        root.addLayout(btn_row)

        # ================= 日志 =================
        root.addWidget(QLabel("运行日志"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(160)
        root.addWidget(self.log_view)

        # ================= 信号绑定 =================
        self.session_btn.clicked.connect(self.toggle_session)
        self.frp_btn.clicked.connect(self.toggle_frp)
        self.save_btn.clicked.connect(self.save)
        add_btn.clicked.connect(self.add_proxy)
        self.logout_btn.clicked.connect(self.logout)

        # session 信号
        self.session.status_changed.connect(self.on_session_status)
        self.session.countdown_changed.connect(self.on_countdown)
        self.session.error.connect(self.on_session_error)
        self.session.session_closed.connect(self.on_session_closed)

        # frp 信号
        self.frp.log_signal.connect(self.append_log)
        self.frp.status_signal.connect(self.on_frp_status)

        # ================= 初始化 =================
        self.load()
        self._uid = TokenHolder.get_uid()
        self.user_label.setText(f"用户: {self._uid or '-'}")
        self._apply_ui_state()

        # 启动时检查 Django 会话状态（有则恢复倒计时）
        self.session.refresh_status()

    # ================== 配置 ==================

    def load(self):
        addr, port = self.cfg.get_basic()
        self.addr_label.setText(f"服务器: {addr}:{port}")
        self.table.load(self.cfg.get_proxies())

    def save(self):
        self.cfg.set_proxies(self.table.get_data())
        QMessageBox.information(self, "成功", "已保存")

    # ================== Django 会话(开启/暂停时长) ==================

    def toggle_session(self):
        if self.session.status == "active":
            self._pause_session()
        else:
            self._start_session()

    def _start_session(self):
        """开启时长: 先建立 Django 会话, active 后 UI 自动切换"""
        self.session.start()

    def _pause_session(self):
        """暂停时长: 先断开 frp(若连着), 再关 Django 会话结算"""
        # 规则: FRP 已连 -> 先停 frpc
        if self.current_status in ("connecting", "connected"):
            self.frp.stop()
        self.session.stop()

    # ================== FRP(连接/断开) ==================

    def toggle_frp(self):
        if self.current_status in ("connecting", "connected"):
            self.frp.stop()
            return

        # 门禁: 必须先开启 Django 时长
        if self.session.status != "active":
            QMessageBox.warning(self, "提示", "请先点击「开启时长」连接服务器")
            return
        self.frp.start()

    # ================== 日志 / 登出 ==================

    def append_log(self, line):
        self.log_view.append(line)
        if self.log_view.document().blockCount() > 500:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def add_proxy(self):
        self.table.insertRow(self.table.rowCount())

    def logout(self):
        # 登出前先断开所有连接
        if self.current_status in ("connecting", "connected"):
            self.frp.stop()
        if self.session.status == "active":
            self.session.stop()
        TokenStorage.clear()
        from ui.login_window import LoginWindow
        self.login = LoginWindow()
        self.login.show()
        self.close()

    # ================== Session 信号处理 ==================

    def on_session_status(self, status):
        self._apply_ui_state()
        if status == "error":
            # 会话错误 -> 若 frp 在跑也停掉
            if self.current_status in ("connecting", "connected"):
                self.frp.stop()

    def on_countdown(self, sec):
        if self.session.status == "active":
            self.time_label.setText(fmt_remaining(sec))
        else:
            self._show_balance_only()

    def on_session_error(self, msg):
        # 401 等鉴权失败会走这里
        if "登录" in msg or "过期" in msg or "401" in msg:
            self.time_label.setText("请重新登录")
        else:
            QMessageBox.warning(self, "会话错误", msg)
        self._apply_ui_state()

    def on_session_closed(self, info):
        """服务器关闭会话(到期/被踢) -> 同步停 frp + 提示"""
        if self.current_status in ("connecting", "connected"):
            self.frp.stop()
        balance = info.get("balance")
        reason = info.get("reason", "")
        txt = "会话已结束"
        if reason == "balance_exhausted":
            txt = "时长已用完，会话已结束"
        if balance is not None:
            txt += f"（剩余 {fmt_remaining(balance)}）"
        QMessageBox.information(self, "会话结束", txt)
        self._apply_ui_state()

    # ================== FRP 信号处理 ==================

    def on_frp_status(self, status):
        self.current_status = status
        self._apply_ui_state()

    # ================== UI 状态统一刷新 ==================

    def _apply_ui_state(self):
        """根据 session/frp 状态刷新按钮文案与指示灯"""
        # 时长按钮
        if self.session.status == "active":
            self.session_btn.setText("暂停时长")
            self.session_btn.setStyleSheet("")
            self.session_btn.setEnabled(True)
        elif self.session.status in ("connecting", "stopping"):
            self.session_btn.setText("处理中...")
            self.session_btn.setEnabled(False)
        else:
            self.session_btn.setText("开启时长")
            self.session_btn.setEnabled(True)

        # FRP 按钮
        if self.current_status in ("connecting", "connected"):
            self.frp_btn.setText("断开")
            self.frp_btn.setEnabled(True)
        else:
            self.frp_btn.setText("连接")
            self.frp_btn.setEnabled(self.session.status == "active")

        # FRP 指示灯
        if self.current_status == "connecting":
            self.status_light.setStyleSheet("color: orange; font-size: 18px;")
            self.status_text.setText("连接中")
        elif self.current_status == "connected":
            self.status_light.setStyleSheet("color: green; font-size: 18px;")
            self.status_text.setText("已连接")
        elif self.current_status == "failed":
            self.status_light.setStyleSheet("color: red; font-size: 18px;")
            self.status_text.setText("连接失败")
        else:
            self.status_light.setStyleSheet("color: gray; font-size: 18px;")
            self.status_text.setText("未连接")

        # 余额展示（非会话态时显示余额秒数）
        if self.session.status != "active":
            self._show_balance_only()

    def _show_balance_only(self):
        b = getattr(self.session, "balance", 0)
        if b > 0:
            self.time_label.setText(fmt_remaining(b))
        else:
            self.time_label.setText("--")
