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
        if reply.error() != QNetworkReply.NetworkError.NoError:
            callback({"code": 1, "message": f"网络错误: {reply.errorString()}"})
            return

        raw_bytes = reply.readAll().data()
        try:
            raw_str = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            callback({"code": 1, "message": "响应编码错误，无法解析"})
            return

        print(f"HTTP status: {reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)}")
        print(f"Raw response: {raw_str}")

        try:
            result = json.loads(raw_str)
            callback(result)
        except json.JSONDecodeError:
            callback({"code": 1, "message": f"JSON 解析失败，服务器返回: {raw_str[:200]}"})