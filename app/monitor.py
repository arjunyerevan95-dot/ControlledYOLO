import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


class VisibleMonitor:
    def __init__(self, store):
        self.store = store
        self.process = None
        self.messages = queue.Queue()
        self.last_message = 0
        self.last_start = 0
        self.status = "Waiting"
        self.config = store.home / "visible-chats.json"
        self.signature = None
        self.closed = False
        self.lock = threading.RLock()

    def _reader(self, process):
        try:
            for line in process.stdout:
                self.messages.put((process.pid, json.loads(line)))
        except (ValueError, OSError):
            self.messages.put((process.pid, {"error": "Visible monitor output was interrupted."}))

    def tick(self):
        with self.lock:
            if not self.closed:
                self._tick()

    def _tick(self):
        enabled = self.store.get("visible_monitor", True)
        if os.name != "nt" or not enabled:
            self.stop()
            self.status = "Windows only" if os.name != "nt" else "Off"
            return
        chats = [{"id": c["id"], "title": c["title"]} for c in self.store.chats() if c["selected"]]
        runner = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).with_name("main.py"))]
        config = {"chats": chats, "runner": runner + ["--check-visible"]}
        signature = json.dumps(config)
        if signature != self.signature:
            temporary = self.config.with_suffix(".tmp")
            temporary.write_text(signature, encoding="utf-8")
            temporary.replace(self.config)
            self.signature = signature
        now = time.monotonic()
        while not self.messages.empty():
            pid, message = self.messages.get_nowait()
            if self.process and pid == self.process.pid:
                self.last_message = now
                self.status = message.get("error") or "Watching visible chats"
                if not message.get("error"):
                    self.store.visible_snapshot(message.get("cards", []))
                    for card in message.get("approved", []):
                        self.store.record_visible_approval(card)
        if self.process and (self.process.poll() is not None or now - self.last_message > 20):
            self.stop()
            self.status = "Restarting monitor"
        if self.process is None and now - self.last_start > 10:
            self.last_start = self.last_message = now
            script = Path(__file__).with_name("VisibleMonitor.ps1")
            self.process = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                             "-File", str(script), "-ConfigPath", str(self.config)],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
            threading.Thread(target=self._reader, args=(self.process,), daemon=True).start()

    def stop(self, final=False):
        with self.lock:
            self.closed = self.closed or final
            self._stop()

    def _stop(self):
        if self.process:
            process, self.process = self.process, None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.stdout:
                process.stdout.close()
