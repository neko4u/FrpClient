import json
from urllib.parse import urlencode
from PyQt6.QtCore import QUrl, QByteArray
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

LOGIN_URL = "https://sorielflow.com/token_login/"


class ApiClient:
    def __init__(self):
        self.manager = QNetworkAccessManager()

    def login(self, username, password, callback):
        params = urlencode({"user": username, "pwd": password})
        data = QByteArray(params.encode())

        req = QNetworkRequest(QUrl(LOGIN_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/x-www-form-urlencoded")
        req.setRawHeader(b"Accept", b"application/json")

        reply = self.manager.post(req, data)
        reply.finished.connect(lambda: self.handle(reply, callback))

    def handle(self, reply, callback):
        """统一解析: 先解析服务端 JSON(服务器错误也会带 msg), 解析不到才算网络错误"""
        raw_bytes = reply.readAll().data()
        try:
            raw_str = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            raw_str = ""

        print(f"HTTP status: {reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)}")
        print(f"Raw response: {raw_str}")

        # 1) 能解析成 JSON -> 交给上层按 code 处理
        #    (注意: HTTP 4xx/5xx 时 reply.error() 也会非 0, 但服务端同样会带 {code, msg})
        try:
            result = json.loads(raw_str)
            if isinstance(result, dict):
                # 服务端统一用 msg, 这里兜底兼容 message
                if "msg" not in result and "message" in result:
                    result["msg"] = result["message"]
                callback(result)
                return
        except json.JSONDecodeError:
            pass

        # 2) 连 JSON 都没有 -> 才是真正的网络/解析错误
        if reply.error() != QNetworkReply.NetworkError.NoError:
            callback({"code": 1, "msg": f"网络错误: {reply.errorString()}"})
        else:
            callback({"code": 1, "msg": f"服务器返回异常: {raw_str[:200] or '(空响应)'}"})
