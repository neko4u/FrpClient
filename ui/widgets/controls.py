from PyQt6.QtCore import (Qt, QRectF, QPropertyAnimation, QEasingCurve,
                          pyqtProperty, pyqtSignal)
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget, QLabel, QMessageBox


def _lerp(c1, c2, t):
    """两个颜色按 t(0~1) 线性混合"""
    return QColor(int(c1.red() + (c2.red() - c1.red()) * t),
                  int(c1.green() + (c2.green() - c1.green()) * t),
                  int(c1.blue() + (c2.blue() - c1.blue()) * t))


class ToggleSwitch(QWidget):
    """滑动开关

    - 点击切换（禁用时不响应）
    - setChecked(checked, animate=False) 可在初始化时直接摆到位（不播动画）
    - toggled(bool) 只在状态真正变化时发出
    """

    toggled = pyqtSignal(bool)

    W, H = 46, 24        # 控件尺寸
    GAP = 2              # 滑块与轨道边缘的间距
    ANIM_MS = 180        # 过渡时长

    TRACK_OFF = QColor("#cfd8e3")
    TRACK_ON = QColor("#12b7f5")
    TRACK_DISABLED = QColor("#e3e8ef")
    KNOB = QColor("#ffffff")

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._checked = bool(checked)
        self._knob = 1.0 if self._checked else 0.0     # 0.0=关, 1.0=开
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ---- 供动画驱动的属性(不要叫 pos, 会覆盖 QWidget.pos) ----
    def _get_knob(self):
        return self._knob

    def _set_knob(self, v):
        self._knob = float(v)
        self.update()

    knobPos = pyqtProperty(float, fget=_get_knob, fset=_set_knob)

    # ---- 对外接口 ----
    def isChecked(self):
        return self._checked

    def setChecked(self, checked, animate=True):
        checked = bool(checked)
        if checked == self._checked:
            self._slide(checked, animate=False)        # 状态没变也要把滑块摆到位
            return
        self._checked = checked
        self._slide(checked, animate=animate)
        self.toggled.emit(checked)

    def toggle(self):
        """用户动作入口: 禁用时不响应(程序置位请用 setChecked)"""
        if not self.isEnabled():
            return
        self.setChecked(not self._checked)

    def _slide(self, checked, animate=True):
        target = 1.0 if checked else 0.0
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(self._knob)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._set_knob(target)

    # ---- 交互 ----
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.toggle()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0

        if self.isEnabled():
            track = _lerp(self.TRACK_OFF, self.TRACK_ON, self._knob)
        else:
            track = self.TRACK_DISABLED
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        d = h - self.GAP * 2                            # 滑块直径
        x = self.GAP + (w - d - self.GAP * 2) * self._knob
        p.setBrush(self.KNOB)
        p.drawEllipse(QRectF(x, self.GAP, d, d))
        p.end()


class InfoDot(QLabel):
    """圆形 "!" 提示图标：hover 显示 tooltip，点击弹出同一段说明"""

    def __init__(self, text, parent=None):
        super().__init__("!", parent)
        self._text = text
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setToolTip(text)
        self.setStyleSheet(
            "QLabel{background:#eaf2ff;border:1px solid #9fc0e8;border-radius:8px;"
            "color:#2b6cb0;font-size:11px;font-weight:bold;}")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            QMessageBox.information(self.window(), "说明", self._text)
        super().mouseReleaseEvent(event)
