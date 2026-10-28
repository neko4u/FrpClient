from PyQt6.QtCore import QProcess, QObject, QTimer, pyqtSignal
import os
import re
from datetime import datetime

CONNECT_TIMEOUT_MS = 20 * 1000   # 启动后 20s 仍未登录成功 -> 判定连接失败(避免卡在"连接中...")
STOP_KILL_MS = 3 * 1000          # terminate 后 3s 仍未退出 -> 强杀
HEARTBEAT_RECV_TIMEOUT_MS = 15 * 1000   # 发出心跳后 15s 没等到回应 -> 记一次超时样本

# frpc 输出带 ANSI 色码, 解析时间戳前要先剥掉
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class FRPManager(QObject):
    # ===== 信号 =====
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)      # stopped / connecting / connected / failed
    heartbeat_sample = pyqtSignal(float, bool)   # (RTT 毫秒, 是否超时) —— 只给网络质量观测用

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

        # 心跳配对状态(被动观测): 记录 send 的时间戳, 等 receive 回来求差
        self._hb_send_ts = None
        self._hb_watch = QTimer(self)
        self._hb_watch.setSingleShot(True)
        self._hb_watch.setInterval(HEARTBEAT_RECV_TIMEOUT_MS)
        self._hb_watch.timeout.connect(self._on_hb_timeout)

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
        self._hb_send_ts = None
        self._hb_watch.stop()
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

        for raw in data.splitlines():
            line = _ANSI_RE.sub("", raw).strip()
            if not line:
                continue

            # debug/trace 行只用来配对心跳 RTT, 不进日志窗口也不落盘(否则刷屏)
            if " [D] " in line:
                self._parse_heartbeat(line)
                continue
            if " [T] " in line:
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
            elif "heartbeat timeout" in low:
                self._hb_timeout("frpc 心跳超时")

        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    # ===== 心跳 RTT 配对(被动, 只读日志) =====

    @staticmethod
    def _log_ts(line):
        """从 frpc 日志行取毫秒时间戳: '2026-10-28 20:03:33.365 [D] ...' """
        try:
            return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f").timestamp() * 1000.0
        except Exception:
            return None

    def _parse_heartbeat(self, line):
        low = line.lower()
        if "send heartbeat to server" in low:
            ts = self._log_ts(line)
            if ts is not None:
                self._hb_send_ts = ts
                self._hb_watch.start()
        elif "receive heartbeat from server" in low:
            recv = self._log_ts(line)
            send = self._hb_send_ts
            if recv is not None and send is not None:
                self._hb_send_ts = None
                self._hb_watch.stop()
                self.heartbeat_sample.emit(max(0.0, recv - send), False)

    def _hb_timeout(self, _why=""):
        """心跳没等到回应: 记一次超时样本(不做任何业务动作)"""
        if self._hb_send_ts is None:
            return
        self._hb_send_ts = None
        self._hb_watch.stop()
        self.heartbeat_sample.emit(0.0, True)

    def _on_hb_timeout(self):
        self._hb_timeout()

    # ===== stderr 

    def _on_stderr(self):
        data = self.process.readAllStandardError().data().decode(errors="ignore")

        for raw in data.splitlines():
            line = _ANSI_RE.sub("", raw).strip()
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
