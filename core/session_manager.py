"""FRP 会话管理器：start -> 心跳保活 -> 倒计时 -> stop 全生命周期

通过 Qt 信号通知 UI（不阻塞界面）：
  status_changed(str)    状态变化: idle/connecting/active/stopping/error
  countdown_changed(int) 剩余秒数(每秒发射)
  error(str)             错误信息
  session_closed(dict)   会话被服务器关闭(含原因/余额)
"""
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal

from core.session_api import SessionAPI
from core.token_holder import TokenHolder

HEARTBEAT_INTERVAL_MS = 30 * 1000   # 30s 心跳
COUNTDOWN_INTERVAL_MS = 200         # 倒计时轮询 200ms(精确), 秒变才发信号 -> 平滑


class SessionManager(QObject):
    status_changed = pyqtSignal(str)
    countdown_changed = pyqtSignal(int)
    error = pyqtSignal(str)
    session_closed = pyqtSignal(dict)   # {"reason": str, "balance": int}
    initialized = pyqtSignal()          # status 首次查询完成(成功/失败), 用于移除启动遮罩

    def __init__(self, api=None):
        super().__init__()
        self.api = api or SessionAPI()
        self.session_id = ""
        self.stop_time_ts = 0        # 服务器返回的到期时间戳
        self._status = "idle"
        self._balance = 0
        self._started_at = None
        self._clock_offset = 0       # 服务器时钟 - 本地时钟 偏移(秒), 用于倒计时校准

        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._hb_timer.timeout.connect(self._do_heartbeat)

        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(COUNTDOWN_INTERVAL_MS)
        self._cd_timer.setTimerType(Qt.TimerType.PreciseTimer)  # 精确计时, 避免丢 tick
        self._cd_timer.timeout.connect(self._tick_countdown)
        self._last_cd_sec = None  # 上次发出的剩余秒, 秒变才 emit

    # ---------- 对外接口 ----------

    @property
    def status(self):
        return self._status

    @property
    def balance(self):
        return self._balance

    @property
    def remaining_seconds(self):
        """估算剩余秒数: 用服务器时钟校准, 避免本地钟偏差导致跳变"""
        if not self.stop_time_ts:
            return 0
        # 本地当前时刻 + 偏移 = 服务器当前时刻
        server_now = self._now_ts() + self._clock_offset
        return max(0, int(self.stop_time_ts - server_now))

    def _calibrate_clock(self, data):
        """若响应带 server_time, 记录本地与服务器的时钟偏移(秒)"""
        st = data.get("server_time")
        if st:
            self._clock_offset = int(st) - self._now_ts()

    def start(self, token=None):
        """建立 django 会话(门禁: 成功后才允许启动 frpc)"""
        token = token or TokenHolder.get_token()
        if not token:
            self._set_status("error")
            self.error.emit("未登录，请先登录")
            return
        self._set_status("connecting")
        self.api.start(token, self._on_start)

    def stop(self):
        """主动断开: 先停心跳/倒计时, 再调服务器 stop"""
        self._hb_timer.stop()
        self._cd_timer.stop()
        if not self.session_id:
            self._set_status("idle")
            return
        token = TokenHolder.get_token()
        sid = self.session_id
        self.session_id = ""
        self.stop_time_ts = 0
        self._set_status("stopping")
        self.api.stop(token, sid, self._on_stop)

    def refresh_status(self, token=None):
        """启动时同步: 查服务器当前会话(可能上次没正常关)"""
        token = token or TokenHolder.get_token()
        if not token:
            return
        self.api.status(token, self._on_status)

    # ---------- 内部回调 ----------

    def _on_start(self, data):
        if data.get("code") != 0:
            self._set_status("error")
            self.error.emit(data.get("msg") or data.get("message") or "开启会话失败")
            return
        self._calibrate_clock(data)
        self.session_id = data["session_id"]
        self.stop_time_ts = data["stop_time_ts"]
        self._balance = data.get("balance_seconds", 0)
        self._started_at = self._now_ts()
        self._set_status("active")

        self._hb_timer.start()
        self._cd_timer.start()
        self._tick_countdown()

    def _on_status(self, data):
        if data.get("code") != 0:
            # 401 等 -> token 失效
            self.error.emit(data.get("msg") or data.get("message") or "状态查询失败")
            self.initialized.emit()   # 查询结束(失败也要撤遮罩)
            return
        self._calibrate_clock(data)
        self._balance = data.get("balance_seconds", 0)
        self.countdown_changed.emit(self._balance)
        if data.get("has_session"):
            self.session_id = data["session_id"]
            self.stop_time_ts = data["stop_time_ts"]
            self._started_at = data.get("start_ts", 0)
            self._set_status("active")
            self._hb_timer.start()
            self._cd_timer.start()
            self._tick_countdown()
        else:
            self._set_status("idle")
        self.initialized.emit()       # 查询完成 -> 撤遮罩

    def _on_heartbeat(self, data):
        if data.get("code") != 0:
            self._fail_session(data.get("msg") or "心跳失败")
            return
        self._calibrate_clock(data)
        if data.get("closed"):
            self._balance = data.get("balance_seconds", self._balance)
            self._teardown()
            self.session_closed.emit({"reason": "balance_exhausted",
                                      "balance": self._balance})
            return
        self._balance = data.get("balance_seconds", self._balance)
        self.stop_time_ts = data.get("stop_time_ts", self.stop_time_ts)
        self._tick_countdown()

    def _on_stop(self, data):
        if data.get("code") != 0:
            self.error.emit(data.get("msg") or "停止会话失败")
        self._calibrate_clock(data)
        if "balance_seconds" in data:
            self._balance = data["balance_seconds"]
        self.countdown_changed.emit(self._balance)
        self._teardown()
        self._set_status("idle")

    # ---------- 内部逻辑 ----------

    def _do_heartbeat(self):
        token = TokenHolder.get_token()
        if not token or not self.session_id:
            return
        self.api.heartbeat(token, self.session_id, self._on_heartbeat)

    def _tick_countdown(self):
        sec = self.remaining_seconds
        if sec != self._last_cd_sec:
            self._last_cd_sec = sec
            self.countdown_changed.emit(sec)

    def _fail_session(self, msg):
        """心跳失败/会话失效 -> 停表并报错(不自动重连, 由用户重试)"""
        self._hb_timer.stop()
        self._cd_timer.stop()
        self.session_id = ""
        self.stop_time_ts = 0
        self._set_status("error")
        self.error.emit(msg)

    def _teardown(self):
        self._hb_timer.stop()
        self._cd_timer.stop()
        self.session_id = ""
        self.stop_time_ts = 0

    def _now_ts(self):
        import time
        return int(time.time())

    def _set_status(self, s):
        if s != self._status:
            self._status = s
            self.status_changed.emit(s)
