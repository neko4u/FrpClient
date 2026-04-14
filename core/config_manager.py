import toml

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