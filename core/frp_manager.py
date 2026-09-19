from PyQt6.QtCore import QProcess, QObject, QTimer, pyqtSignal
import os

CONNECT_TIMEOUT_MS = 20 * 1000   # 启动后 20s 仍未登录成功 -> 判定连接失败(避免卡在"连接中...")
STOP_KILL_MS = 3 * 1000          # terminate 后 3s 仍未退出 -> 强杀


class FRPManager(QObject):
    # ===== 信号 =====
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)      # stopped / connecting / connected / failed

    def __init__(self, frpc_path, config_path, uid=""):
        super().__init__()

        self.frpc_path = frpc_path
        self.config_path = config_path
        self.uid = uid

        self.process = QProcess()
        self.logs = []
        self.conn_status = "stopped"     # stopped / connecting / connected / failed
        self._stopping = False           # 是否是我们主动 stop(用于忽略 kill 产生的 Crashed)

        # 连接看门狗: 长时间停在 connecting 也要给出终态
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.setInterval(CONNECT_TIMEOUT_MS)
        self._connect_timer.timeout.connect(self._on_connect_timeout)

        # ===== 绑定信号 =====
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)

    # ===== 对外 =====

    def is_running(self):
        return self.process.state() == QProcess.ProcessState.Running

    def start(self):
        if self.process.state() == QProcess.ProcessState.Running:
            return "已运行"

        if not os.path.exists(self.frpc_path):
            self.log_signal.emit("[ERROR] frpc 不存在: %s" % self.frpc_path)
            self._set_status("failed")
            return "frpc.exe 不存在"

        self.logs = []
        self._set_status("connecting")

        args = ["-c", self.config_path]
        if self.uid:
            args += ["--uid", self.uid]
        self._stopping = False
        self.process.start(self.frpc_path, args)
        self._connect_timer.start()
        return "启动成功"

    def stop(self):
        """异步停止。无论进程当前是否在运行, 都保证发出终态信号,
        避免主界面卡在"关闭中..."(原实现: 进程已退出时直接 return, 不发任何信号)。"""
        self._connect_timer.stop()

        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._stopping = False
            self._emit_status("stopped", force=True)
            return "未运行"

        self._stopping = True
        self.process.terminate()
        # 兜底: 3 秒后仍未退出则强杀
        QTimer.singleShot(STOP_KILL_MS, self._kill_if_alive)
        return "正在停止"

    def _kill_if_alive(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        elif self.conn_status != "failed":
            # 已退出但 finished 未触发(极端情况) -> 兜底终态
            self._emit_status("stopped")

    # ===== 状态发射 

    def _set_status(self, status):
        """状态变化才发(去抖)"""
        if status == self.conn_status:
            return
        self.conn_status = status
        self.status_signal.emit(status)

    def _emit_status(self, status, force=False):
        """force=True: 即使与上次相同也发一次(stop 的终态保证)"""
        if not force and status == self.conn_status:
            return
        self.conn_status = status
        self.status_signal.emit(status)

    # ===== stdout =====

    def _on_stdout(self):
        data = self.process.readAllStandardOutput().data().decode(errors="ignore")

        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue

            self.logs.append(line)
            self.log_signal.emit(line)

            low = line.lower()
            if "login to server success" in low or "start proxy success" in low:
                self._connect_timer.stop()
                self._set_status("connected")
            elif "connection refused" in low or "login failed" in low:
                self._connect_timer.stop()
                self._set_status("failed")

        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    # ===== stderr 

    def _on_stderr(self):
        data = self.process.readAllStandardError().data().decode(errors="ignore")

        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue

            msg = "[ERROR] " + line
            self.logs.append(msg)
            self.log_signal.emit(msg)

            self._connect_timer.stop()
            self._set_status("failed")

        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    # ===== 进程事件 =====

    def _on_finished(self):
        self._connect_timer.stop()
        self._stopping = False
        if self.conn_status == "failed":
            return                       # 失败已上报, 不再覆盖为"未连接"
        self._emit_status("stopped", force=True)

    def _on_error(self, err):
        """只把"启动失败"当作连接失败; 我们主动 stop() 触发的 Crashed 不算"""
        self.log_signal.emit("[ERROR] frpc 进程错误: %s" % err)
        if err == QProcess.ProcessError.FailedToStart:
            self._connect_timer.stop()
            self._set_status("failed")

    def _on_connect_timeout(self):
        if self.conn_status != "connecting":
            return
        self.log_signal.emit(
            "[ERROR] 连接超时(%ds 未登录成功), 已自动停止" % (CONNECT_TIMEOUT_MS // 1000))
        self._set_status("failed")
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._stopping = True
            self.process.terminate()
            QTimer.singleShot(STOP_KILL_MS, self._kill_if_alive)
