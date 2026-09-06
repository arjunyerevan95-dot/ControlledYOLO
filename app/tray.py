"""Windows notification-area icon implemented with the standard-library ctypes API."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import threading


class Tray:
    def __init__(self, callback):
        self.callback = callback
        self.hwnd = None
        self.error = ""
        self.ready = threading.Event()
        self.current = "paused"
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if os.name != "nt":
            self.error = "Tray is available on Windows."
            return False
        self.thread.start()
        self.ready.wait(3)
        return bool(self.hwnd)

    def _run(self):
        try:
            self._windows_loop()
        except Exception as error:
            self.error = str(error)
            self.ready.set()

    def _windows_loop(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("proc", WNDPROC), ("clsExtra", ctypes.c_int),
                        ("wndExtra", ctypes.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                        ("cursor", w.HANDLE), ("background", w.HBRUSH), ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]

        class GUID(ctypes.Structure):
            _fields_ = [("data1", w.DWORD), ("data2", w.WORD), ("data3", w.WORD), ("data4", ctypes.c_ubyte * 8)]

        class NID(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                        ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                        ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                        ("uTimeoutOrVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                        ("guidItem", GUID), ("hBalloonIcon", w.HICON)]

        self.user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user.DefWindowProcW.restype = LRESULT
        self.user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        self.user.CreateWindowExW.restype = w.HWND
        self.user.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        self.user.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
        self.user.LoadImageW.restype = w.HANDLE
        self.user.DestroyIcon.argtypes = [w.HICON]
        self.user.CreatePopupMenu.restype = w.HMENU
        self.user.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
        self.user.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPCVOID]
        self.user.DestroyMenu.argtypes = [w.HMENU]
        self.user.SetForegroundWindow.argtypes = [w.HWND]
        self.user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user.DestroyWindow.argtypes = [w.HWND]
        self.user.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        self.user.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
        self.user.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
        self.user.DispatchMessageW.restype = LRESULT
        self.shell.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NID)]
        self.shell.Shell_NotifyIconW.restype = w.BOOL
        kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        kernel.GetModuleHandleW.restype = w.HMODULE
        self.icons = {}
        for state in ("running", "attention", "paused"):
            path = str(Path(__file__).with_name("icons") / (state + ".ico"))
            self.icons[state] = self.user.LoadImageW(None, path, 1, 32, 32, 0x10)
            if not self.icons[state]:
                raise ctypes.WinError(ctypes.get_last_error())
        restart = self.user.RegisterWindowMessageW("TaskbarCreated")

        def window_proc(hwnd, message, wp, lp):
            if message == restart and hasattr(self, "nid"):
                self.shell.Shell_NotifyIconW(0, ctypes.byref(self.nid))
            elif message == 0x8001:
                if lp in (0x0202, 0x0203):
                    self.callback("show")
                elif lp == 0x0205:
                    menu = self.user.CreatePopupMenu()
                    for number, label in ((1, "Open ControlledYOLO"), (2, "Pause / resume"), (3, "Test chime"), (4, "Quit")):
                        self.user.AppendMenuW(menu, 0, number, label)
                    point = w.POINT()
                    self.user.GetCursorPos(ctypes.byref(point))
                    self.user.SetForegroundWindow(hwnd)
                    command = self.user.TrackPopupMenu(menu, 0x0100 | 0x0002, point.x, point.y, 0, hwnd, None)
                    self.user.DestroyMenu(menu)
                    action = {1: "show", 2: "pause", 3: "chime", 4: "quit"}.get(command)
                    if action:
                        self.callback(action)
            elif message == 0x0010:
                self.shell.Shell_NotifyIconW(2, ctypes.byref(self.nid))
                self.user.DestroyWindow(hwnd)
            elif message == 0x0002:
                self.user.PostQuitMessage(0)
            return self.user.DefWindowProcW(hwnd, message, wp, lp)

        self.proc = WNDPROC(window_proc)
        instance = kernel.GetModuleHandleW(None)
        name = "ControlledYOLOTray" + str(os.getpid())
        wc = WNDCLASS(0, self.proc, 0, 0, instance, None, None, None, None, name)
        if not self.user.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        hwnd = self.user.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.nid = NID()
        self.nid.cbSize = ctypes.sizeof(NID)
        self.nid.hWnd = hwnd
        self.nid.uID = 1
        self.nid.uFlags = 1 | 2 | 4
        self.nid.uCallbackMessage = 0x8001
        self.nid.hIcon = self.icons[self.current]
        self.nid.szTip = "ControlledYOLO"
        if not self.shell.Shell_NotifyIconW(0, ctypes.byref(self.nid)):
            self.user.DestroyWindow(hwnd)
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        self.ready.set()
        msg = w.MSG()
        while self.user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user.TranslateMessage(ctypes.byref(msg))
            self.user.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None
        for icon in self.icons.values():
            self.user.DestroyIcon(icon)

    def state(self, state, text):
        self.current = state
        if self.hwnd:
            self.nid.hIcon = self.icons[state]
            self.nid.szTip = text[:127]
            self.shell.Shell_NotifyIconW(1, ctypes.byref(self.nid))

    def close(self):
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, 0x0010, 0, 0)

