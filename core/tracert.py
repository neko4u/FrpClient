"""L2：本机 traceroute（Windows 只有 tracert，没有 mtr）

只做两件事：跑一条有限跳数的 tracert、把逐跳 RTT/丢包解析成结构。
归因判断不在这里，放在 net_probe.attribute_route()。

为什么要 -d -w 400 -h 20：
  -d 不反解域名（省时间，也避免看到机房主机名）；
  -w 400 每跳等 400ms，20 跳最坏 8 秒级；
  -h 20 最多 20 跳（需求里的上限）。
ICMP 常被云厂商/运营商限速，出现 * 不等于业务链路丢包——只作辅助证据。
"""
import re
import sys

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

MAX_HOPS = 20
WAIT_MS = 400
TOTAL_TIMEOUT_MS = 45 * 1000

_HOP_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
# 中文 Windows 的 tracert 打印的是"毫秒"，不是 ms
_MS_RE = re.compile(r"(<\s*1|[\d.]+)\s*(?:ms|毫秒)", re.I)
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_tracert(text):
    """把 tracert 输出解析成 [{hop, rtts, lost, addr}]"""
    hops = []
    for raw in (text or "").splitlines():
        m = _HOP_RE.match(raw)
        if not m:
            continue
        hop = int(m.group(1))
        rest = m.group(2)

        rtts = []
        for tok in _MS_RE.findall(rest):
            try:
                rtts.append(0.5 if tok.strip().startswith("<") else float(tok))
            except ValueError:
                pass

        addr = ""
        ips = _IP_RE.findall(rest)
        if ips:
            addr = ips[-1]

        stars = rest.count("*")
        hops.append({
            "hop": hop,
            "rtts": rtts,
            "lost": stars,
            "addr": addr,
        })
    return hops


class TracertRunner(QObject):
    """异步跑 tracert，可取消；失败也回调（由上层决定要不要用）"""

    finished = pyqtSignal(list, str)      # (hops, error_text)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self._text = []
        self._done = False
        self.proc = None

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(TOTAL_TIMEOUT_MS)
        self._timeout.timeout.connect(lambda: self._finish("路由追踪超时"))

    def start(self):
        if sys.platform != "win32":
            return self._finish("当前系统不支持路由追踪")
        if not self.host:
            return self._finish("目标地址为空")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_read)
        self.proc.finished.connect(self._on_exit)
        self.proc.errorOccurred.connect(lambda _e: self._finish("路由追踪启动失败"))
        self.proc.start("tracert", ["-d", "-w", str(WAIT_MS), "-h", str(MAX_HOPS), self.host])
        self._timeout.start()

    def cancel(self):
        self._finish("已取消")

    # ---------------- 内部 ----------------

    def _on_read(self):
        try:
            data = self.proc.readAllStandardOutput().data().decode("gbk", "replace")
        except Exception:
            data = ""
        self._text.append(data)

    def _on_exit(self, *_):
        # 退出时把剩余缓冲读干净
        try:
            rest = self.proc.readAllStandardOutput().data().decode("gbk", "replace")
            if rest:
                self._text.append(rest)
        except Exception:
            pass
        self._finish("")

    def _finish(self, error):
        if self._done:
            return
        self._done = True
        self._timeout.stop()
        if self.proc is not None:
            try:
                if self.proc.state() != QProcess.ProcessState.NotRunning:
                    self.proc.kill()
            except Exception:
                pass

        hops = parse_tracert("".join(self._text))
        if not hops and not error:
            error = "没有拿到路由数据"
        self.finished.emit(hops, error)
