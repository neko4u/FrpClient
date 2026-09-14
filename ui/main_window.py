"""FRPClient 主窗口（会话层版 · UI 重构 2026-09-09）

布局:
  顶部菜单栏:  [logo sorielconnection] ... [关于▾]
  主区:
    右上:  [剩余可用时长: X天X时X分X秒]  [开启时长/暂停时长]  [头像▾]
    中部:  服务器连接: [连接/断开] ● 状态
          本地端口: [7777] [保存]
交互:
  1. "开启时长" = 建 Django 会话(计费) — 必须先开启才能连 FRP
  2. "暂停时长" = 先停 frpc 再关会话(结算)
  3. 头像点击 -> 弹层(用户ID + 登出), 点外部自动隐藏
  4. "关于"菜单 -> 运行日志(弹窗) / 检查更新 / 意见反馈(占位)
  5. 服务器地址/隧道表/内嵌日志 均不再显示于主界面
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QLineEdit, QTextEdit,
                             QToolButton, QMenu, QMessageBox,
                             QApplication, QDialog)
from PyQt6.QtGui import QIntValidator, QPainter, QColor
from PyQt6.QtCore import Qt, QTimer, QPoint
import os

from core.frp_manager import FRPManager
from core.config_manager import ConfigManager
from core.paths import resource_dir
from core.token_holder import TokenHolder
from core.token_storage import TokenStorage
from core.session_manager import SessionManager

# 注: ProxyTable 代码保留于 ui/widgets/proxy_table.py, 当前 UI 不使用(需求4)


class FillButton(QPushButton):
    """从左到右单次填充动画按钮: 用于 frp 连接/断开等待过程

    - start_loading(text): 开始动画(禁用点击, 文字换 text)
    - stop_loading(text):  请求结束 -> 若动画未走完则等走完再切换(保证完整播放一次),
                           若已走完则立即切换
    """
    FILL_STEPS = 30            # 一次填充从 0->100% 的帧数
    FRAME_MS = 20              # 每帧间隔(20ms), 总时长 = 30*20 = 600ms

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._loading = False
        self._fill = 0.0            # 0.0 ~ 1.0, 只增不减(单次填充)
        self._pending_text = None   # 动画走完前收到的 stop 目标文本
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._step)

    # ---------- 对外 ----------

    def start_loading(self, text):
        self._loading = True
        self._fill = 0.0
        self._pending_text = None
        self.setText(text)
        self.setEnabled(False)
        self._timer.start()

    def stop_loading(self, text):
        """请求结束: 若动画未播完则记录目标文本, 播完最后一帧再切换"""
        if not self._loading:
            self.setText(text)
            self.setEnabled(True)
            self.update()
            return
        if self._fill >= 1.0:
            # 动画已播完 -> 立即切换
            self._finish(text)
        else:
            # 动画还没走完 -> 记住目标, 等走完最后一帧再 finish
            self._pending_text = text

    # ---------- 内部 ----------

    def _step(self):
        self._fill += 1.0 / self.FILL_STEPS
        if self._fill >= 1.0:
            self._fill = 1.0
            self._timer.stop()
            if self._pending_text is not None:
                self._finish(self._pending_text)
        self.update()

    def _finish(self, text):
        self._loading = False
        self.setEnabled(True)
        self.setText(text)
        self.update()

    def paintEvent(self, event):
        if not self._loading:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 背景
        p.fillRect(0, 0, w, h, QColor("#e8e8e8"))
        # 从左到右单次填充条
        fw = int(w * self._fill)
        if fw > 0:
            p.fillRect(0, 0, fw, h, QColor("#4da3ff"))
        # 文字(居中)
        p.setPen(QColor("#ffffff") if self._fill < 0.6 else QColor("#003366"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


def fmt_remaining(sec):
    """秒 -> 固定 'X天X时X分X秒'（不足也补0, 最小为 0天0时0分0秒, 永不为负）"""
    sec = max(0, int(sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}天{h}时{m}分{s}秒"


class LogWindow(QWidget):
    """独立日志窗口: 由'关于>运行日志'切换显示/隐藏"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("运行日志")
        self.setMinimumSize(560, 360)
        lay = QVBoxLayout(self)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        lay.addWidget(self.view)

    def append(self, line):
        self.view.append(line)
        if self.view.document().blockCount() > 800:
            cur = self.view.textCursor()
            cur.movePosition(cur.MoveOperation.Start)
            cur.select(cur.SelectionType.BlockUnderCursor)
            cur.removeSelectedText()
            cur.deleteChar()
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("sorielconnection")
        self.setGeometry(100, 100, 760, 480)

        # ===== 核心管理器 =====
        self.session = SessionManager()
        self.frp = FRPManager(
            os.path.join(resource_dir(), "frpc.exe"),
            os.path.join(resource_dir(), "frpc.toml"),
            TokenHolder.get_uid()
        )
        self.cfg = ConfigManager(os.path.join(resource_dir(), "frpc.toml"))
        self.current_status = "stopped"
        self.remote_port = 0            # 服务器分配的远程端口
        self.frp_host = ""              # 对外访问域名
        self._going_login = False       # 防止 401 重复触发跳转



        # 独立日志窗口(默认隐藏)
        self.log_win = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ================= 顶部菜单栏 =================
        root.addWidget(self._build_menu_bar())

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 12, 16, 12)
        root.addWidget(body, 1)

        # ================= 顶行: 剩余时间 + 时长按钮 + 头像 =================
        top = QHBoxLayout()
        top.addStretch()

        # 剩余时间模块(右侧, 固定 X天X时X分X秒)
        time_box = QHBoxLayout()
        time_box.addWidget(QLabel("剩余可用时长:"))
        self.time_label = QLabel("0天0时0分0秒")
        self.time_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;")
        time_box.addWidget(self.time_label)
        top.addLayout(time_box)

        self.session_btn = QPushButton("开启时长")
        self.session_btn.setFixedHeight(34)
        self.session_btn.setMinimumWidth(110)
        top.addWidget(self.session_btn)

        # 头像(点击弹层: 用户ID + 登出; 用 QPushButton 手动 popup, 无下箭头)
        self.avatar_btn = QPushButton("头")
        self.avatar_btn.setFixedSize(34, 34)
        self.avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.avatar_btn.setStyleSheet(
            "QPushButton{border:1px solid #bbb;border-radius:17px;"
            "background:#e8e8e8;font-size:14px;}")
        self.avatar_menu = None
        self._build_avatar_menu()
        self.avatar_btn.clicked.connect(self._popup_avatar_menu)
        top.addWidget(self.avatar_btn)

        body_lay.addLayout(top)
        body_lay.addSpacing(10)

        # ================= 服务器连接区 =================
        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("服务器连接:"))

        self.frp_btn = FillButton("连接")
        self.frp_btn.setFixedWidth(110)
        conn_row.addWidget(self.frp_btn)

        self.status_light = QLabel("●")
        self.status_light.setStyleSheet("color: gray; font-size: 16px;")
        conn_row.addWidget(self.status_light)
        self.status_text = QLabel("未连接")
        conn_row.addWidget(self.status_text)
        conn_row.addStretch()
        body_lay.addLayout(conn_row)

        # 外网访问地址（服务器分配的端口, 可复制）
        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("外网地址:"))
        self.addr_label = QLabel("--")
        self.addr_label.setStyleSheet("font-size:14px;font-weight:bold;color:#333;")
        self.addr_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        addr_row.addWidget(self.addr_label)
        self.copy_btn = QPushButton("复制")
        self.copy_btn.setFixedWidth(56)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_addr)
        addr_row.addWidget(self.copy_btn)
        addr_row.addStretch()
        body_lay.addLayout(addr_row)
        body_lay.addSpacing(8)

        # ================= 本地端口(可编辑, 仅数字) =================
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("本地端口:"))

        self.port_edit = QLineEdit()
        self.port_edit.setFixedWidth(120)
        self.port_edit.setValidator(QIntValidator(1, 65535, self))
        port_row.addWidget(self.port_edit)

        self.save_port_btn = QPushButton("保存")
        self.save_port_btn.setFixedWidth(80)
        port_row.addWidget(self.save_port_btn)

        port_row.addStretch()
        body_lay.addLayout(port_row)

        body_lay.addStretch()

        # ================= 信号绑定 =================
        self.session_btn.clicked.connect(self.toggle_session)
        self.frp_btn.clicked.connect(self.toggle_frp)
        self.save_port_btn.clicked.connect(self.save_port)

        self.session.status_changed.connect(self.on_session_status)
        self.session.countdown_changed.connect(self.on_countdown)
        self.session.error.connect(self.on_session_error)
        self.session.session_closed.connect(self.on_session_closed)

        self.frp.log_signal.connect(self.append_log)
        self.frp.status_signal.connect(self.on_frp_status)

        # ================= 初始化 =================
        self.load()
        self._apply_ui_state()

        # 启动遮罩: 等 status 数据回来再撤掉, 避免看到未加载完的页面
        self._init_loading_mask()
        self.session.initialized.connect(self._remove_loading_mask)
        self.session.refresh_status()
        self._sync_port_from_server()


    # ---------------- 启动加载遮罩 ----------------

    def _init_loading_mask(self):
        """半透明全窗遮罩 + '加载中', 置于中央部件之上"""
        mask = QWidget(self.centralWidget())
        mask.setStyleSheet("background: rgba(255,255,255,0.88);")
        lay = QVBoxLayout(mask)
        lab = QLabel("加载中...")
        lab.setStyleSheet("font-size:22px;color:#555;background:transparent;")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lab)
        mask.setGeometry(self.centralWidget().rect())
        mask.show()
        mask.raise_()
        self._loading_mask = mask

    def _remove_loading_mask(self):
        if getattr(self, "_loading_mask", None) is not None:
            self._loading_mask.hide()
            self._loading_mask.deleteLater()
            self._loading_mask = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        m = getattr(self, "_loading_mask", None)
        if m is not None and self.centralWidget() is not None:
            m.setGeometry(self.centralWidget().rect())

    # ---------------- 顶部菜单栏 ----------------

    def _build_menu_bar(self):
        bar = QWidget()
        bar.setStyleSheet("background:#f0f0f0;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)

        # logo + 软件名
        logo = QLabel("⬡  sorielconnection")
        logo.setStyleSheet("font-size:15px;font-weight:bold;color:#333;")
        lay.addWidget(logo)

        lay.addSpacing(18)

        # "关于" 下拉菜单(靠左, logo 右侧)
        about_btn = QToolButton()
        about_btn.setText("关于")
        about_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        about_btn.setArrowType(Qt.ArrowType.DownArrow)
        about_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        about_btn.setStyleSheet(
            "QToolButton{border:none;font-size:13px;color:#333;padding:2px 6px;}"
            "QToolButton::menu-indicator{image:none;}")
        menu = QMenu(about_btn)
        act_log = menu.addAction("运行日志")
        menu.addSeparator()
        act_update = menu.addAction("检查更新")
        act_feedback = menu.addAction("意见反馈")
        act_update.setEnabled(False)     # 占位(仅UI)
        act_feedback.setEnabled(False)   # 占位(仅UI)
        about_btn.setMenu(menu)
        act_log.triggered.connect(self.toggle_log_window)
        lay.addWidget(about_btn)

        lay.addStretch()
        return bar

    def _build_avatar_menu(self):
        """头像弹层: 用户ID + 登出; 点击外部自动隐藏"""
        menu = QMenu(self.avatar_btn)
        uid = TokenHolder.get_uid() or "-"
        act_uid = menu.addAction(f"用户ID: {uid}")
        act_uid.setEnabled(False)
        menu.addSeparator()
        act_logout = menu.addAction("登出")
        act_logout.triggered.connect(self.logout)
        self.avatar_menu = menu

    def _popup_avatar_menu(self):
        """在头像正下方弹出菜单(无箭头按钮)"""
        pos = self.avatar_btn.mapToGlobal(
            self.avatar_btn.rect().bottomLeft() + QPoint(0, 4))
        self.avatar_menu.popup(pos)

    # ---------------- 配置 ----------------

    def load(self):
        port = self.cfg.get_local_port()
        self.port_edit.setText(str(port))

    def save_port(self):
        """保存本地端口到 frpc.toml, 仅提示, 不自动重连"""
        text = self.port_edit.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, "提示", "本地端口只能输入数字")
            return
        port = int(text)
        if not (1 <= port <= 65535):
            QMessageBox.warning(self, "提示", "端口范围 1-65535")
            return
        self.cfg.set_local_port(port)
        QMessageBox.information(self, "提示", "保存成功！请重新连接")

    # ---------------- Django 会话(开启/暂停时长) ----------------

    def toggle_session(self):
        if self.session.status == "active":
            self._pause_session()
        else:
            self._start_session()

    def _start_session(self):
        self._show_loading()
        self.session.start()

    def _pause_session(self):
        self._show_loading()
        if self.current_status in ("connecting", "connected"):
            self._release_port_async()   # 先释放端口, 再停 frpc
            self.frp.stop()
        self.session.stop()


    # ---------------- FRP(连接/断开) ----------------

    def toggle_frp(self):
        if self.current_status in ("connecting", "connected"):
            # 断开中: 动画 + 禁用 -> 停 frpc + 释放端口
            self.frp_btn.start_loading("关闭中...")
            self._release_port_async()
            self.frp.stop()
            return
        if self.session.status != "active":
            QMessageBox.warning(self, "提示", "请先点击「开启时长」连接服务器")
            return
        # 连接: 先向服务器申请端口 -> 写入 frpc.toml -> 启动 frpc
        self.frp_btn.start_loading("连接中...")
        try:
            self.session.api.allocate_port(TokenHolder.get_token(), self._on_allocate_done)
        except Exception as e:
            self.frp_btn.stop_loading("连接")
            QMessageBox.warning(self, "提示", f"端口申请失败: {e}")

    # ---------------- 远程端口 ----------------

    def _on_allocate_done(self, data):
        """端口分配回调"""
        if data.get("code") == 401:
            self.frp_btn.stop_loading("连接")
            self._back_to_login(data.get("msg") or "登录已过期，请重新登录")
            return
        if data.get("code") != 0:

            self.frp_btn.stop_loading("连接")
            msg = data.get("msg") or data.get("message") or "端口分配失败"
            QMessageBox.warning(self, "提示", msg)
            return
        port = data.get("remote_port") or 0
        if not port:
            self.frp_btn.stop_loading("连接")
            QMessageBox.warning(self, "提示", "未获取到可用端口，请稍后重试")
            return
        self.remote_port = port
        self.frp_host = data.get("host") or "ai.sorielflow.com"
        try:
            self.cfg.set_remote_port(port)      # 覆盖 frpc.toml 的 remotePort
        except Exception as e:
            print("写入 remotePort 失败:", e)
        self._update_addr_label()
        self.frp.start()

    def _release_port_async(self):
        """断开时释放端口（异步, 不阻塞 UI）"""
        try:
            self.session.api.release_port(TokenHolder.get_token(), self._on_release_done)
        except Exception:
            pass

    def _on_release_done(self, data):
        self.remote_port = 0
        self._update_addr_label()

    def _sync_port_from_server(self):
        """启动/恢复时同步服务器上的端口"""
        try:
            self.session.api.current_port(TokenHolder.get_token(), self._on_port_sync)
        except Exception:
            pass

    def _on_port_sync(self, data):
        if data.get("code") == 401:
            self._back_to_login(data.get("msg") or "登录已过期，请重新登录")
            return
        if data.get("code") == 0:

            port = data.get("remote_port") or 0
            if port:
                self.remote_port = port
                self.frp_host = data.get("host") or ""
                self._update_addr_label()

    def _update_addr_label(self):
        if self.remote_port:
            host = self.frp_host or "ai.sorielflow.com"
            self.addr_label.setText(f"{host}:{self.remote_port}")
            self.copy_btn.setEnabled(True)
        else:
            self.addr_label.setText("--")
            self.copy_btn.setEnabled(False)

    def copy_addr(self):
        """复制完整的外网地址(域名:端口)"""
        text = self.addr_label.text()
        if text and text != "--":
            QApplication.clipboard().setText(text)
            self.status_text.setText("地址已复制")


    # ---------------- 日志(独立窗口, toggle) ----------------

    def append_log(self, line):
        if self.log_win is not None:
            self.log_win.append(line)

    def toggle_log_window(self):
        if self.log_win is None:
            self.log_win = LogWindow()
            # 补显历史日志
            for line in getattr(self.frp, "logs", [])[-200:]:
                self.log_win.append(line)
            self.log_win.show()
        elif self.log_win.isVisible():
            self.log_win.hide()
        else:
            self.log_win.show()
            self.log_win.raise_()

    # ---------------- 登出 ----------------

    def logout(self):
        if self.current_status in ("connecting", "connected"):
            self._release_port_async()
            self.frp.stop()
        if self.session.status == "active":
            self.session.stop()

        TokenStorage.clear()
        from ui.login_window import LoginWindow
        self.login = LoginWindow()
        self.login.show()
        self.close()

    # ---------------- Session 信号 ----------------

    def on_session_status(self, status):
        self._apply_ui_state()
        if status == "active":
            self._sync_port_from_server()
        if status == "error" and self.current_status in ("connecting", "connected"):
            self.frp.stop()


    def on_countdown(self, sec):
        # 恢复正式样式
        self.time_label.setStyleSheet(
            "font-size:18px;font-weight:bold;color:black;")
        if self.session.status == "active":
            self.time_label.setText(fmt_remaining(sec))
        else:
            self._show_balance_only()

    def _back_to_login(self, msg="登录已过期，请重新登录"):
        """token 失效 -> 清凭据并退回登录页"""
        if self._going_login:
            return
        self._going_login = True
        try:
            if self.current_status in ("connecting", "connected"):
                self.frp.stop()
        except Exception:
            pass
        TokenStorage.clear()
        TokenHolder.set_token("", 0)
        TokenHolder.set_uid("")
        QMessageBox.warning(self, "提示", msg)
        from ui.login_window import LoginWindow
        self.login = LoginWindow()
        self.login.show()
        self.close()

    def on_session_error(self, msg):
        if "登录" in msg or "过期" in msg or "401" in msg:
            self._back_to_login(msg)
            return
        QMessageBox.warning(self, "会话错误", msg)
        self._apply_ui_state()


    def on_session_closed(self, info):
        if self.current_status in ("connecting", "connected"):
            self.frp.stop()
        self._release_port_async()       # 会话结束 -> 释放端口
        balance = info.get("balance")

        reason = info.get("reason", "")
        txt = "会话已结束"
        if reason == "balance_exhausted":
            txt = "时长已用完，会话已结束"
        if balance is not None:
            txt += f"（剩余 {fmt_remaining(balance)}）"
        QMessageBox.information(self, "会话结束", txt)
        self._apply_ui_state()

    # ---------------- FRP 信号 ----------------

    def on_frp_status(self, status):
        """frpc 状态变化 -> 驱动按钮动画/文本"""
        self.current_status = status

        if status == "connecting":
            # 连接中: 若按钮未在动画则启动(兜底), 保持禁用
            if not self.frp_btn._loading:
                self.frp_btn.start_loading("连接中...")
        elif status == "connected":
            # 成功 -> 结束动画, 显示"断开"
            self.frp_btn.stop_loading("断开")
        elif status == "failed":
            # 失败 -> 结束动画, 恢复"连接"
            self.frp_btn.stop_loading("连接")
        elif status == "stopped":
            # 停止(主动断开/进程退出) -> 结束动画, 恢复"连接"
            self.frp_btn.stop_loading("连接")

        self._apply_ui_state()

    # ---------------- UI 状态统一刷新 ----------------

    def _apply_ui_state(self):
        # 时长按钮
        if self.session.status == "active":
            self.session_btn.setText("暂停时长")
            self.session_btn.setStyleSheet(
                "background:#ffd9d9;font-weight:bold;")   # 淡红=已连接时长
            self.session_btn.setEnabled(True)
        elif self.session.status in ("connecting", "stopping"):
            self.session_btn.setText("处理中...")
            self.session_btn.setStyleSheet("")
            self.session_btn.setEnabled(False)
        else:
            self.session_btn.setText("开启时长")
            self.session_btn.setStyleSheet("")
            self.session_btn.setEnabled(True)

        # FRP 连接按钮(动画期间不干预文本, 只控制可用性)
        if self.frp_btn._loading:
            self.frp_btn.setEnabled(False)
        elif self.current_status in ("connecting", "connected"):
            self.frp_btn.setText("断开")
            self.frp_btn.setEnabled(True)
        else:
            self.frp_btn.setText("连接")
            self.frp_btn.setEnabled(self.session.status == "active")

        # 指示灯
        if self.current_status == "connecting":
            self.status_light.setStyleSheet("color: orange; font-size: 16px;")
            self.status_text.setText("连接中")
        elif self.current_status == "connected":
            self.status_light.setStyleSheet("color: green; font-size: 16px;")
            self.status_text.setText("已连接")
        elif self.current_status == "failed":
            self.status_light.setStyleSheet("color: red; font-size: 16px;")
            self.status_text.setText("连接失败")
        else:
            self.status_light.setStyleSheet("color: gray; font-size: 16px;")
            self.status_text.setText("未连接")

        # 时间显示: connecting/stopping -> 加载中; idle -> 余额; active -> 倒计时
        if self.session.status in ("connecting", "stopping"):
            self._show_loading()
        elif self.session.status != "active":
            self._show_balance_only()

    def _show_balance_only(self):
        b = getattr(self.session, "balance", 0)
        self.time_label.setText(fmt_remaining(b))
        self.time_label.setStyleSheet(
            "font-size:18px;font-weight:bold;color:black;")

    def _show_loading(self):
        self.time_label.setText("加载中...")
        self.time_label.setStyleSheet(
            "font-size:18px;font-weight:bold;color:gray;")
