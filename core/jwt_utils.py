import base64
import json


def decode_jwt_payload(token):
    """解码 JWT 的 payload 段（第二段，base64url）。读取无需密钥。失败返回 None。"""
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(raw)
    except Exception:
        return None


def get_uid_from_token(token):
    """从登录返回的 JWT 中提取 uid（转成 str）。失败返回 None。"""
    payload = decode_jwt_payload(token)
    if not payload:
        return None
    uid = payload.get("uid")
    return str(uid) if uid is not None else None
