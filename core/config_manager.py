import toml
import json
from core.api_client import APIs

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
            with open("resources/config.json", "r", encoding="utf-8") as f:
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