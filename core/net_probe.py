"""网络质量观察（被动）+ L1 主动链路检测

两条互相独立的东西，别混：

被动 PassiveMonitor —— 只吃已有信号，一个包都不多发：
  django 通道：SessionManager 每次心跳的计时（外加本地 8s 没回就记一次超时样本）
  frps  通道：frpc debug 日志里 "send heartbeat to server" / "receive heartbeat from server"
              两行的毫秒时间戳配对（需要 frpc.toml 里显式开应用层心跳，见 ConfigManager）
  —— 不干预会话、不停隧道、不改心跳失败处理。灯只是显示。

主动 L1Probe —— 只有用户点"网络连接测试"才跑：
  每个样本新建一条 TCP 连接（连 HTTP keep-alive 会让第二个样本起接近 0ms，测的不是链路）
  frps  打到控制口（业务无感，不会被对账任务当伪造连接拉黑）
  django 打到 443 的 TCP 握手（纯网络 RTT，不碰 Django 业务，也不写它 DB）
  单例、可取消、有总超时；连续丢包 5 个或连续 3 个 RTT>900ms 提前终止
"""
import time

from PyQt6.QtCore import QObject, QTimer, QElapsedTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QTcpSocket, QAbstractSocket

from core import app_log
from core.tracert import TracertRunner

# ---------------- 被动：阈值与参数 ----------------

WINDOW_SIZE = 10           # 每通道滑动窗口样本数
MIN_SAMPLES = 5            # 少于这个数只用固定阈值（冷启动）

GREEN, YELLOW, RED, UNKNOWN = "green", "yellow", "red", "unknown"
_RANK = {GREEN: 0, YELLOW: 1, RED: 2}

FRPS_YELLOW_MS = 150
FRPS_RED_MS = 300

DJANGO_YELLOW_MS = 300         # django 通道绝对阈值只有一档
DJANGO_RATIO = 1.5             # 相对基线倍数
DJANGO_FLOOR_MS = 100          # 但至少要比这个高才算异常：max(基线×1.5, 100)
DJANGO_HARD_RATIO = 2.0        # 连续 2 个样本超基线 2 倍
DJANGO_TIMEOUT_RED = 2         # 连续 2 次超时 -> 红

STATUS_TEXT = {
    UNKNOWN: "采样中",
    GREEN: "网络良好",
    YELLOW: "网络一般",
    RED: "网络差",
}


