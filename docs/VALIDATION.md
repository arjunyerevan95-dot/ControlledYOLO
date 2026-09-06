# Validation and host status

## 2.0.2

The tray and repeated chime are working on the user’s Windows PC, with three UE5 worker chats selected. The six ControlledYOLO hooks were reviewed and trusted through the normal Codex interface. Unrelated hook entries were preserved.

Native events have not reached ControlledYOLO from the active desktop worker, including after reloading hooks. Trust and discovery are verified; native automatic approval is not. Version 2.0.2 therefore adds a Windows accessibility fallback for recognizable terminal cards. A direct InvokePattern test approved the initial waiting terminal request and the worker progressed, without changing the foreground window. The installed 2.0.2 monitor then approved the next waiting terminal request automatically. Codex logged ExecApproval/Approved at 2026-09-06 08:41:41 UTC, and the worker continued. The utility recorded the matching UI approval. Two stale reminders from the earlier monitor were acknowledged after confirming both requests had been approved.

Local verification: 33 core/integration tests passed. Windows CI passed all 36 tests and built and checked the standalone executable and package. On the user’s PC, 35 tests passed; the test harness’s script invocation was blocked by its default execution policy, so the new monitor was parsed directly through the PowerShell parser with no syntax errors. No machine execution policy was changed. Added cases cover fresh policy in a separate process, selection and mode, pause, expiry, dead/future heartbeat, renamed/missing/duplicate titles, malformed index input, command mismatch, and exact reminder correlation. UI recognition itself is version-sensitive and requires live verification.

The fallback contains no focus, keystroke, mouse, or chat-switching calls. End-to-end focus retention is not yet verified: Unreal was brought forward before starting the monitor, but ChatGPT was in front at a later observation. That observation does not establish which action caused the focus change. Unreal was restored afterward. Do not claim a no-focus-stealing guarantee from the successful approval alone. It requires an exposed chat/card accessibility tree. Minimized windows and hidden chats are not covered reliably. Native delivery, phone delivery, and simultaneous hidden-chat coverage remain unverified. Phone push is not configured on this PC.

## Installation correction retained from 2.0.1

Microsoft Store/MSIX redirects LocalAppData for packaged processes. App and state live directly under the user profile so normal Windows Startup and packaged Codex hooks share files. The installer preserves selected chats and existing hook trust because hook command paths stay unchanged. The original utility archive remains unchanged.

Windows CI: https://github.com/arjunyerevan95-dot/ControlledYOLO/actions/runs/34022476067
