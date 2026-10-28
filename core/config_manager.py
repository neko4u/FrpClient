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
    
    def ensure_server_addr(self):
        """启动兜底：用 resources/config.json 的 frp_server_addr/port 初始化 frpc.toml。

        为什么需要：frpc.toml 被 .gitignore 排除、不在仓库里，换机重建时没有可靠来源。
        为什么安全：连接时服务器还会再下发一次（_on_allocate_done 里覆盖），
        而 frpc 只在 allocate 之后才启动 —— 所以这里写入的旧值不会真正被用上。
        """
        try:
            addr = (self.get_pref("frp_server_addr") or "").strip()
            if not addr:
                return False
            port = int(self.get_pref("frp_server_port") or 0) or 7000

            data = self.load()
            if data.get("serverAddr") == addr and int(data.get("serverPort") or 0) == port:
                return False
            data["serverAddr"] = addr
            data["serverPort"] = port
            self.save(data)
            print("已从 config.json 初始化 frps 控制地址:", addr, port)
            return True
        except Exception as e:
            print("初始化 frps 控制地址失败:", e)
            return False

    # ---- 被动网络观测: 让 frpc 打出心跳日志（只加配置键, 不改传输方式） ----

    def ensure_network_probe(self):
        """写入网络观测必需的两段 frpc 配置：

            [log]       level = "debug"
            [transport] heartbeatInterval = 30
                        heartbeatTimeout  = 90

        为什么必须显式写：frp v0.65 的 ClientTransportConfig.Complete() 在
        tcpMux(默认 true) 开启时把 HeartbeatInterval / HeartbeatTimeout 置为 -1，
        即应用层 Ping/Pong 被关闭、交给 TCPMux 自己的 keepalive —— 那一层不产生
        任何日志，不写这两项就一条心跳行都读不到。
        这里只新增配置键，tcpMux 保持默认，隧道数据路径不变。
        """
        import os
        try:
            if not os.path.exists(self.path):
                return False
            try:
                data = self.load()
            except Exception:
                return False

            changed = False

            log_cfg = data.get("log")
            if not isinstance(log_cfg, dict):
                log_cfg = {}
            if log_cfg.get("level") != "debug":
                log_cfg["level"] = "debug"
                changed = True
            data["log"] = log_cfg

            tr = data.get("transport")
            if not isinstance(tr, dict):
                tr = {}
            if int(tr.get("heartbeatInterval") or 0) != 30:
                tr["heartbeatInterval"] = 30
                changed = True
            if int(tr.get("heartbeatTimeout") or 0) != 90:
                tr["heartbeatTimeout"] = 90
                changed = True
            data["transport"] = tr

            if changed:
                self.save(data)
                print("已写入网络观测配置: log.level=debug, "
                      "transport.heartbeatInterval=30, heartbeatTimeout=90")
            return changed
        except Exception as e:
            print("写入网络观测配置失败:", e)
            return False

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
        except FileNotFoundError:
            data = {}
        except Exception as e:
            try:
                import shutil
                shutil.copyfile(path, path + ".bad")
            except Exception:
                pass
            print("config.json 解析失败, 原文件已备份为 config.json.bad, 本次不写入:", e)
            return False
        data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

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

            info, err = APIs.fetch_frp_token(api_url, user_token)

            print("接口返回:", info, err)

            if not info:
                print("获取 token 失败:", err)
                return False

            data = self.load()
            data.setdefault("auth", {})["token"] = info["config_token"]

            # frps 控制地址以服务器下发为准；未下发则保留 frpc.toml 里已有的值
            addr = (info.get("frps_addr") or "").strip()
            port = info.get("frps_port") or 0
            if addr:
                data["serverAddr"] = addr
                if port:
                    data["serverPort"] = int(port)
                print("已按服务器下发更新 frps 控制地址:", addr, port)

            self.save(data)
            print("写入后的 token:", self.get_token())
            return True

        except Exception as e:
            print("更新 token 异常:", e)
            return False