import subprocess
import psutil
import os

class FRPManager:
    def __init__(self, frpc_path, config_path):
        self.frpc_path = frpc_path
        self.config_path = config_path
        self.process = None

    def start(self):
        if self.process and self.process.poll() is None:
            return "已运行"

        if not os.path.exists(self.frpc_path):
            return "frpc.exe 不存在"

        self.process = subprocess.Popen(
            [self.frpc_path, "-c", self.config_path],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "启动成功"

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None
            return "已停止"
        return "未运行"

    def status(self):
        if self.process and self.process.poll() is None:
            p = psutil.Process(self.process.pid)
            return f"运行中 PID={p.pid} CPU={p.cpu_percent()}%"
        return "未运行"