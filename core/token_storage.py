import json
import os
import time
import hashlib
import platform

SAVE_PATH = "resources/token.json"

def get_device_id():
    # 防止复制
    raw = platform.node() + platform.processor()
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenStorage:

    @staticmethod
    def save(token, expires_in_days=5):
        data = {
            "token": token,
            "expire_at": time.time() + expires_in_days * 86400,
            "device_id": get_device_id()
        }
        with open(SAVE_PATH, "w") as f:
            json.dump(data, f)

    @staticmethod
    def load():
        if not os.path.exists(SAVE_PATH):
            return None

        try:
            with open(SAVE_PATH, "r") as f:
                data = json.load(f)

            if data.get("device_id") != get_device_id():
                return None

            if time.time() > data.get("expire_at", 0):
                return None

            return data.get("token")

        except:
            return None

    @staticmethod
    def clear():
        if os.path.exists(SAVE_PATH):
            os.remove(SAVE_PATH)