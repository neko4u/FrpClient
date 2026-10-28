"""网络连接测试子页面（工具 → 网络连接测试，或主页状态灯右侧"详情"）

结构：
  顶部  两路链路的实时状态（被动只读）
  中部  [开始检测] / [取消] + 进度条
  下部  「本次结果」/「历史记录」两个页签
  底部  [关闭]

文案分两档：
  普通模式 —— 只给结论（延迟正常 / 波动正常 / 无丢包 / 连接质量良好），
             不显示目标地址、不显示 RTT、基线、样本数
  调试模式 —— 才显示 host:port、样本数、丢包数、平均/P50/P95、抖动等原始数字
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QProgressBar, QTextEdit, QFrame,
                             QTabWidget, QWidget)
from PyQt6.QtCore import QTimer

from core import app_log
from core.net_probe import (L1Probe, OK, WARN, BAD,
                            GREEN, YELLOW, RED, UNKNOWN, STATUS_TEXT)

BTN_QSS = """
QPushButton{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #eef2f7);
    border:1px solid #cfd8e3; border-radius:6px; padding:5px 14px;
    font-size:13px; color:#25303f;
}
QPushButton:hover{border:1px solid #9fc0e8;}
QPushButton:disabled{background:#f2f4f7;color:#aab2bf;border:1px solid #e3e8ef;}
"""

# 圆润一点的正文字体（Windows 上优先微软雅黑 UI）
TEXT_QSS = """
QTextEdit{
    background:#ffffff; border:1px solid #e2e7ef; border-radius:10px;
    padding:10px 12px;
    font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC",sans-serif;
    font-size:14px; line-height:170%; color:#25303f;
}
"""

TAB_QSS = """
QTabWidget::pane{border:1px solid #e2e7ef;border-radius:10px;background:#ffffff;}
QTabBar::tab{background:transparent;color:#6b7280;padding:6px 16px;font-size:13px;
             font-family:"Microsoft YaHei UI",sans-serif;}
QTabBar::tab:selected{color:#1f6fd0;font-weight:bold;}
"""

DOT_COLOR = {
    GREEN: "#2e9e4f",
    YELLOW: "#e0a63c",
    RED: "#d64545",
    UNKNOWN: "#9aa5b5",
}

# --- 对用户说的话（不用 OK/WARN/BAD，也不用"抖动"这种词） ---
RTT_TEXT = {OK: "延迟正常", WARN: "延迟偏高", BAD: "延迟很高", "N/A": "没有测到延迟"}
JIT_TEXT = {OK: "波动正常", WARN: "波动偏大", BAD: "波动很大", "N/A": "波动未知"}
LOSS_TEXT = {OK: "无丢包", WARN: "轻微丢包", BAD: "明显丢包", "N/A": "丢包未知"}
OVERALL_TEXT = {OK: "连接质量良好", WARN: "连接质量一般", BAD: "连接质量差"}


class NetDetailDialog(QDialog):
    def __init__(self, monitor, targets, parent=None, debug=False):
        super().__init__(parent)
        self.monitor = monitor
        self.targets = targets
        self.probe = None
        self.debug = bool(debug)
        self._last_result = None

        self.setWindowTitle("网络连接测试")
        self.setFixedSize(560, 590)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        title_qss = ("font-size:13px;font-weight:bold;color:#25303f;"
                     "font-family:'Microsoft YaHei UI',sans-serif;")

        # ================= 实时状态 =================
        t1 = QLabel("当前链路状态")
        t1.setStyleSheet(title_qss)
        lay.addWidget(t1)

        self.rows = {}
        for key, caption in (("frps", "隧道通道"), ("django", "平台通道")):
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet("color:#9aa5b5;font-size:15px;")
            cap = QLabel(caption)
            cap.setFixedWidth(74)
            cap.setStyleSheet("font-family:'Microsoft YaHei UI',sans-serif;font-size:13px;")
            val = QLabel("检测中")
            val.setStyleSheet("color:#25303f;font-family:'Microsoft YaHei UI',sans-serif;"
                              "font-size:13px;")
            detail = QLabel("")          # 仅调试模式显示
            detail.setStyleSheet("color:#9aa5b5;font-size:11px;")
            row.addWidget(dot)
            row.addWidget(cap)
            row.addWidget(val)
            row.addSpacing(10)
            row.addWidget(detail)
            row.addStretch()
            lay.addLayout(row)
            self.rows[key] = (dot, val, detail)

        # ================= 分割线 =================
        lay.addSpacing(6)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background:#e6ebf2;border:none;")
        lay.addWidget(line)
        lay.addSpacing(6)

        # ================= 操作行 =================
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始检测")
        self.start_btn.setFixedSize(96, 32)
        self.start_btn.setStyleSheet(BTN_QSS)
        self.start_btn.clicked.connect(self.start_probe)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(72, 32)
        self.cancel_btn.setStyleSheet(BTN_QSS)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_probe)
        btn_row.addWidget(self.cancel_btn)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 32)
        self.progress.setValue(0)
        self.progress.setStyleSheet(
            "QProgressBar{border:1px solid #e2e7ef;border-radius:6px;background:#f7f9fc;}"
            "QProgressBar::chunk{background:#8cbff2;border-radius:5px;}")
        btn_row.addWidget(self.progress, 1)
        lay.addLayout(btn_row)

        # ================= 结果 / 历史 =================
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TAB_QSS)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setStyleSheet(TEXT_QSS)
        self.result_view.setPlainText("点「开始检测」测一下当前网络。")

        self.history_view = QTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setStyleSheet(TEXT_QSS)

        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        l1.setContentsMargins(6, 6, 6, 6)
        l1.addWidget(self.result_view)

        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        l2.setContentsMargins(6, 6, 6, 6)
        l2.addWidget(self.history_view)

        self.tabs.addTab(tab1, "本次结果")
        self.tabs.addTab(tab2, "历史记录")
        lay.addWidget(self.tabs, 1)

        # ================= 关闭 =================
        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.setFixedSize(80, 30)
        self.close_btn.setStyleSheet(BTN_QSS)
        self.close_btn.clicked.connect(self.close)
        close_row.addWidget(self.close_btn)
        lay.addLayout(close_row)

        # 每秒刷一次实时状态（纯读快照，不采集）
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.refresh_passive)
        self._tick.start()
        self.refresh_passive()
        self.reload_history()

    # ---------------- 调试模式 ----------------

    def set_debug(self, on):
        self.debug = bool(on)
        self.refresh_passive()
        if self._last_result:
            self.result_view.setPlainText(self._render(self._last_result))
        self.reload_history()

    # ---------------- 被动显示 ----------------

    def refresh_passive(self):
        snap = self.monitor.snapshot()
        for key in ("frps", "django"):
            ch = snap.get(key) or {}
            dot, val, detail = self.rows[key]
            st = ch.get("status", UNKNOWN)
            dot.setStyleSheet("color:%s;font-size:15px;" % DOT_COLOR.get(st, "#9aa5b5"))
            val.setText(STATUS_TEXT.get(st, "采样中"))

            if not self.debug:
                detail.setText("")
                continue

            bits = ["RTT %s" % (("%dms" % int(round(ch["rtt"])))
                                if ch.get("rtt") is not None else "--")]
            if ch.get("base") is not None:
                bits.append("基线 %dms" % int(round(ch["base"])))
            bits.append("样本 %d/10" % ch.get("samples", 0))
            if ch.get("timeout"):
                bits.append("连续超时 %d" % ch["timeout"])
            detail.setText("    ".join(bits))

    # ---------------- 主动检测 ----------------

    def start_probe(self):
        if self.probe is not None and not self.probe.done:
            return
        self.tabs.setCurrentIndex(0)
        self.result_view.setPlainText("正在检测…")
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.monitor.set_suspended(True)

        self.probe = L1Probe(self.targets, self)
        self.probe.progress.connect(self.on_progress)
        self.probe.finished.connect(self.on_finished)
        self.probe.failed.connect(self.on_failed)
        self.probe.start()

    def cancel_probe(self):
        if self.probe is not None:
            self.probe.cancel()

    def on_progress(self, channel, done, total):
        base = 0 if channel == "frps" else 20
        self.progress.setRange(0, 32)
        self.progress.setValue(base + done)

    def on_failed(self, msg):
        self.monitor.set_suspended(False)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.result_view.setPlainText("检测没能完成：%s" % msg)

    def on_finished(self, result):
        self.monitor.set_suspended(False)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        self._last_result = result
        self.result_view.setPlainText(self._render(result))

        app_log.l1_result({
            "overall": result.get("overall"),
            "elapsed": result.get("elapsed"),
            "note": result.get("note", ""),
            "channels": {
                k: {kk: v.get(kk) for kk in
                    ("sent", "lost", "loss_pct", "rtt_avg", "rtt_p50", "rtt_p95",
                     "jitter", "stop_reason")}
                for k, v in (result.get("channels") or {}).items()
            },
            "verdict": {k: v.get("verdict") for k, v in
                        (result.get("channels") or {}).items()},
        })
        self.reload_history()

    def _render(self, r):
        """普通模式只给结论；调试模式追加原始数字与目标地址"""
        lines = []
        for key, caption in (("frps", "隧道通道"), ("django", "平台通道")):
            ch = (r.get("channels") or {}).get(key)
            if not ch:
                continue
            v = ch.get("verdict") or {}
            lines.append(caption)

            if v.get("rtt") == OK and v.get("jitter") == OK and v.get("loss") == OK:
                lines.append("  延迟、波动、丢包 3 项都正常")
            else:
                lines.append("  %s · %s · %s" % (
                    RTT_TEXT.get(v.get("rtt"), "延迟未知"),
                    JIT_TEXT.get(v.get("jitter"), "波动未知"),
                    LOSS_TEXT.get(v.get("loss"), "丢包未知")))

            if self.debug:
                host, port = self.targets.get(key, ("-", "-"))
                lines.append("  目标 %s:%s" % (host, port))
                lines.append("  样本 %d，丢失 %d（%.0f%%）" % (
                    ch.get("sent") or 0, ch.get("lost") or 0, ch.get("loss_pct") or 0))
                if ch.get("rtt_avg") is not None:
                    lines.append("  平均 %.0fms / P50 %.0fms / P95 %.0fms / 抖动 %.0fms" % (
                        ch["rtt_avg"], ch["rtt_p50"], ch["rtt_p95"], ch["jitter"]))
                if ch.get("stop_reason"):
                    lines.append("  %s" % ch["stop_reason"])
            lines.append("")

        overall = "已取消" if r.get("canceled") else OVERALL_TEXT.get(
            r.get("overall"), "结果未知")
        lines.append("总判定：%s" % overall)
        if self.debug:
            lines.append("用时 %.1fs%s" % (r.get("elapsed") or 0,
                                         ("，" + r["note"]) if r.get("note") else ""))
        return "\n".join(lines)

    def reload_history(self):
        records = app_log.l1_history(30)
        if not records:
            self.history_view.setPlainText("还没有历史记录。")
            return

        lines = []
        for rec in records:
            overall = OVERALL_TEXT.get(rec.get("overall"), "结果未知")
            parts = []
            for key, caption in (("frps", "隧道"), ("django", "平台")):
                ch = (rec.get("channels") or {}).get(key) or {}
                v = (rec.get("verdict") or {}).get(key) or {}
                if not ch:
                    continue
                if v.get("rtt") == OK and v.get("jitter") == OK and v.get("loss") == OK:
                    parts.append("%s 正常" % caption)
                else:
                    parts.append("%s %s" % (caption, LOSS_TEXT.get(v.get("loss"), "有异常")))
            lines.append("%s    %s" % (rec.get("_ts", ""), overall))
            if parts:
                lines.append("              " + " · ".join(parts))
        self.history_view.setPlainText("\n".join(lines))

    # ---------------- 生命周期 ----------------

    def closeEvent(self, event):
        try:
            self._tick.stop()
            if self.probe is not None and not self.probe.done:
                self.probe.cancel()
        except Exception:
            pass
        super().closeEvent(event)
