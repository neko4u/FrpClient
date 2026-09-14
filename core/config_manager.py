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