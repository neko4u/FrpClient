"""历史日志窗口：看近 7 天的持久化日志（与"运行日志"窗口是两套东西）

运行日志  -> ui/main_window.py 里的 LogWindow：本次运行实时刷屏，内存，不落盘
历史日志  -> 这个窗口：读 core/app_log.py 按天写的文件，保留 7 天
"""
import os

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QTextEdit, QMessageBox)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

from core import app_log

# 样式跟主界面一致，但不 import main_window（否则与之循环 import）
BTN_QSS = """
QPushButton{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #eef2f7);
    border:1px solid #cfd8e3; border-radius:6px; padding:4px 12px;
    font-size:12px; color:#25303f;
}
QPushButton:hover{border:1px solid #9fc0e8;}
QPushButton:disabled{background:#f2f4f7;color:#aab2bf;border:1px solid #e3e8ef;}
"""

COMBO_QSS = """
QComboBox{background:#ffffff;border:1px solid #cfd8e3;border-radius:6px;
          padding:3px 10px;font-size:12px;color:#25303f;}
QComboBox:hover{border:1px solid #9fc0e8;}
"""

# ---- 把落盘的机器日志翻成人话（不改存储格式，只改显示） ----
_CH_NAME = {"frps": "隧道通道", "django": "平台通道", "frpc": "隧道", "-": ""}
_NET_STATUS = {"green": "网络良好", "yellow": "网络一般", "red": "网络差",
               "unknown": "刚连接，正在观察"}
_SESS_STATUS = {"active": "时长已开启", "idle": "时长未开启", "connecting": "正在开启",
                "stopping": "正在暂停", "error": "异常"}
_FRP_STATUS = {"connected": "已连接", "connecting": "连接中", "stopped": "已断开",
               "failed": "连接失败"}
_OVERALL = {"OK": "连接质量良好", "WARN": "连接质量一般", "BAD": "连接质量差"}


def _kv(metrics):
    """rtt=182ms base=61ms timeout=0 consec=0 -> 延迟 182 毫秒 / 基线 61 毫秒"""
    out = []
    for part in (metrics or "").split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "rtt":
            out.append("延迟 " + v.replace("ms", " 毫秒"))
        elif k == "base":
            out.append("基线 " + v.replace("ms", " 毫秒"))
        elif k == "timeout" and v != "0":
            out.append("心跳超时")
        elif k == "consec" and v not in ("0", ""):
            out.append("连续 %s 次" % v)
    return " / ".join(out)


def friendly_line(raw):
    """原始日志行 -> 面向用户的句子；解析不了就原样返回"""
    try:
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 6:
            return raw
        ts, kind, channel, status, metrics, text = parts[0], parts[1], parts[2], \
            parts[3].lower(), parts[4], "|".join(parts[5:]).strip()
        hhmmss = ts[11:19] if len(ts) >= 19 else ts

        if kind == "net":
            name = _CH_NAME.get(channel, channel)
            head = "%s  %s：%s" % (hhmmss, name, _NET_STATUS.get(status, status))
            detail = _kv(metrics)
            return head + (("    " + detail) if detail else "")

        if kind == "sess":
            return "%s  平台会话：%s" % (hhmmss, _SESS_STATUS.get(status, status))

        if kind == "frp":
            if status == "raw":
                return "%s  [隧道] %s" % (hhmmss, text)
            return "%s  隧道：%s" % (hhmmss, _FRP_STATUS.get(status, status))

        if kind == "app":
            return "%s  %s" % (hhmmss, text)

        if kind == "test":
            return "%s  网络检测：%s" % (hhmmss, _OVERALL.get(status.upper(), status))

        return raw
    except Exception:
        return raw


class LogViewerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史日志（近 7 天）")
        self.setMinimumSize(760, 520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # ---- 顶部：日期选择 + 刷新 + 打开目录 ----
        top = QHBoxLayout()
        top.addWidget(QLabel("日期:"))
        self.day_box = QComboBox()
        self.day_box.setMinimumWidth(150)
        self.day_box.setStyleSheet(COMBO_QSS)
        self.day_box.currentIndexChanged.connect(self._load_current)
        top.addWidget(self.day_box)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedSize(70, 30)
        self.refresh_btn.setStyleSheet(BTN_QSS)
        self.refresh_btn.clicked.connect(self.reload)
        top.addWidget(self.refresh_btn)

        self.dir_btn = QPushButton("打开目录")
        self.dir_btn.setFixedSize(90, 30)
        self.dir_btn.setStyleSheet(BTN_QSS)
        self.dir_btn.clicked.connect(self._open_dir)
        top.addWidget(self.dir_btn)

        top.addStretch()
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("font-size:11px;color:#888780;")
        top.addWidget(self.path_label)
        lay.addLayout(top)

        # ---- 正文 ----
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "QTextEdit{background:#ffffff;border:1px solid #e2e7ef;border-radius:10px;"
            "padding:10px 12px;line-height:175%;color:#25303f;"
            "font-family:'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',sans-serif;"
            "font-size:14px;}")
        lay.addWidget(self.view, 1)

        self.hint = QLabel("")
        self.hint.setStyleSheet("font-size:11px;color:#888780;")
        lay.addWidget(self.hint)

        self.reload()

    # ---------------- 数据 ----------------

    def reload(self):
        days = app_log.list_days()
        cur = self.day_box.currentData()
        self.day_box.blockSignals(True)
        self.day_box.clear()
        for key, _path, size in days:
            self.day_box.addItem("%s（%.0f KB）" % (key, size / 1024.0), key)
        if cur:
            idx = self.day_box.findData(cur)
            if idx >= 0:
                self.day_box.setCurrentIndex(idx)
        self.day_box.blockSignals(False)

        self.path_label.setText(app_log.log_dir())
        total = app_log.total_bytes() / 1024.0
        self.hint.setText("日志目录：%s    共 %d 个文件 / %.0f KB    保留 %d 天"
                          % (app_log.log_dir(), len(days), total, app_log.RETENTION_DAYS))
        self._load_current()

    def _load_current(self):
        key = self.day_box.currentData()
        if not key:
            self.view.setPlainText("（还没有日志文件）")
            return
        raw = app_log.read_day(key)
        if not raw.strip():
            self.view.setPlainText("（这一天没有记录）")
            return
        lines = [friendly_line(x) for x in raw.splitlines() if x.strip()]
        self.view.setPlainText("\n".join(lines))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _open_dir(self):
        path = app_log.log_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.information(self, "提示", "无法打开目录：\n%s" % path)
