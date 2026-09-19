import toml
import json
import os
from core.api_client import APIs
from core.paths import resource_dir

class ConfigManager:
    def __init__(self, path):
        self.path = path

    def load(self):
        return toml.load(self.path)

    def save(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            toml.dump(data, f)

    def get_basic(self):
        data = self.load()
        return data.get("serverAddr"), data.get("serverPort")

    def set_basic(self, addr, port):
        data = self.load()
        data["serverAddr"] = addr
        data["serverPort"] = int(port)
        self.save(data)

    def get_proxies(self):
        data = self.load()
        return data.get("proxies", [])

    def set_proxies(self, proxies):
        data = self.load()
        data["proxies"] = proxies
        self.save(data)

    # ---- fork: 单隧道"本地端口"读写(需求: 仅一条通道, 远程端口由服务器下发, 用户不可见) ----
    DEFAULT_LOCAL_PORT = 7777

    def get_local_port(self):
        """读取第一条隧道的 localPort, 无隧道/无配置时返回默认 7777"""
        proxies = self.get_proxies()
        if proxies:
            return int(proxies[0].get("localPort", self.DEFAULT_LOCAL_PORT))
        return self.DEFAULT_LOCAL_PORT

    def set_local_port(self, port):
        """只更新第一条隧道的 localPort(其余字段保持不动), 无隧道则补建默认隧道"""
        data = self.load()
        proxies = data.get("proxies", [])

        if proxies:
            proxies[0]["localPort"] = int(port)
        else:
            data["proxies"] = [{
                "name": "默认链接",
                "type": "tcp",
                "localIP": "127.0.0.1",
                "localPort": int(port),
                "remotePort": 6000,   # 占位, 后期由服务器下发覆盖
            }]
        data["proxies"] = proxies
        self.save(data)

        data["proxies"] = proxies
        self.save(data)

    def get_remote_port(self):
        """读取第一条隧道的 remotePort(0 表示未设置)"""
        proxies = self.get_proxies()
        if proxies:
            return int(proxies[0].get("remotePort", 0))
        return 0

    def set_remote_port(self, port):
        """写入第一条隧道的 remotePort(连接前由服务器下发的端口覆盖)"""
        data = self.load()
        proxies = data.get("proxies", [])
        if proxies:
            proxies[0]["remotePort"] = int(port)
        else:
            proxies = [{
                "name": "默认链接",
                "type": "tcp",
                "localIP": "127.0.0.1",
                "localPort": self.DEFAULT_LOCAL_PORT,
                "remotePort": int(port),
            }]
        data["proxies"] = proxies
        self.save(data)

    def get_remote_port(self):
        """读取第一条隧道的 remotePort(0 表示未设置)"""
        proxies = self.get_proxies()
        if proxies:
            return int(proxies[0].get("remotePort", 0))
        return 0

    def set_remote_port(self, port):
        """写入第一条隧道的 remotePort(连接前由服务器下发的端口覆盖)"""
        data = self.load()
        proxies = data.get("proxies", [])
        if proxies:
            proxies[0]["remotePort"] = int(port)
        else:
            proxies = [{
                "name": "默认链接",
                "type": "tcp",
                "localIP": "127.0.0.1",
                "localPort": self.DEFAULT_LOCAL_PORT,
                "remotePort": int(port),
            }]
        data["proxies"] = proxies
        self.save(data)

    # ---- fork: 隧道名 = 用户 uid(登录成功后写入, 便于 frps 面板/日志按 uid 识别) ----
    def set_proxy_name(self, name):
        name = str(name or "").strip()
        if not name:
            return False
        data = self.load()
        proxies = data.get("proxies", [])
        if proxies:
            proxies[0]["name"] = name
        else:
            proxies = [{
                "name": name,
                "type": "tcp",
                "localIP": "127.0.0.1",
                "localPort": self.DEFAULT_LOCAL_PORT,
                "remotePort": 6000,
            }]
        data["proxies"] = proxies
        self.save(data)
        return True

    def get_proxy_name(self):
        proxies = self.get_proxies()
        if proxies:
            return proxies[0].get("name", "")
        return ""

    # ---- fork: "共享文件夹(快速建站)"模式 ----
    #   关: 第一条隧道转发到本地端口(原有业务)
    #   开: 给第一条隧道挂 static_file 插件, 由 frpc 直接服务该文件夹
    #       (挂了插件后 frpc 会忽略 localIP/localPort, 已实测)
    #   两种模式共用同一条隧道 / 同一个 remotePort, 所以对外地址不变。
    STATIC_PLUGIN = "static_file"
    PREF_STATIC_FOLDER = "static_site_folder"

    def set_static_site(self, folder, enabled):
        """切换第一条隧道的模式; 返回是否写盘成功。
        enabled=True  -> 挂上 static_file 插件(需要 folder 非空)
        enabled=False -> 只删掉 plugin; localIP/localPort 原样保留, 切回来不丢端口号"""
        data = self.load()
        proxies = data.get("proxies", [])
        if not proxies:
            return False
        if enabled:
            folder = str(folder or "").strip()
            if not folder:
                return False
            proxies[0]["plugin"] = {"type": self.STATIC_PLUGIN, "localPath": folder}
        else:
            proxies[0].pop("plugin", None)
        data["proxies"] = proxies
        self.save(data)
        return True

    def is_static_site(self):
        """当前是否处于"共享文件夹"模式(以 frpc.toml 为唯一权威),持久化"""
        proxies = self.get_proxies()
        if not proxies:
            return False
        return (proxies[0].get("plugin") or {}).get("type") == self.STATIC_PLUGIN

    def get_static_folder(self):
        """读取当前共享的文件夹路径(不在该模式时返回空串)"""
        proxies = self.get_proxies()
        if not proxies:
            return ""
        plugin = proxies[0].get("plugin") or {}
        if plugin.get("type") != self.STATIC_PLUGIN:
            return ""
        return plugin.get("localPath", "") or ""

    # ---- 客户端本地偏好(存 resources/config.json, 与 frpc.toml 无关) ----
    def get_pref(self, key, default=None):
        try:
            with open(os.path.join(resource_dir(), "config.json"), "r", encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except Exception:
            return default

    def set_pref(self, key, value):
        path = os.path.join(resource_dir(), "config.json")
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def get_token(self):
        data = self.load()
        return data.get("auth", {}).get("token")





    def set_token(self, token):
        data = self.load()

        if "auth" not in data:
            data["auth"] = {}

        data["auth"]["token"] = token

        self.save(data)

    def update_token_from_api(self, user_token):
        try:
            with open(os.path.join(resource_dir(), "config.json"), "r", encoding="utf-8") as f:
                cfg = json.load(f)

            api_url = cfg.get("frp_token_api")

            if not api_url:
                print("未配置 frp_token_api")
                return False

            frp_token, err = APIs.fetch_frp_token(api_url, user_token)

            print("接口返回:", frp_token, err)

            if not frp_token:
                print("获取 token 失败:", err)
                return False

            self.set_token(frp_token)

            print("写入后的 token:", self.get_token())

            return True

        except Exception as e:
            print("更新 token 异常:", e)
            return False