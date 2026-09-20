import time

from PyQt6.QtCore import QObject, QUrl, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtWidgets import QApplication

from core.session_api import BASE_URL

DEFAULT_SIZE = 34


def circular_pixmap(src, size=DEFAULT_SIZE):
    """把图片裁成圆形（四角透明），并按屏幕缩放取高清尺寸"""
    dpr = 1.0
    screen = QApplication.primaryScreen()
    if screen is not None:
        dpr = float(screen.devicePixelRatio() or 1.0)
    px = max(1, int(round(size * dpr)))

    s = src.scaled(px, px,
                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    x = max(0, (s.width() - px) // 2)
    y = max(0, (s.height() - px) // 2)
    s = s.copy(x, y, px, px)

    out = QPixmap(px, px)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, px, px)
    p.setClipPath(path)
    p.drawPixmap(0, 0, s)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


class AvatarLoader(QObject):
    """一次加载一张头像，可重复 load() 换图（会自动丢弃上一次的请求）"""

    loaded = pyqtSignal(QPixmap)
    failed = pyqtSignal(str)

    def __init__(self, parent=None, timeout_ms=8000, size=DEFAULT_SIZE):
        super().__init__(parent)
        self.size = size
        self.manager = QNetworkAccessManager(self)
        self._reply = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._on_timeout)

    # ---- 对外 ----
    def load(self, path_or_url):
        """path_or_url: 相对路径（/media/avatars/x.png）或完整 URL；空值直接忽略"""
        if not path_or_url:
            return
        url = str(path_or_url)
        if not url.lower().startswith("http"):
            url = BASE_URL.rstrip("/") + "/" + url.lstrip("/")
        url += ("&" if "?" in url else "?") + "t=%d" % int(time.time())

        self._discard()
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._reply = self.manager.get(req)
        self._reply.finished.connect(self._on_finished)
        self._timer.start()

    # ---- 内部 ----
    def _discard(self):
        self._timer.stop()
        if self._reply is not None:
            try:
                self._reply.deleteLater()
            except Exception:
                pass
            self._reply = None

    def _on_timeout(self):
        if self._reply is not None:
            self._reply.abort()
        self._reply = None
        self.failed.emit("头像加载超时")

    def _on_finished(self):
        reply, self._reply = self._reply, None
        self._timer.stop()
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString())
                return
            data = bytes(reply.readAll().data())
            pm = QPixmap()
            if not data or not pm.loadFromData(data):
                self.failed.emit("头像数据无效")
                return
            self.loaded.emit(circular_pixmap(pm, self.size))
        finally:
            reply.deleteLater()
