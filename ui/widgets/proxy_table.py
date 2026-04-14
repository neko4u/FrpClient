from PyQt6.QtWidgets import *

class ProxyTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels(
            ["名称", "类型", "本地端口", "远程端口", "操作"]
        )

    def load(self, proxies):
        self.setRowCount(len(proxies))

        for row, p in enumerate(proxies):
            self.setItem(row, 0, QTableWidgetItem(p["name"]))
            self.setItem(row, 1, QTableWidgetItem(p["type"]))
            self.setItem(row, 2, QTableWidgetItem(str(p["localPort"])))
            self.setItem(row, 3, QTableWidgetItem(str(p["remotePort"])))

            btn = QPushButton("删除")
            btn.clicked.connect(lambda _, r=row: self.removeRow(r))
            self.setCellWidget(row, 4, btn)

    def get_data(self):
        proxies = []
        for row in range(self.rowCount()):
            proxies.append({
                "name": self.item(row, 0).text(),
                "type": self.item(row, 1).text(),
                "localIP": "127.0.0.1",
                "localPort": int(self.item(row, 2).text()),
                "remotePort": int(self.item(row, 3).text())
            })
        return proxies