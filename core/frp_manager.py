from PyQt6.QtCore import QProcess, QObject, pyqtSignal
import os


class FRPManager(QObject):
    # ===== 信号 =====
    log_signal = pyqtSignal(str)       # 实时日志
    status_signal = pyqtSignal(str)    # 状态变化

    def __init__(self, frpc_path, config_path):
        super().__init__()

        self.frpc_path = frpc_path
        self.config_path = config_path

        self.process = QProcess()
        self.logs = []
        self.conn_status = "stopped"  # stopped / connecting / connected / failed

        # ===== 绑定信号 =====
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

    # ===== 启动 =====
    def start(self):
        if self.process.state() == QProcess.ProcessState.Running:
            return "已运行"

        if not os.path.exists(self.frpc_path):
            return "frpc.exe 不存在"

        self.logs = []
        self.conn_status = "connecting"
        self.status_signal.emit("connecting")

        self.process.start(self.frpc_path, ["-c", self.config_path])

        return "启动成功"

    # ===== 停止 =====
    def stop(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()

            # 等待退出
            if not self.process.waitForFinished(2000):
                self.process.kill()

            self.conn_status = "stopped"
            self.status_signal.emit("stopped")

            return "已停止"

        return "未运行"

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

            # ===== 状态判断 =====
            if "login to server success" in low or "start proxy success" in low:
                if self.conn_status != "connected":
                    self.conn_status = "connected"
                    self.status_signal.emit("connected")

            elif "connection refused" in low or "login failed" in low:
                if self.conn_status != "failed":
                    self.conn_status = "failed"
                    self.status_signal.emit("failed")

        # ===== 限制日志长度 =====
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

        # ===== 限制日志长度 =====
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    # ===== 进程结束 =====
    def _on_finished(self):
        # 如果不是失败导致的退出，就标记为 stopped
        if self.conn_status != "failed":
            self.conn_status = "stopped"
            self.status_signal.emit("stopped")