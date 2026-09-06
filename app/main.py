"""ControlledYOLO 2 entry point: tray app or a short-lived Codex hook process."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import traceback
import uuid

from core import Store, VERSION


def codex_home():
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


class Instance:
    def __init__(self, path):
        key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
        if os.name == "nt":
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            self.kernel.CreateMutexW.restype = ctypes.c_void_p
            self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            self.handle = self.kernel.CreateMutexW(None, False, "Local\\ControlledYOLO-" + key)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self.acquired = ctypes.get_last_error() != 183
        else:
            import fcntl
            self.file = (path / "instance.lock").open("w")
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
            except BlockingIOError:
                self.acquired = False

    def close(self):
        if os.name == "nt":
            self.kernel.CloseHandle(self.handle)
        else:
            self.file.close()


def hook_entry():
    # Never emit an allow response on malformed input, an error, or a missing live tray.
    try:
        data = sys.stdin.buffer.read(2_000_001)
        if len(data) > 2_000_000:
            return 0
        event = json.loads(data.decode("utf-8-sig"))
        result = Store().handle_hook(event)
        if result:
            print(json.dumps(result), flush=True)
    except Exception:
        # An empty successful response preserves Codex's ordinary approval flow.
        if sys.stderr:
            sys.stderr.write("ControlledYOLO could not process this event; normal approval continues.\n")
    return 0


def play_chime(root=None):
    if os.name == "nt":
        import winsound
        sound = Path(__file__).with_name("chime.wav")
        winsound.PlaySound(str(sound), winsound.SND_FILENAME | winsound.SND_ASYNC)
    elif root:
        root.bell()


def select_title(store, title, mode):
    matches = [c for c in store.chats() if c["title"].casefold() == title.casefold()]
    if len(matches) == 1:
        store.configure_chat(matches[0]["id"], True, mode)
        store.set("selection_notice", "Selected " + title)
        return True
    store.set("selection_notice", "Choose the chat manually: " + title + (" has duplicate titles." if matches else " has not been discovered yet."))
    return False


class App:
    def __init__(self, store, minimized=False, demo=False):
        import tkinter as tk
        from tkinter import ttk, messagebox, simpledialog
        from tray import Tray
        from monitor import VisibleMonitor
        self.tk, self.ttk = tk, ttk
        self.messagebox, self.simpledialog = messagebox, simpledialog
        self.store, self.demo = store, demo
        self.owner = uuid.uuid4().hex
        self.events = queue.Queue()
        self.root = tk.Tk()
        self.root.title("ControlledYOLO" + (" — DEMO" if demo else ""))
        self.root.geometry("1080x720")
        self.root.minsize(900, 620)
        self.root.configure(bg="#f3f5f8")
        self.last_sound = 0
        self.last_attention = set()
        self.last_show = 0
        self.started_at = time.time()
        self.closing = False
        self.push_busy = False
        self.worker_stop = threading.Event()
        self.monitor = VisibleMonitor(store)
        self.signature = None
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f8")
        style.configure("TLabel", background="#f3f5f8", foreground="#243349", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
        style.configure("TCheckbutton", background="#f3f5f8", font=("Segoe UI", 10))
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=34, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", "#d9e7ff")], foreground=[("selected", "#123c73")])
        style.configure("TNotebook.Tab", padding=(18, 10), font=("Segoe UI", 10))
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="ControlledYOLO", font=("Segoe UI", 23, "bold")).pack(side="left")
        self.pause_button = ttk.Button(header, command=self.toggle_pause)
        self.pause_button.pack(side="right")
        ttk.Button(header, text="Test chime", command=lambda: play_chime(self.root)).pack(side="right", padx=8)
        self.summary = tk.StringVar(value="Starting…")
        ttk.Label(outer, textvariable=self.summary, font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 16))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.chats_page = ttk.Frame(self.tabs, padding=16)
        self.attention_page = ttk.Frame(self.tabs, padding=16)
        self.settings_page = ttk.Frame(self.tabs, padding=16)
        for page, name in ((self.chats_page, "Chats"), (self.attention_page, "Needs attention"), (self.settings_page, "Settings")):
            self.tabs.add(page, text=name)
        self.build_chats()
        self.build_attention()
        self.build_settings()
        self.health = tk.StringVar()
        ttk.Label(outer, textvariable=self.health, wraplength=1000, font=("Segoe UI", 9)).pack(anchor="w", pady=(14, 0))
        self.tray = Tray(self.events.put)
        self.tray_ok = self.tray.start() if not demo else False
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.store.heartbeat(self.owner)
        self.store.prune()
        if not demo:
            threading.Thread(target=self.worker, daemon=True).start()
            threading.Thread(target=self.push_worker, daemon=True).start()
        if minimized and self.tray_ok:
            self.root.withdraw()
        self.root.after(200, self.tick)

    def tree(self, parent, columns, widths):
        container = self.ttk.Frame(parent)
        container.pack(fill="both", expand=True, pady=(10, 12))
        tree = self.ttk.Treeview(container, columns=columns, show="headings", selectmode="extended")
        scrollbar = self.ttk.Scrollbar(container, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, minwidth=55, stretch=column in {"Chat", "Request"})
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def build_chats(self):
        bar = self.ttk.Frame(self.chats_page)
        bar.pack(fill="x")
        self.search = self.tk.StringVar()
        entry = self.ttk.Entry(bar, textvariable=self.search, width=34)
        entry.pack(side="left")
        self.search.trace_add("write", lambda *_: self.refresh_chats(force=True))
        self.ttk.Label(bar, text="Filter by title or chat ID").pack(side="left", padx=10)
        self.ttk.Button(bar, text="Refresh chats", command=self.import_chats).pack(side="right")
        self.ttk.Button(bar, text="Add by ID", command=self.add_chat).pack(side="right", padx=6)
        self.chat_tree = self.tree(self.chats_page, ["Watch", "Chat", "Mode", "Chat ID", "Native events", "Expiry"], [65, 300, 125, 160, 115, 90])
        self.chat_tree.bind("<Double-1>", self.toggle_chat)
        controls = self.ttk.Frame(self.chats_page)
        controls.pack(fill="x")
        self.ttk.Button(controls, text="Notify only", command=lambda: self.apply_mode("notify")).pack(side="left")
        self.ttk.Button(controls, text="Auto local approvals", command=lambda: self.apply_mode("auto_local")).pack(side="left", padx=6)
        self.ttk.Button(controls, text="Stop watching", command=self.unselect).pack(side="left")
        self.ttk.Label(controls, text="For:").pack(side="left", padx=(18, 5))
        self.expiry = self.ttk.Combobox(controls, state="readonly", width=15, values=["Until I stop it", "30 minutes", "1 hour", "2 hours", "8 hours"])
        self.expiry.current(0)
        self.expiry.pack(side="left")
        self.ttk.Label(self.chats_page, text="Select one or several rows, then choose a mode. Double-click a row to toggle watching.\nAuto local covers shell and file-edit permission requests exposed by Codex hooks, including that chat’s subagents.", wraplength=970).pack(anchor="w", pady=(14, 0))
        self.selection_notice = self.tk.StringVar(value=self.store.get("selection_notice", ""))
        self.ttk.Label(self.chats_page, textvariable=self.selection_notice, foreground="#875c13", wraplength=960).pack(anchor="w", pady=(8, 0))

    def build_attention(self):
        self.ttk.Label(self.attention_page, text="Reminders continue until you acknowledge them or a matching native event clears them.").pack(anchor="w")
        self.request_tree = self.tree(self.attention_page, ["Chat", "Request", "Source", "State", "Since"], [300, 220, 95, 170, 85])
        controls = self.ttk.Frame(self.attention_page)
        controls.pack(fill="x")
        self.ttk.Button(controls, text="Acknowledge selected", command=self.acknowledge).pack(side="left")
        self.ttk.Button(controls, text="Acknowledge all", command=self.acknowledge_all).pack(side="left", padx=8)
        self.ttk.Label(self.attention_page, text="Acknowledging silences reminders; it does not approve a request. Visible-card alerts stay listed when a window is hidden.\n“Hook allowed” records a hook decision. It does not claim Codex executed the action.", wraplength=950).pack(anchor="w", pady=(14, 0))

    def build_settings(self):
        page = self.settings_page
        self.ttk.Label(page, text="Codex connection", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.native_text = self.tk.StringVar(value="Awaiting native events")
        self.ttk.Label(page, textvariable=self.native_text).grid(row=1, column=0, columnspan=3, sticky="w")
        self.ttk.Button(page, text="Install / repair hooks", command=self.install_hooks, state="disabled" if self.demo else "normal").grid(row=2, column=0, sticky="w", pady=8)
        self.ttk.Label(page, text="After setup, review the new hooks using /hooks in Codex. Existing hooks and approval settings are preserved.", wraplength=690).grid(row=2, column=1, columnspan=2, sticky="w", padx=10)
        self.visible = self.tk.BooleanVar(value=self.store.get("visible_monitor", True))
        self.ttk.Checkbutton(page, text="Also watch visible desktop permission cards", variable=self.visible).grid(row=3, column=0, columnspan=3, sticky="w", pady=5)
        self.ttk.Label(page, text="Sound", font=("Segoe UI", 13, "bold")).grid(row=4, column=0, sticky="w", pady=(16, 8))
        self.ttk.Label(page, text="Chime every (seconds)").grid(row=5, column=0, sticky="w")
        self.chime_seconds = self.tk.StringVar(value=str(self.store.get("chime_seconds", 10)))
        self.ttk.Spinbox(page, from_=3, to=300, width=8, textvariable=self.chime_seconds).grid(row=5, column=1, sticky="w", padx=10)
        self.ttk.Label(page, text="Phone alerts · optional ntfy", font=("Segoe UI", 13, "bold")).grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 8))
        self.ttk.Label(page, text="Topic URL").grid(row=7, column=0, sticky="w")
        self.ntfy_url = self.tk.StringVar(value=self.store.get("ntfy_url", ""))
        self.ttk.Entry(page, textvariable=self.ntfy_url, width=58).grid(row=7, column=1, columnspan=2, sticky="ew", padx=10)
        self.ttk.Label(page, text="Access token (if required)").grid(row=8, column=0, sticky="w", pady=6)
        self.ntfy_token = self.tk.StringVar(value=self.store.get("ntfy_token", ""))
        self.ttk.Entry(page, textvariable=self.ntfy_token, show="•", width=58).grid(row=8, column=1, columnspan=2, sticky="ew", padx=10)
        self.ttk.Label(page, text="Subscribe to the same topic in the ntfy phone app. Use a private topic. Alerts contain chat titles, never tool arguments.\nDelivery follows your phone’s notification settings. Credentials stay in this Windows user’s local app data.", wraplength=920).grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 12))
        buttons = self.ttk.Frame(page)
        buttons.grid(row=10, column=0, columnspan=3, sticky="w")
        self.ttk.Button(buttons, text="Save settings", command=self.save_settings).pack(side="left")
        self.ttk.Button(buttons, text="Test phone alert", command=self.test_push).pack(side="left", padx=8)
        self.ttk.Button(buttons, text="Open app data", command=self.open_data).pack(side="left")
        self.ttk.Button(buttons, text="Quit app", command=self.quit).pack(side="left", padx=8)
        page.columnconfigure(1, weight=1)

    def report_error(self, error):
        self.messagebox.showerror("ControlledYOLO", str(error), parent=self.root)

    def import_chats(self):
        try:
            count = self.store.import_index(codex_home() / "session_index.jsonl")
            self.selection_notice.set(f"Refreshed {count} chat labels. Native hook events also discover chats as you use them.")
            self.refresh_chats(True)
        except Exception as error:
            self.report_error(error)

    def add_chat(self):
        session = self.simpledialog.askstring("Add chat", "Paste the Codex chat ID:", parent=self.root)
        if not session:
            return
        title = self.simpledialog.askstring("Chat label", "Name to show in this list:", parent=self.root)
        try:
            self.store.upsert_chat(session.strip(), title)
            self.refresh_chats(True)
        except Exception as error:
            self.report_error(error)

    def apply_mode(self, mode):
        minutes = [0, 30, 60, 120, 480][self.expiry.current()]
        for session in self.chat_tree.selection():
            self.store.configure_chat(session, True, mode, minutes)
        self.refresh_chats(True)

    def unselect(self):
        for session in self.chat_tree.selection():
            self.store.configure_chat(session, False)
        self.refresh_chats(True)

    def toggle_chat(self, event):
        session = self.chat_tree.identify_row(event.y)
        for chat in self.store.chats():
            if chat["id"] == session:
                remaining = max(0, (chat["expires"] - time.time()) / 60) if chat["expires"] else 0
                self.store.configure_chat(session, not chat["selected"], chat["mode"], remaining)
                break
        self.refresh_chats(True)

    def refresh_chats(self, force=False):
        if not hasattr(self, "chat_tree"):
            return
        chats = self.store.chats()
        query = self.search.get().casefold()
        visible = [c for c in chats if query in (c["title"] + c["id"]).casefold()]
        signature = json.dumps(visible) + str(int(time.time() / 30))
        if force or signature != self.signature:
            selected = self.chat_tree.selection()
            self.chat_tree.delete(*self.chat_tree.get_children())
            for chat in visible:
                expiry = "None" if not chat["expires"] else ("Expired" if chat["expires"] <= time.time() else time.strftime("%H:%M", time.localtime(chat["expires"])))
                self.chat_tree.insert("", "end", iid=chat["id"], values=("●" if chat["selected"] else "○", chat["title"], "Auto local" if chat["mode"] == "auto_local" else "Notify", chat["id"], "Observed" if chat["native_seen"] else "Not yet", expiry))
            self.chat_tree.selection_set([s for s in selected if self.chat_tree.exists(s)])
            self.signature = signature

    def acknowledge(self):
        self.store.acknowledge(self.request_tree.selection())

    def acknowledge_all(self):
        self.store.acknowledge([r["id"] for r in self.store.requests(True)])

    def toggle_pause(self):
        self.store.set("paused", not self.store.get("paused", False))

    def save_settings(self):
        from notifications import validate_url
        try:
            seconds = int(self.chime_seconds.get())
            if not 3 <= seconds <= 300:
                raise ValueError("Choose a chime interval from 3 to 300 seconds.")
            url = validate_url(self.ntfy_url.get())
            for key, value in {"chime_seconds": seconds, "ntfy_url": url, "ntfy_token": self.ntfy_token.get().strip(), "visible_monitor": self.visible.get()}.items():
                self.store.set(key, value)
            self.selection_notice.set("Settings saved.")
            return True
        except Exception as error:
            self.report_error(error)
            return False

    def install_hooks(self):
        from hooks import register
        try:
            register(codex_home())
            self.messagebox.showinfo("Hooks installed", "Open /hooks in Codex and review the ControlledYOLO definitions once. The app will show 'Native events observed' after your runtime calls them.", parent=self.root)
        except Exception as error:
            self.report_error(error)

    def test_push(self):
        if not self.save_settings():
            return
        if not self.store.get("ntfy_url"):
            self.report_error("Enter your ntfy topic URL first.")
            return
        def run():
            from notifications import send
            try:
                send(self.store.get("ntfy_url"), self.store.get("ntfy_token"), "ControlledYOLO test")
                self.events.put(("info", "The notification server accepted the test. Check delivery on your phone."))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=run, daemon=True).start()

    def open_data(self):
        if os.name == "nt":
            os.startfile(self.store.home)

    def worker(self):
        while not self.worker_stop.wait(1):
            try:
                self.monitor.tick()
            except Exception as error:
                self.events.put(("health", "Background monitor: " + str(error)[:160]))
        self.monitor.stop()

    def push_worker(self):
        while not self.worker_stop.wait(1):
            try:
                if self.store.get("paused", False):
                    continue
                settings = self.store.settings()
                if not settings.get("ntfy_url"):
                    continue
                from notifications import send
                for request in self.store.attention():
                    if self.worker_stop.is_set():
                        return
                    now = time.time()
                    if now - request["push_at"] < settings["push_seconds"] or now - request["push_attempt"] < 30:
                        continue
                    # Re-check after slow network work to avoid sending newly acknowledged reminders.
                    if self.store.get("paused", False) or request["id"] not in {r["id"] for r in self.store.attention()}:
                        continue
                    try:
                        send(settings["ntfy_url"], settings["ntfy_token"], request["title"])
                        self.store.update_push(request["id"], True)
                    except Exception as error:
                        self.store.update_push(request["id"], False, str(error))
            except Exception as error:
                self.events.put(("health", "Phone alerts: " + str(error)[:160]))

    def tick(self):
        if self.closing:
            return
        try:
            self.store.heartbeat(self.owner)
            if self.store.get("quit_requested", 0) >= self.started_at:
                self.quit()
                return
            while not self.events.empty():
                event = self.events.get_nowait()
                if isinstance(event, tuple):
                    kind, text = event
                    if kind == "error":
                        self.report_error(text)
                    elif kind == "info":
                        self.messagebox.showinfo("ControlledYOLO", text, parent=self.root)
                    else:
                        self.monitor.status = text
                elif event == "show":
                    self.show()
                elif event == "pause":
                    self.toggle_pause()
                elif event == "chime":
                    play_chime(self.root)
                elif event == "quit":
                    self.quit()
                    return
            requested = self.store.get("show_requested", 0)
            if requested > self.last_show:
                self.last_show = requested
                self.show()
            paused = self.store.get("paused", False)
            attention = self.store.attention()
            ids = {r["id"] for r in attention}
            if ids and not paused and (ids - self.last_attention or time.monotonic() - self.last_sound >= self.store.get("chime_seconds", 10)):
                play_chime(self.root)
                self.last_sound = time.monotonic()
            self.last_attention = ids
            watched = sum(c["selected"] and (not c["expires"] or c["expires"] > time.time()) for c in self.store.chats())
            self.pause_button.configure(text="Resume" if paused else "Pause all")
            state = "Paused" if paused else f"Watching {watched} chat{'s' if watched != 1 else ''}"
            self.summary.set(f"{state}  ·  {len(attention)} need attention" + ("  ·  DEMO DATA" if self.demo else ""))
            self.tray.state("paused" if paused else "attention" if attention else "running", self.summary.get())
            self.refresh_chats()
            self.tabs.tab(self.attention_page, text=f"Needs attention ({len(attention)})")
            self.refresh_requests()
            native_at = self.store.get("native_event_at", 0)
            native = "Native events observed · last " + time.strftime("%H:%M:%S", time.localtime(native_at)) if native_at else "Native connection: awaiting first event"
            self.native_text.set(native)
            self.health.set(f"{native}  |  Visible cards: {self.monitor.status}  |  v{VERSION}" + ("  |  Tray unavailable; window stays open" if not self.tray_ok else ""))
        except Exception as error:
            self.health.set("App needs attention: " + str(error)[:180])
        self.root.after(1000, self.tick)

    def refresh_requests(self):
        rows = self.store.requests()[:200]
        selected = self.request_tree.selection()
        self.request_tree.delete(*self.request_tree.get_children())
        for row in rows:
            status = {"pending": "Acknowledged" if row["acknowledged"] else "Needs attention", "allowed_by_hook": "Hook allowed", "tool_finished": "Tool finished", "ended": "Turn/session ended", "interrupted": "Interrupted"}.get(row["status"], row["status"])
            if row["push_error"] and row["status"] == "pending" and not row["acknowledged"]:
                status += " · push retry"
            self.request_tree.insert("", "end", iid=row["id"], values=(row["title"], row["tool"], "Native" if row["source"] == "hook" else "Visible UI", status, time.strftime("%H:%M:%S", time.localtime(row["created"]))))
        self.request_tree.selection_set([s for s in selected if self.request_tree.exists(s)])

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        if self.tray_ok:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.store.stop_heartbeat(self.owner)
        self.worker_stop.set()
        self.monitor.stop(final=True)
        self.tray.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--install-hooks", action="store_true")
    parser.add_argument("--remove-hooks", action="store_true")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--select-title")
    parser.add_argument("--configure-title")
    parser.add_argument("--request-exit", action="store_true")
    parser.add_argument("--mode", choices=["notify", "auto_local"], default="notify")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    if args.hook:
        return hook_entry()
    if args.request_exit:
        store = Store()
        store.set("quit_requested", time.time())
        for _ in range(40):
            heartbeat = store.get("heartbeat", {})
            if not heartbeat or time.time() - heartbeat.get("at", 0) > 12:
                return 0
            time.sleep(.1)
        return 1
    if args.install_hooks or args.remove_hooks:
        from hooks import register
        register(codex_home(), remove=args.remove_hooks)
        print("Hook configuration updated. Review it using /hooks in Codex." if args.install_hooks else "ControlledYOLO hooks removed.")
        return 0
    temporary = tempfile.TemporaryDirectory(prefix="controlledyolo-demo-") if args.demo else None
    store = Store(temporary.name if temporary else None)
    if args.configure_title:
        store.import_index(codex_home() / "session_index.jsonl")
        found = select_title(store, args.configure_title, args.mode)
        print(store.get("selection_notice"))
        return 0
    if args.demo:
        for session, title, mode in [("demo-bootstrap", "Bootstrap ControlPlane Console", "auto_local"), ("demo-archviz", "Hawksnest · Unreal showroom", "notify"), ("demo-research", "Keyword research · September", "notify")]:
            store.upsert_chat(session, title, native=True)
            store.configure_chat(session, True, mode)
        store.handle_hook({"hook_event_name": "PermissionRequest", "session_id": "demo-archviz", "turn_id": "demo-turn", "tool_name": "Bash", "tool_input": {"command": "demo only"}})
    else:
        store.import_index(codex_home() / "session_index.jsonl")
    if args.select_title:
        select_title(store, args.select_title, args.mode)
    instance = Instance(store.home)
    if not instance.acquired:
        store.set("show_requested", time.time())
        instance.close()
        return 0
    try:
        App(store, args.minimized, args.demo).run()
    finally:
        instance.close()
        store.close()
        if temporary:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Show startup failures even when launched by a hidden Windows shortcut.
        details = traceback.format_exc()
        if sys.stderr:
            sys.stderr.write(details)
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, details[-1800:], "ControlledYOLO could not start", 0x10)
        raise SystemExit(1)
