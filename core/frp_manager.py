from PyQt6.QtCore import QProcess, QObject, pyqtSignal
import os


class FRPManager(QObject):
    # ===== 信号 =====
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, frpc_path, config_path, uid=""):
        super().__init__()

        self.frpc_path = frpc_path
        self.config_path = config_path
        self.uid = uid


        self.process = QProcess()
        self.logs = []
        self.conn_status = "stopped"  # stopped / connecting / connected / failed

        # ===== 绑定信号 =====
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

    def start(self):
        if self.process.state() == QProcess.ProcessState.Running:
            return "已运行"

        if not os.path.exists(self.frpc_path):
            return "frpc.exe 不存在"

        self.logs = []
        self.conn_status = "connecting"
        self.status_signal.emit("connecting")

        args = ["-c", self.config_path]
        if self.uid:
            args += ["--uid", self.uid]
        self.process.start(self.frpc_path, args)

        return "启动成功"


    def stop(self):
        """异步停止: terminate 后等 finished 信号自动发 stopped, 3s 未退出则强杀。
        不阻塞 UI, 便于主窗口在关闭过程中展示动画。"""
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return "未运行"

        self.process.terminate()
        # 兜底: 3 秒后仍未退出则强杀
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, self._kill_if_alive)
        return "正在停止"

    def _kill_if_alive(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    # ===== stdout =====
    def _on_stdout(self):
        data = self.process.readAllStandardOutput().data().decode(errors="ignore")
        lines = data.splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            self.logs.append(line)
            self.log_signal.emit(line)

            low = line.lower()
            if "login to server success" in low or "start proxy success" in low:
                if self.conn_status != "connected":
                    self.conn_status = "connected"
                    self.status_signal.emit("connected")

            elif "connection refused" in low or "login failed" in low:
                if self.conn_status != "failed":
                    self.conn_status = "failed"
                    self.status_signal.emit("failed")
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    # ===== stderr =====
    def _on_stderr(self):
        data = self.process.readAllStandardError().data().decode(errors="ignore")
        lines = data.splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            msg = "[ERROR] " + line
            self.logs.append(msg)
            self.log_signal.emit(msg)

            if self.conn_status != "failed":
                self.conn_status = "failed"
                self.status_signal.emit("failed")
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def _on_finished(self):
        if self.conn_status != "failed":
            self.conn_status = "stopped"
            self.status_signal.emit("stopped")