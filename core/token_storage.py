import json
import os
import time
import hashlib
import platform

from core.paths import resource_dir
from core.jwt_utils import decode_jwt_payload

SAVE_PATH = os.path.join(resource_dir(), "token.json")


def get_device_id():
    raw = platform.node() + platform.processor()
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenStorage:

    @staticmethod
    def save(token, expires_in_days=3):
        """保存 token。过期时间优先用 JWT 自身的 exp（服务端权威，3天）"""
        expire_at = None
        payload = decode_jwt_payload(token)
        if payload and payload.get("exp"):
            expire_at = float(payload["exp"])
        if not expire_at:
            expire_at = time.time() + expires_in_days * 86400

        data = {
            "token": token,
            "expire_at": expire_at,
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

            token = data.get("token")
            if not token:
                return None

            if time.time() > data.get("expire_at", 0):
                TokenStorage.clear()
                return None

            # JWT 自身过期校验（与服务端一致）
            payload = decode_jwt_payload(token)
            if not payload or not payload.get("exp"):
                TokenStorage.clear()
                return None
            if time.time() > float(payload["exp"]):
                TokenStorage.clear()
                return None

            return token

        except Exception:
            return None

    @staticmethod
    def clear():
        if os.path.exists(SAVE_PATH):
            os.remove(SAVE_PATH)
