# Validation and host status

## 2.0.2

The tray and repeated chime are working on the user’s Windows PC, with three UE5 worker chats selected. The six ControlledYOLO hooks were reviewed and trusted through the normal Codex interface. Unrelated hook entries were preserved.

Native events have not reached ControlledYOLO from the active desktop worker, including after reloading hooks. Trust and discovery are verified; native automatic approval is not. Version 2.0.2 therefore adds a Windows accessibility fallback for recognizable terminal cards. A direct InvokePattern test approved the initial waiting terminal request and the worker progressed, without changing the foreground window. The packaged monitor still requires its live acceptance check.

Local verification: 33 core/integration tests passed; three Windows-specific tests are run on Windows. Added cases cover fresh policy in a separate process, selection and mode, pause, expiry, dead/future heartbeat, renamed/missing/duplicate titles, malformed index input, command mismatch, and exact reminder correlation. UI recognition itself is version-sensitive and requires live verification.

The fallback never focuses a window, sends keystrokes, or switches chats. It requires an exposed chat/card accessibility tree. Minimized windows and hidden chats are not covered reliably. Native delivery, phone delivery, and simultaneous hidden-chat coverage remain unverified. Phone push is not configured on this PC.

## Installation correction retained from 2.0.1

Microsoft Store/MSIX redirects LocalAppData for packaged processes. App and state live directly under the user profile so normal Windows Startup and packaged Codex hooks share files. The installer preserves selected chats and existing hook trust because hook command paths stay unchanged. The original utility archive remains unchanged.