def _median(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


class RttWindow:
    """滑动窗口，只存 RTT 数值，不存任何业务内容"""

    def __init__(self, size=WINDOW_SIZE):
        self.size = size
        self.values = []

    def add(self, rtt):
        self.values.append(float(rtt))
        if len(self.values) > self.size:
            self.values = self.values[-self.size:]

    def __len__(self):
        return len(self.values)

    def median(self):
        return _median(self.values)

    def ready(self):
        return len(self.values) >= MIN_SAMPLES


class _Channel:
    def __init__(self, name):
        self.name = name
        self.win = RttWindow()
        self.last_rtt = None
        self.last_ts = 0.0
        self.consec_timeout = 0
        self.consec_high = 0
        self.status = UNKNOWN
        self._pending = None
        self._pending_n = 0
        self._last_log_ts = 0.0

    def snapshot(self):
        return {
            "name": self.name,
            "status": self.status,
            "text": STATUS_TEXT.get(self.status, "采样中"),
            "rtt": self.last_rtt,
            "base": self.win.median(),
            "samples": len(self.win),
            "timeout": self.consec_timeout,
            "ts": self.last_ts,
        }


class PassiveMonitor(QObject):
    """被动网络质量观察器。changed(dict) 在"灯色真正变化"时发一次。"""

    changed = pyqtSignal(dict)

    # 持续同一状态时，最多每 5 分钟补一条日志（避免 30s 一行刷爆）
    KEEPALIVE_LOG_SEC = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frps = _Channel("frps")
        self.django = _Channel("django")
        self._suspended = False          # 主动检测期间置 True：样本只丢弃
        self._last_worst = UNKNOWN

    # ---------------- 对外 ----------------

    def set_suspended(self, on):
        """主动检测期间丢弃被动样本（只丢弃，不动其它逻辑）"""
        self._suspended = bool(on)

    def reset(self):
        """隧道断开时清空，避免拿旧基线判新连接"""
        for ch in (self.frps, self.django):
            ch.status = UNKNOWN
            ch.win.values = []
            ch.last_rtt = None
            ch.consec_timeout = 0
            ch.consec_high = 0
            ch._pending = None
            ch._pending_n = 0
        self._last_worst = UNKNOWN

    def worst(self):
        """主页灯取哪一档

        特例（按需求）：frps = 绿 且 django = 黄 时，主页仍然显示绿
        （frps 是隧道主链路，django 只是计时通道，它略慢不该让整灯变黄）。
        其余情况一律取更严重的一档。
        """
        f = self.frps.status
        d = self.django.status
        if f == GREEN and d == YELLOW:
            return GREEN

        live = [s for s in (f, d) if s != UNKNOWN]
        if not live:
            return UNKNOWN
        return max(live, key=lambda s: _RANK[s])

    def snapshot(self):
        return {
            "frps": self.frps.snapshot(),
            "django": self.django.snapshot(),
            "worst": self.worst(),
            "worst_text": STATUS_TEXT.get(self.worst(), "采样中"),
        }

    # ---------------- 样本入口 ----------------

    def feed_frps(self, rtt_ms, is_timeout=False):
        if self._suspended:
            return
        self._feed(self.frps, rtt_ms, is_timeout)

    def feed_django(self, rtt_ms, is_timeout=False):
        if self._suspended:
            return
        self._feed(self.django, rtt_ms, is_timeout)

    # ---------------- 判定 ----------------

    def _feed(self, ch, rtt_ms, is_timeout):
        now = time.time()
        ch.last_ts = now

        if is_timeout:
            ch.consec_timeout += 1
            ch.consec_high = 0
            # django 要连续 2 次；frps 一次超时就是红（需求里 frps 超时=红）
            red_now = (ch.consec_timeout >= DJANGO_TIMEOUT_RED
                       if ch is self.django else ch.consec_timeout >= 1)
            cand = RED if red_now else ch.status
            if cand == RED:
                self._commit(ch, RED, force=True, now=now,
                             text="心跳超时（连续 %d 次）" % ch.consec_timeout)
            return

        rtt = float(rtt_ms)
        ch.last_rtt = rtt
        ch.consec_timeout = 0

        cand, strong = self._classify(ch, rtt)
        dropped = ""
        if cand == YELLOW and ch is self.django and not strong:
            dropped = "（相对基线偏高，已按下限 %dms 判）" % DJANGO_FLOOR_MS

        self._commit(ch, cand, force=strong, now=now, rtt=rtt, text=dropped)
        ch.win.add(rtt)                  # 先判定再入窗：基线只用历史样本

    def _classify(self, ch, rtt):
        """返回 (候选状态, 是否"强判定")

        强判定 = 已到绝对阈值，或已满足"连续 N 次"规则 —— 立即生效(不再去抖)
        弱判定 = 仅单个样本超过相对下限 —— 需要 2 个样本确认
        """
        if ch is self.frps:
            if rtt > FRPS_RED_MS:
                return RED, True
            if rtt > FRPS_YELLOW_MS:
                return YELLOW, True
            return GREEN, False

        # django 通道
        if rtt > DJANGO_YELLOW_MS:
            return YELLOW, True

        if ch.win.ready():
            base = ch.win.median()
            floor = max(base * DJANGO_RATIO, DJANGO_FLOOR_MS)
            if rtt > base * DJANGO_HARD_RATIO:
                ch.consec_high += 1
            else:
                ch.consec_high = 0
            if ch.consec_high >= 2:          # 连续 2 个样本超基线 2 倍
                return YELLOW, True
            if rtt > floor:                  # 单样本超前 "max(基线×1.5, 100ms)"
                return YELLOW, False
        return GREEN, False

    def _commit(self, ch, cand, force=False, now=None, rtt=None, text=""):
        """状态去抖：
           变红（更坏）立即生效 —— 出问题要马上看到；
           其余变化（黄/绿/回落）要连续 2 个样本一致才切换，避免灯乱闪。
        """
        now = now or time.time()
        if cand == ch.status:
            ch._pending = None
            ch._pending_n = 0
            self._keepalive(ch, now)
            return

        if force or cand == RED or ch.status == UNKNOWN:
            changed = True          # 变红/强判定/首次判定立即生效（首样本别等 60s 才亮灯）
        else:
            if ch._pending == cand:
                ch._pending_n += 1
            else:
                ch._pending = cand
                ch._pending_n = 1
            changed = ch._pending_n >= 2

        if not changed:
            return

        old = ch.status
        ch.status = cand
        ch._pending = None
        ch._pending_n = 0
        ch._last_log_ts = now
        app_log.net(
            ch.name, cand,
            rtt=rtt if rtt is not None else ch.last_rtt,
            base=ch.win.median(),
            timeout=1 if cand == RED and ch.consec_timeout else 0,
            consec=ch.consec_timeout,
            text="%s -> %s%s" % (STATUS_TEXT.get(old, "采样中"),
                                 STATUS_TEXT.get(cand, ""), text),
        )
        self.changed.emit(self.snapshot())

    def _keepalive(self, ch, now):
        if ch.status in (YELLOW, RED) and now - ch._last_log_ts >= self.KEEPALIVE_LOG_SEC:
            ch._last_log_ts = now
            app_log.net(ch.name, ch.status, rtt=ch.last_rtt, base=ch.win.median(),
                        timeout=1 if ch.consec_timeout else 0,
                        consec=ch.consec_timeout,
                        text="持续 %s" % STATUS_TEXT.get(ch.status, ""))


# ======================================================================
# L1 主动检测
# ======================================================================

PROBE_RTT_WARN = 150
PROBE_RTT_BAD = 300
PROBE_JIT_WARN = 30
PROBE_JIT_BAD = 50
PROBE_LOSS_WARN = 1.0
PROBE_LOSS_BAD = 5.0
PROBE_HARD_RTT = PROBE_RTT_BAD * 3      # 提前终止：连续超 3 倍阈值
PROBE_MAX_LOSS = 5                      # 提前终止：连续丢 5 个
SAMPLE_TIMEOUT_MS = 2500
TOTAL_TIMEOUT_MS = 90 * 1000

OK, WARN, BAD = "OK", "WARN", "BAD"
_RANK_V = {OK: 0, WARN: 1, BAD: 2}


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return float(sorted_vals[max(0, min(idx, len(sorted_vals) - 1))])


def _verdict_rtt(v):
    if v is None:
        return "N/A"
    return OK if v < PROBE_RTT_WARN else (WARN if v <= PROBE_RTT_BAD else BAD)


def _verdict_jitter(v):
    if v is None:
        return "N/A"
    return OK if v < PROBE_JIT_WARN else (WARN if v <= PROBE_JIT_BAD else BAD)


def _verdict_loss(v):
    if v is None:
        return "N/A"
    return OK if v < PROBE_LOSS_WARN else (WARN if v < PROBE_LOSS_BAD else BAD)


class L1Probe(QObject):
    """L1 主动链路检测（单例、可取消、有总超时）

    targets = {"frps": (host, port), "django": (host, port)}
    """

    progress = pyqtSignal(str, int, int)     # channel, done, total
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    PLAN = [("frps", 20, 300), ("django", 12, 300)]   # 通道, 样本数, 间隔ms

    def __init__(self, targets, parent=None):
        super().__init__(parent)
        self.targets = targets
        self.results = {}
        self._ci = 0
        self._cur = None
        self._idx = 0
        self._sid = 0
        self._sock = None
        self._canceled = False
        self._done = False
        self._t0 = 0.0
        self._clock = QElapsedTimer()

        self._next_timer = QTimer(self)
        self._next_timer.setSingleShot(True)
        self._next_timer.timeout.connect(self._next_sample)

        self._sock_timer = QTimer(self)
        self._sock_timer.setSingleShot(True)
        self._sock_timer.setInterval(SAMPLE_TIMEOUT_MS)
        self._sock_timer.timeout.connect(self._on_sample_timeout)

        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.setInterval(TOTAL_TIMEOUT_MS)
        self._deadline.timeout.connect(self._on_deadline)

    # ---------------- 控制 ----------------

    def start(self):
        self._t0 = time.time()
        self._deadline.start()
        app_log.app("开始 L1 主动链路检测")
        self._begin_channel()

    def cancel(self):
        if self._done:
            return
        self._canceled = True
        self._finish("已取消")

    @property
    def done(self):
        return self._done

    # ---------------- 采样 ----------------

    def _begin_channel(self):
        name, total, gap = self.PLAN[self._ci]
        self._cur = {
            "name": name, "total": total, "gap": gap,
            "sent": 0, "lost": 0, "rtts": [],
            "consec_loss": 0, "consec_high": 0, "stop_reason": "",
        }
        self._idx = 0
        self._next_timer.start(120)

    def _next_sample(self):
        if self._done:
            return
        c = self._cur
        if c is None or self._idx >= c["total"]:
            return self._finish_channel()

        self._idx += 1
        self._sid += 1
        sid = self._sid

        host, port = self.targets.get(c["name"], ("", 0))
        if not host or not port:
            return self._finish("目标地址未配置")

        sock = QTcpSocket(self)
        self._sock = sock
        self._clock.start()
        sock.connected.connect(lambda: self._on_connected(sid))
        sock.errorOccurred.connect(lambda _err: self._on_error(sid))
        self._sock_timer.start()
        sock.connectToHost(host, int(port))

    def _drop_sock(self):
        try:
            if self._sock is not None:
                self._sock.connected.disconnect()
                self._sock.errorOccurred.disconnect()
        except Exception:
            pass
        try:
            if self._sock is not None:
                self._sock.abort()
                self._sock.deleteLater()
        except Exception:
            pass
        self._sock = None

    def _on_connected(self, sid):
        if self._done or sid != self._sid:
            return
        self._sock_timer.stop()
        ms = self._clock.elapsed()
        self._drop_sock()
        self._add_sample(ms)

    def _on_error(self, sid):
        if self._done or sid != self._sid:
            return
        self._sock_timer.stop()
        self._drop_sock()
        self._add_sample(None)

    def _on_sample_timeout(self):
        if self._done:
            return
        self._drop_sock()
        self._add_sample(None)

    def _add_sample(self, ms):
        c = self._cur
        if c is None:
            return
        c["sent"] += 1
        if ms is None:
            c["lost"] += 1
            c["consec_loss"] += 1
            c["consec_high"] = 0
        else:
            c["rtts"].append(float(ms))
            c["consec_loss"] = 0
            if ms > PROBE_HARD_RTT:
                c["consec_high"] += 1
            else:
                c["consec_high"] = 0

        self.progress.emit(c["name"], c["sent"], c["total"])

        if c["consec_loss"] >= PROBE_MAX_LOSS:
            c["stop_reason"] = "连续丢包 %d 个，提前终止" % c["consec_loss"]
            return self._finish_channel()
        if c["consec_high"] >= 3:
            c["stop_reason"] = "连续 %d 个 RTT > %dms，提前终止" % (
                c["consec_high"], PROBE_HARD_RTT)
            return self._finish_channel()

        self._next_timer.start(c["gap"])

    def _finish_channel(self):
        c = self._cur
        if c is not None:
            self.results[c["name"]] = self._metrics(c)
        self._ci += 1
        if self._ci >= len(self.PLAN):
            return self._finish("")
        self._begin_channel()

    @staticmethod
    def _metrics(c):
        rtts = c["rtts"]
        sent = c["sent"]
        lost = c["lost"]
        if rtts:
            srt = sorted(rtts)
            avg = sum(rtts) / len(rtts)
            p50 = _percentile(srt, 50)
            p95 = _percentile(srt, 95)
            jitter = max(0.0, p95 - p50)
        else:
            avg = p50 = p95 = jitter = None
        loss = (100.0 * lost / sent) if sent else None
        return {
            "sent": sent, "lost": lost, "loss_pct": loss,
            "rtt_avg": avg, "rtt_p50": p50, "rtt_p95": p95, "jitter": jitter,
            "verdict": {
                "rtt": _verdict_rtt(avg),
                "jitter": _verdict_jitter(jitter),
                "loss": _verdict_loss(loss),
            },
            "stop_reason": c["stop_reason"],
        }

    def _on_deadline(self):
        if not self._done:
            self._finish("总超时 %ds，已停止" % (TOTAL_TIMEOUT_MS // 1000))

    def _finish(self, note):
        if self._done:
            return
        self._done = True
        self._next_timer.stop()
        self._sock_timer.stop()
        self._deadline.stop()
        self._drop_sock()

        # 当前通道未跑完也给出已采到的结论
        if self._cur is not None and self._cur["name"] not in self.results:
            self.results[self._cur["name"]] = self._metrics(self._cur)

        worst = OK
        for r in self.results.values():
            for v in r["verdict"].values():
                if _RANK_V.get(v, 0) > _RANK_V[worst]:
                    worst = v

        result = {
            "canceled": self._canceled,
            "note": note,
            "elapsed": round(time.time() - self._t0, 1),
            "channels": self.results,
            "overall": worst,
        }
        app_log.app("L1 检测结束：总判定 %s%s" % (worst, ("，" + note) if note else ""))
        self.finished.emit(result)


# ======================================================================
# L3 上行测速（打 frps 那台的 nginx 靶子）
# ======================================================================

# 靶子：frps 机上的 nginx（location = /up/... -> return 204）
UPLOAD_URL = "http://8.148.144.164:8088/up/k9Qv2Lm7Rt"

# 未连接隧道 = 没在用 -> 直接一档；已连接 = 在用 -> 小档起步逐档升
# 每档 (MB, 发送限速 Mbps；0=不限)；样本时长不足 0.8s 会自动加档（避免测到本地缓冲）
UPLOAD_STAGES_FREE = [(1, 0.0), (2, 0.0), (5, 0.0), (10, 0.0)]
UPLOAD_STAGES_BUSY = [(1, 3.0), (2, 6.0), (5, 0.0), (10, 0.0)]
VALID_SECS = 0.8

UP_OK_MBPS = 1.5
UP_WARN_MBPS = 0.5
CHUNK = 64 * 1024


def _verdict_upload(mbps):
    if mbps is None:
        return "N/A"
    if mbps > UP_OK_MBPS:
        return OK
    return WARN if mbps >= UP_WARN_MBPS else BAD


class L3Upload(QObject):
    """上行测速：往靶子 POST 指定字节数，客户端自己数写了多少字节、花了多久。

    说明：nvginx 会先回 204 再把剩余请求体读掉，所以不能靠响应判断完成，
    测量以"socket 把字节全部刷出去"为准。
    """

    progress = pyqtSignal(int, int)      # 已发, 总
    finished = pyqtSignal(dict)

    def __init__(self, url=UPLOAD_URL, stages=None, parent=None):
        super().__init__(parent)
        self.url = QUrl(url)
        self.stages = list(stages or UPLOAD_STAGES_FREE)
        self._si = 0
        self._records = []
        self._done = False
        self._sock = None
        self._total = 0
        self._sent = 0
        self._pace = 0.0
        self._buf = b"\x00" * CHUNK
        self._header = b""
        self._resp = ""
        self._err = ""
        self._flushed = False
        self._secs_at_flush = 0.0
        self._clock = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._pump)

        # 上传写完后最多再等 5 秒的响应，等不到就判靶子不可用
        self._wait_resp = QTimer(self)
        self._wait_resp.setSingleShot(True)
        self._wait_resp.setInterval(5000)
        self._wait_resp.timeout.connect(
            lambda: self._finish("skip", "上传靶子没有返回成功（无响应）"))

    # ---------------- 对外 ----------------

    def start(self):
        if not self.url.isValid() or not self.url.host():
            return self._finish("skip", "上传地址无效")
        self._run_stage()

    def cancel(self):
        self._finish("skip", "已取消")

    @property
    def done(self):
        return self._done

    # ---------------- 单档 ----------------

    def _run_stage(self):
        if self._done:
            return
        if self._si >= len(self.stages):
            return self._finish("ok", "")

        mb, pace = self.stages[self._si]
        self._total = int(mb * 1024 * 1024)
        self._sent = 0
        self._pace = float(pace)
        self._resp = ""
        self._err = ""
        self._flushed = False
        self._secs_at_flush = 0.0
        self._clock.start()

        path = self.url.path() or "/"
        self._header = (
            "POST %s HTTP/1.1\r\nHost: %s\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n"
            % (path, self.url.host(), self._total)
        ).encode()

        self._sock = QTcpSocket(self)
        # 关键：把内核发送缓冲压小，否则几百 KB 会瞬间进缓冲，
        # bytesToWrite() 立刻归零，测出来是"内存带宽"而不是上行带宽
        try:
            self._sock.setSocketOption(
                QAbstractSocket.SocketOption.SendBufferSizeSocketOption, 32 * 1024)
        except Exception as e:
            print("设置发送缓冲失败:", e)
        self._sock.connected.connect(self._pump)
        self._sock.bytesWritten.connect(self._on_written)
        self._sock.readyRead.connect(self._on_read)
        self._sock.errorOccurred.connect(self._on_error)
        self._sock.connectToHost(self.url.host(), self.url.port(80))

    def _pump(self):
        if self._done or self._sock is None:
            return
        if self._sent == 0:
            self._sock.write(self._header)

        if self._sent >= self._total:
            return          # 已经灌完，等 bytesToWrite 清零后再结算（否则会提前算完）

        # 限速：按"应花时间 - 已花时间"补延时，避免把正在用的隧道打满
        if self._pace > 0:
            should = (self._sent * 8.0) / (self._pace * 1e6)
            actual = self._clock.elapsed() / 1000.0
            if actual < should - 0.02:
                self._tick.start(int((should - actual) * 1000))
                return

        n = min(CHUNK, self._total - self._sent)
        self._sock.write(self._buf[:n])
        self._sent += n
        self.progress.emit(self._sent, self._total)

    def _on_written(self, _n):
        if self._done or self._sock is None:
            return
        if self._sent >= self._total and self._sock.bytesToWrite() == 0:
            # 只是"写进了 socket"，不代表服务端收到；要等服务端回 2xx 才算数
            if not self._flushed:
                self._flushed = True
                self._secs_at_flush = max(0.001, self._clock.elapsed() / 1000.0)
                self._maybe_end_stage()
            return
        # 缓冲区还有空间就继续灌
        if self._sock.bytesToWrite() < 512 * 1024:
            self._pump()

    def _on_read(self):
        if self._sock is None:
            return
        try:
            data = bytes(self._sock.readAll().data())
            if len(self._resp) < 200:
                self._resp += data.decode("latin-1", "ignore")
        except Exception:
            pass
        self._maybe_end_stage()

    def _maybe_end_stage(self):
        """写入完成 + 服务端回了 2xx 才算这一档成立"""
        if self._done or not self._flushed:
            return
        if self._http_ok():
            return self._end_stage()
        # 写完了但还没响应：给 5 秒，等不到就判不可用
        if not self._wait_resp.isActive():
            self._wait_resp.start()

    def _on_error(self, _err):
        if self._done:
            return
        self._err = str(_err)
        # 只有确认拿到了 2xx 响应，才把已发字节当样本；否则一律判"靶子不可用"
        if self._http_ok() and self._sent >= max(CHUNK, self._total // 4):
            return self._end_stage()
        self._finish("skip", "上传靶子不可用（%s）" % (self._err or "连接被关闭"))

    def _http_ok(self):
        return self._resp.startswith("HTTP/2") or self._resp.startswith("HTTP/1.1 2")

    def _end_stage(self):
        self._wait_resp.stop()
        secs = self._secs_at_flush or max(0.001, self._clock.elapsed() / 1000.0)
        got = self._sent if self._sent > 0 else 0
        mbps = (got * 8.0) / (secs * 1e6) if got else None

        code = 0
        if self._resp.startswith("HTTP/"):
            try:
                code = int(self._resp.split()[1])
            except Exception:
                code = 0
        if not (200 <= code < 300):
            return self._finish("skip", "上传靶子没有返回成功（%s）"
                                % (("HTTP %d" % code) if code else "无响应"))

        # 太快 = 还卡在本地缓冲里，不可信，稍后自动加档
        valid = secs >= VALID_SECS

        verdict = _verdict_upload(mbps)
        self._records.append({
            "mb": self.stages[self._si][0],
            "bytes": got,
            "secs": round(secs, 2),
            "mbps": None if mbps is None else round(mbps, 2),
            "verdict": verdict,
            "valid": valid,
        })
        self._close_sock()
        self._si += 1

        if verdict == BAD:
            # 上行已经很低，不再加档（也不浪费流量）
            return self._finish("ok", "上行偏低，已停止加压")
        if valid:
            return self._finish("ok", "")           # 拿到可信样本就够了
        if self._si < len(self.stages):
            QTimer.singleShot(600, self._run_stage)  # 加一档再测
            return
        self._finish("ok", "")

    def _close_sock(self):
        try:
            if self._sock is not None:
                self._sock.abort()
                self._sock.deleteLater()
        except Exception:
            pass
        self._sock = None

    def _finish(self, status, reason):
        if self._done:
            return
        self._done = True
        self._tick.stop()
        self._wait_resp.stop()
        self._close_sock()

        # 有可信样本就只看可信样本；全都不够时长才退回用全部样本（标记为下限估算）
        pool = [r for r in self._records if r.get("valid") and r["mbps"] is not None]
        estimated = False
        if not pool:
            pool = [r for r in self._records if r["mbps"] is not None]
            estimated = bool(pool)
        best = max((r["mbps"] for r in pool), default=None)
        verdict = _verdict_upload(best)

        self.finished.emit({
            "status": status,
            "reason": reason,
            "mbps": best,
            "estimated": estimated,
            "verdict": verdict,
            "stages": self._records,
        })


# ======================================================================
# L4 归因（只在 frps 通道做；结论要短、要面向用户）
# ======================================================================

ROUTE_TEXT = {
    "local": ("可能是本机或家用路由器这一段的问题",
              "隧道会卡顿，别人连你容易超时"),
    "transit": ("可能是运营商中间线路的问题",
                "隧道会时快时慢，晚高峰更明显"),
    "datacenter": ("可能是机房一侧的问题",
                   "稍后再测一次，仍然这样请联系客服"),
    "route": ("线路可能绕远了",
              "延迟高但一般不掉线"),
    "uplink": ("可能是家用宽带上行被占满（上传/直播/网盘同步）",
               "上行一慢，别人连你就会超时"),
    "ok": ("链路正常", "不用处理"),
    "unknown": ("暂时判断不出具体原因", "可以稍后再测一次"),
}


def attribute_route(hops, l1_frps, l3=None):
    """根据 L1/L2/L3 给一个用户能看懂的结论 -> (code, 结论, 影响)"""
    loss_v = (l1_frps or {}).get("verdict", {}).get("loss")
    rtt_v = (l1_frps or {}).get("verdict", {}).get("rtt")
    jit_v = (l1_frps or {}).get("verdict", {}).get("jitter")

    # 1) 上行被判定为差 -> 直接说是上行问题
    if l3 and l3.get("verdict") == BAD:
        return ("uplink",) + ROUTE_TEXT["uplink"]

    # 2) L1 三项都正常 -> 就是正常。
    #    （中途某些跳显示 * 是 ICMP 被限速，不能拿它当丢包证据）
    if loss_v == OK and rtt_v == OK and jit_v == OK:
        return ("ok",) + ROUTE_TEXT["ok"]

    # 2) 有逐跳数据：按"第一次出现丢包的位置"归因
    if hops:
        total = len(hops)
        # 整跳全 * 的多半是 ICMP 被过滤，不算丢包证据；只认"部分回应+部分丢"的跳
        loss_hops = [h for h in hops if h["lost"] > 0 and h["rtts"]]
        # 路很短时只把最后一跳算机房侧，否则中转跳会被误判成机房问题
        tail = 2 if total >= 8 else 1
        for h in loss_hops:
            hop = h["hop"]
            if hop <= 2:
                return ("local",) + ROUTE_TEXT["local"]
            if hop > total - tail:
                return ("datacenter",) + ROUTE_TEXT["datacenter"]
            return ("transit",) + ROUTE_TEXT["transit"]

        # 全跳没丢包但延迟判坏 -> 绕路/拥塞
        if loss_v == OK and rtt_v in (WARN, BAD):
            return ("route",) + ROUTE_TEXT["route"]

    # 3) 只有 L1 结论
    if loss_v == BAD:
        return ("transit",) + ROUTE_TEXT["transit"]
    if rtt_v == BAD and jit_v == BAD:
        return ("route",) + ROUTE_TEXT["route"]
    if rtt_v == OK and jit_v == OK and loss_v == OK:
        return ("ok",) + ROUTE_TEXT["ok"]
    return ("unknown",) + ROUTE_TEXT["unknown"]


# ======================================================================
# 诊断编排：L1 -> (L2) -> (L3) -> 归因
# ======================================================================

class Diagnoser(QObject):
    """一次完整诊断（单例用法：同一时间只允许一个）

    L2 只在隧道通道 L1 有 WARN/BAD 时跑；
    L3 在 L1 严重异常（丢包>=5% 或 RTT 与波动同时坏）时跳过；
    归因只对隧道通道给出。
    """

    stage = pyqtSignal(str, str)          # (key, 面向用户的一句话)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, targets, frps_host="", tunnel_connected=False,
                 upload_url=UPLOAD_URL, parent=None):
        super().__init__(parent)
        self.targets = targets
        self.frps_host = frps_host or (targets.get("frps") or ("", 0))[0]
        self.tunnel_connected = bool(tunnel_connected)
        self.upload_url = upload_url

        self.l1 = None
        self.route = {"hops": [], "error": ""}
        self.l3 = None
        self._probe = None
        self._tracert = None
        self._upload = None
        self._canceled = False
        self._done = False

    # ---------------- 对外 ----------------

    def start(self):
        self.stage.emit("delay", "正在检测延迟…")
        self._probe = L1Probe(self.targets, self)
        self._probe.finished.connect(self._on_l1)
        self._probe.failed.connect(self._fail)
        self._probe.start()

    def cancel(self):
        if self._done:
            return
        self._canceled = True
        for obj in (self._probe, self._tracert, self._upload):
            try:
                if obj is not None:
                    obj.cancel()
            except Exception:
                pass
        self._finish()

    @property
    def done(self):
        return self._done

    # ---------------- 阶段 ----------------

    def _on_l1(self, result):
        if self._canceled:
            return self._finish()
        self.l1 = result
        frps_ch = (result.get("channels") or {}).get("frps") or {}
        v = frps_ch.get("verdict") or {}
        need_route = any(x != OK for x in v.values()) and bool(self.frps_host)

        if need_route:
            self.stage.emit("route", "正在分析线路…")
            self._tracert = TracertRunner(self.frps_host, self)
            self._tracert.finished.connect(self._on_route)
            self._tracert.start()
        else:
            self._on_route([], "")

    def _on_route(self, hops, error):
        if self._canceled:
            return self._finish()
        self.route = {"hops": hops or [], "error": error or ""}

        frps_ch = (self.l1.get("channels") or {}).get("frps") or {}
        v = frps_ch.get("verdict") or {}
        severe = (v.get("loss") == BAD) or (v.get("rtt") == BAD and v.get("jitter") == BAD)
        if severe:
            self.l3 = {"status": "skip", "reason": "链路异常，跳过上传测试", "verdict": "N/A"}
            return self._finish()

        self.stage.emit("upload", "正在测试上传速度…")
        stages = UPLOAD_STAGES_BUSY if self.tunnel_connected else UPLOAD_STAGES_FREE
        self._upload = L3Upload(self.upload_url, stages, self)
        self._upload.finished.connect(self._on_upload)
        self._upload.start()

    def _on_upload(self, result):
        if self._canceled:
            return self._finish()
        self.l3 = result
        self._finish()

    def _fail(self, msg):
        if self._done:
            return
        self._done = True
        self.failed.emit(msg)

    def _finish(self):
        if self._done:
            return
        self._done = True

        l1 = self.l1 or {"overall": "N/A", "channels": {}}
        frps_ch = (l1.get("channels") or {}).get("frps") or {}
        code, title, impact = attribute_route(self.route.get("hops"), frps_ch, self.l3)

        overall = l1.get("overall", OK)
        if self.l3 and self.l3.get("verdict") in (WARN, BAD):
            if _RANK_V.get(self.l3["verdict"], 0) > _RANK_V.get(overall, 0):
                overall = self.l3["verdict"]

        self.finished.emit({
            "canceled": self._canceled,
            "elapsed": l1.get("elapsed"),
            "l1": l1,
            "route": self.route,
            "l3": self.l3,
            "attribution": {"code": code, "title": title, "impact": impact},
            "overall": overall,
        })
