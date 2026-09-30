"""
版本号规则:
  - 形如 a.b.c, 用 2 个小数点隔开, 共 3 段;
  - 每段 1~2 位数字, 不足 2 位左补 0:   1.0.1 -> 01.00.01
  - 去掉小数点得到 6 位数字串:  010001
    因为所有版本都归一到等长 6 位, 所以直接比大小就能判断新旧:
      01.00.01(010001) < 01.00.02(010002) < 10.10.12(101012)
"""

# ================= 改版本号只改这一行 =================
APP_VERSION = "0.1.0"
# =======================================

def format_version(v=APP_VERSION):
    """补零成 6 位形式: 1.0.1 -> 01.00.01"""
    parts = str(v).strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"版本号必须是 a.b.c 三段: {v!r}")
    out = []
    for p in parts:
        if not p.isdigit():
            raise ValueError(f"版本号每段必须是数字: {v!r}")
        if len(p) > 2:
            raise ValueError(f"版本号每段最多 2 位数字: {v!r}")
        out.append(p.zfill(2))          # 不足 2 位左补 0
    return ".".join(out)


def display_version(v=APP_VERSION):
    return ".".join(str(int(p)) for p in format_version(v).split("."))



def version_str(v=APP_VERSION):
    """归一化成 6 位数字串(去掉小数点): 1.0.1 -> '010001'"""
    s = str(v).strip()
    # 兼容服务器可能直接返回 6 位数字串的情况
    if "." not in s:
        return s.zfill(6)
    return format_version(s).replace(".", "")


def version_code(v=APP_VERSION):
    """归一化成整数, 用于比大小: 1.0.1 -> 10001, 10.10.12 -> 101012"""
    return int(version_str(v))


def is_newer(server_version, current_version=APP_VERSION):
    """服务器版本是否比当前新 —— 二期更新判断直接用这个"""
    try:
        return version_code(server_version) > version_code(current_version)
    except Exception:
        return False      # 服务器数据异常时不误报"有更新"
