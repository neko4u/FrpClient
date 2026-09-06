import os
import sys
import shutil


def is_frozen():
    """是否被打包成 exe"""
    return getattr(sys, "frozen", False)


def base_dir():
    """exe 所在目录(打包后)或项目根目录(开发时)"""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    """可读写的资源目录:始终位于 exe 旁边(或项目根目录)的 resources 文件夹"""
    return os.path.join(base_dir(), "resources")


def ensure_resources():
    """
    单文件打包后首次运行时,把内置资源(临时解压目录 _MEIPASS 中)
    释放到 exe 旁边的 resources 文件夹,之后所有读写都基于该文件夹。
    开发模式下无需处理。
    """
    if not is_frozen():
        return

    target = resource_dir()
    if os.path.isdir(target):
        return

    src = os.path.join(sys._MEIPASS, "resources")
    try:
        shutil.copytree(src, target)
        print("已释放资源到:", target)
    except Exception as e:
        print("释放资源失败:", e)
