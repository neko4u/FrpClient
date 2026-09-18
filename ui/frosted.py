"""
仅 Win11 22H2+ (build >= 22621) 生效; 其他系统自动跳过, 窗口保持普通外观(不会变透明)。
"""
import ctypes
import sys

from PyQt6.QtCore import Qt

DWMWA_SYSTEMBACKDROP_TYPE = 38   # Win11 22H2+
DWMSBT_MAINWINDOW = 2            # 云母 Mica
DWMSBT_TRANSIENTWINDOW = 3       # 亚克力 Acrylic(推荐, 颜色更透一点)


def frosted_supported():
    """是否支持系统背景材质（仅 Win11 22H2 及以上）"""
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22621
    except Exception:
        return False


def apply_frosted(window, kind=DWMSBT_TRANSIENTWINDOW):
    """给顶层窗口开启磨砂玻璃。请在 窗口 show() 之前 调用。"""
    # 1) 扩展客户区 + 标题栏背景透明 -> 系统标题栏与按钮完整保留
    flags = window.windowFlags()
    flags |= Qt.WindowType.ExpandedClientAreaHint
    window.setWindowFlags(flags)

    # 2) 低版本系统不支持 -> 直接返回, 保持普通窗口
    if not frosted_supported():
        return False

    # 3) 客户区透明, 否则 Qt 会把磨砂盖住
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # 4) 让 DWM 绘制磨砂材质
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(kind)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        return False
    return True
