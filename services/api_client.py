import json
from PyQt6.QtCore import QUrl, QByteArray
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest

LOGIN_URL = "http://175.178.158.171/token_login/"

class ApiClient:
    def __init__(self):
        self.manager = QNetworkAccessManager()

    def login(self, username, password, callback):
        data = QByteArray()
        data.append(f"user={username}&pwd={password}".encode())

        req = QNetworkRequest(QUrl(LOGIN_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/x-www-form-urlencoded")

        reply = self.manager.post(req, data)
        reply.finished.connect(lambda: self.handle(reply, callback))

    def handle(self, reply, callback):
        data = reply.readAll().data()
        try:
            callback(json.loads(data.decode()))
        except:
            callback({"code": 1, "message": "解析失败"})