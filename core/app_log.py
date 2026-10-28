"""持久化日志（与主界面"运行日志"窗口完全分离）

为什么另起一套：
  "运行日志"窗口只放本次运行的实时刷屏，内存 800 行、滚掉即丢、不落盘；
  排障要回溯到几天前，所以再要一套按天落盘的。

约定：
  - 按天一个文件: <日志目录>/frpclient-YYYYMMDD.log
  - 保留 7 天: 启动时清理 mtime 超期文件；运行中跨天自动写新文件
  - 单文件超 5MB 滚动成 .1（覆盖旧的 .1），防止某天刷爆
  - 只落"事件"与 frpc 的 [I]/[W]/[E] 行；frpc 的 debug 行不落（那只用于心跳 RTT 配对）

日志目录（成熟做法：便携软件用 exe 同级，装到 Program Files 时才回退用户目录）：
  1) <exe 所在目录>/logs
  2) 不可写 -> %LOCALAPPDATA%/SorielConnection/logs

行格式（竖线分隔，人能读、程序能解析）：
  2026-10-28 20:31:02.417 | net | frps | WARN | rtt=182ms base=61ms timeout=0 consec=0 | RTT 偏高
"""
import os
import json
import time
from datetime import datetime

from core.paths import base_dir

RETENTION_DAYS = 7
MAX_BYTES = 5 * 1024 * 1024
DIR_NAME = "logs"
FILE_PREFIX = "frpclient"
APP_DIR_NAME = "SorielConnection"

_dir_cache = {"path": None}


# ---------------------------------------------------------------- 目录

def _writable(path):
    """真写一个文件来判断可写，别只看 os.access（Windows 上经常骗人）"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def log_dir():
    """当前实际使用的日志目录（结果缓存，UI 上要展示这个真实路径）"""
    if _dir_cache["path"]:
        return _dir_cache["path"]

    candidates = []
    try:
        candidates.append(os.path.join(base_dir(), DIR_NAME))
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    candidates.append(os.path.join(local, APP_DIR_NAME, DIR_NAME))

    for d in candidates:
        if _writable(d):
            _dir_cache["path"] = d
            return d

    _dir_cache["path"] = candidates[-1]     # 都不行也别抛异常，日志写失败不致命
    return _dir_cache["path"]


# ---------------------------------------------------------------- 写

def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _path_for(now):
    return os.path.join(log_dir(), "%s-%s.log" % (FILE_PREFIX, now.strftime("%Y%m%d")))


def _rotate_if_needed(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_BYTES:
            keep = path + ".1"
            if os.path.exists(keep):
                os.remove(keep)
            os.replace(path, keep)
    except Exception:
        pass


def _emit(row):
    """写一行；任何异常都吞掉——日志不能影响主流程"""
    try:
        now = datetime.now()
        path = _path_for(now)
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except Exception:
        pass


def _row(kind, channel, status, metrics, text):
    return "%s | %s | %s | %s | %s | %s" % (
        _now_str(), kind, channel or "-", status or "-", metrics or "", text or "")


# ---------------------------------------------------------------- 对外接口

def net(channel, status, rtt=None, base=None, timeout=None, consec=None, text=""):
    """网络质量事件：通道名 / 状态 / RTT / 基线 / 是否超时 / 连续超时次数"""
    kv = []
    if rtt is not None:
        kv.append("rtt=%dms" % int(round(rtt)))
    if base is not None:
        kv.append("base=%dms" % int(round(base)))
    if timeout is not None:
        kv.append("timeout=%d" % (1 if timeout else 0))
    if consec is not None:
        kv.append("consec=%d" % int(consec))
    _emit(_row("net", channel, status.upper(), " ".join(kv), text))


def session(status, text=""):
    _emit(_row("sess", "django", str(status).upper(), "", text))


def frp(status, text=""):
    _emit(_row("frp", "frpc", str(status).upper(), "", text))


def frpc_line(line):
    """frpc 原始输出行（保留它自己的时间戳，原样追加在事件说明里）"""
    _emit(_row("frp", "frpc", "RAW", "", line))


def app(text, status="INFO"):
    _emit(_row("app", "-", status, "", text))


# ---------------------------------------------------------------- 清理 / 浏览

def cleanup(retention_days=RETENTION_DAYS):
    """删掉超过保留期的日志文件；返回删掉的文件名列表"""
    removed = []
    cutoff = time.time() - retention_days * 86400
    directory = log_dir()
    try:
        for name in os.listdir(directory):
            if not name.startswith(FILE_PREFIX) or ".log" not in name:
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed.append(name)
            except Exception:
                pass
    except Exception:
        pass
    return removed


def list_days():
    """[(YYYYMMDD, 路径, 字节数)]，新日期在前"""
    out = []
    directory = log_dir()
    try:
        for name in os.listdir(directory):
            if not name.startswith(FILE_PREFIX) or not name.endswith(".log"):
                continue
            path = os.path.join(directory, name)
            key = name[len(FILE_PREFIX) + 1:-4]
            try:
                out.append((key, path, os.path.getsize(path)))
            except Exception:
                pass
    except Exception:
        pass
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def read_day(key):
    """读某一天的全部日志文本；找不到返回空串"""
    for k, path, _size in list_days():
        if k == key:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                return ""
    return ""


def total_bytes():
    return sum(size for _k, _p, size in list_days())


# ---------------------------------------------------------------- 网络检测记录

def l1_result(payload):
    """存一条主动检测结果（结构化 JSON 放最后一列，便于回收渲染）"""
    try:
        _emit(_row("test", "L1",
                   str(payload.get("overall", "-")).upper(), "",
                   json.dumps(payload, ensure_ascii=False)))
    except Exception:
        pass


def l1_history(limit=30):
    """读回历史检测记录，新的在前"""
    out = []
    for _key, path, _size in list_days():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "| test | L1 |" not in line:
                        continue
                    tail = line.rsplit("|", 1)[-1].strip()
                    try:
                        obj = json.loads(tail)
                    except Exception:
                        continue
                    obj["_ts"] = line.split("|", 1)[0].strip()[:16]
                    out.append(obj)
        except Exception:
            continue
    out.sort(key=lambda x: x.get("_ts", ""), reverse=True)
    return out[:limit]
