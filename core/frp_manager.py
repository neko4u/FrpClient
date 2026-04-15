import subprocess
import psutil
import os
import threading

class FRPManager:
    def __init__(self, frpc_path, config_path):
        self.conn_status = "stopped"  
        # stopped / connecting / connected / failed
        self.frpc_path = frpc_path
        self.config_path = config_path
        self.process = None
        self.conn_status = "stopped"
        self.logs = []
        self._running = False
        self.conn_status = "stopped"

    def start(self):
        if self.process and self.process.poll() is None:
            return "已运行"

        if not os.path.exists(self.frpc_path):
            return "frpc.exe 不存在"
        self.logs = []
        self._running = True
        self.conn_status = "connecting"

        try:
            self.process = subprocess.Popen(
                [self.frpc_path, "-c", self.config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )
            self.current_pid = self.process.pid
        except Exception as e:
            return f"启动失败: {e}"
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._read_error, daemon=True).start()

        return "启动成功"

    def stop(self):
        try:
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()
        except:
            pass
        if self.process:
            self._running = False

            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except Exception:
                self.process.kill()
            self.process = None
            self.conn_status = "stopped"
            
            return "已停止"
        return "未运行"

    def status(self):
        if self.process and self.process.poll() is None:
            p = psutil.Process(self.process.pid)
            return f"运行中 PID={p.pid} CPU={p.cpu_percent(interval=0.1)}%"
        return "未运行"
    
    def _read_output(self):
        try:
            proc = self.process
            if proc is None:
                return
            for line in iter(proc.stdout.readline, ''):
                if proc is None or proc.pid != self.current_pid:
                    break
                if not self._running:
                    break
                line = line.strip()
                if line:
                    self.logs.append(line)
                    if not self._running:
                        break
                    low = line.lower()
                    if "login to server success" in low or "start proxy success" in low:
                        self.conn_status = "connected"

                    elif "connection refused" in low or "login failed" in low:
                        self.conn_status = "failed"

                    # 日志限制
                    if len(self.logs) > 500:
                        self.logs = self.logs[-500:]
        except Exception as e:
            self.logs.append(f"[READ_ERROR] {e}")


    def _read_error(self):
        try:
            proc = self.process
            if proc is None:
                return

            for line in iter(proc.stderr.readline, ''):
                if proc is None or proc.pid != self.current_pid:
                    break
                if not self._running:
                    break
                line = line.strip()
                if line:
                    self.logs.append("[ERROR] " + line)
                    if not self._running:
                        break
                    low = line.lower()
                    if "connection refused" in low or "failed" in low:
                        self.conn_status = "failed"
                    if len(self.logs) > 500:
                        self.logs = self.logs[-500:]
        except Exception as e:
            self.logs.append(f"[ERR_READ_FAIL] {e}")