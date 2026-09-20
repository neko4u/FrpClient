"""FRP 会话接口封装（异步，QNetworkAccessManager，不阻塞 UI）

对接 Django:
  POST /api/frp_session/start      -> {code, session_id, balance_seconds, stop_time_ts, reused}
  POST /api/frp_session/heartbeat  -> {code, closed, balance_seconds, stop_time_ts}
  POST /api/frp_session/stop       -> {code, used_seconds, balance_seconds}
  GET  /api/frp_session/status     -> {code, has_session, session_id, balance_seconds, ...}

用法:
    api = SessionAPI()
    api.start(token, on_done)          # on_done(result: dict)
    api.heartbeat(token, session_id, on_done)
    api.stop(token, session_id, on_done)
    api.status(token, on_done)
"""
import json

from PyQt6.QtCore import QUrl, QByteArray
from PyQt6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                             QNetworkReply)

BASE_URL = "https://sorielflow.com"


class SessionAPI:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.manager = QNetworkAccessManager()

    # ---------------- 通用请求 ----------------

    def _post_json(self, path, token, payload, callback):
        """POST JSON body + Bearer 鉴权"""
        req = QNetworkRequest(QUrl(self.base_url + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        req.setRawHeader(b"Authorization", f"Bearer {token}".encode())

        data = QByteArray(json.dumps(payload).encode())
        reply = self.manager.post(req, data)
        reply.finished.connect(lambda: self._handle(reply, callback))

    def _get(self, path, token, callback):
        """GET + Bearer 鉴权"""
        req = QNetworkRequest(QUrl(self.base_url + path))
        req.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        req.setRawHeader(b"Accept", b"application/json")

        reply = self.manager.get(req)
        reply.finished.connect(lambda: self._handle(reply, callback))

    def _handle(self, reply, callback):
        """统一解析：始终回调 dict"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                callback({"code": 1, "message": f"网络错误: {reply.errorString()}"})
                return

            raw = bytes(reply.readAll().data()).decode("utf-8")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                callback({"code": 1, "message": f"响应非 JSON: {raw[:200]}"})
                return

            # Django 侧错误语义统一
            if isinstance(result, dict) and "code" in result:
                callback(result)
            else:
                callback({"code": 1, "message": "未知响应格式", "raw": raw})
        finally:
            reply.deleteLater()

    # ---------------- 会话接口 ------

    def start(self, token, callback):
        """开启会话（门禁：成功后才能启动 frpc）"""
        self._post_json("/api/frp_session/start/", token, {}, callback)

    def heartbeat(self, token, session_id, callback):
        """心跳续期"""
        self._post_json("/api/frp_session/heartbeat/", token,
                        {"session_id": session_id}, callback)

    def stop(self, token, session_id, callback):
        """主动断开并结算"""
        self._post_json("/api/frp_session/stop/", token,
                        {"session_id": session_id}, callback)

    def status(self, token, callback):
        """查询当前会话与余额（启动时同步用）"""
        self._get("/api/frp_session/status/", token, callback)

    # ---------------- 远程端口租赁 -----

    def allocate_port(self, token, callback):
        """分配远程端口（点"连接"时调用；需已开启时长）"""
        self._post_json("/api/frp_port/allocate/", token, {}, callback)

    def release_port(self, token, callback):
        """释放远程端口（断开连接时调用）"""
        self._post_json("/api/frp_port/release/", token, {}, callback)

    def current_port(self, token, callback):
        """查询当前端口（启动/恢复时用）"""
        self._get("/api/frp_port/", token, callback)

    def user_profile(self, token, callback):
        """获取当前用户资料(含头像相对路径)"""
        self._get("/api/user_profile/", token, callback)



