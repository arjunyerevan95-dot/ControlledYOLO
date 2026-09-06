# Validation and host status

The previous ControlledYOLO utility has been used successfully by Arjun. V2 preserves its published archive and introduces a separate native-hook and notification app.

This build is being tested against synthetic hook events and a temporary state database. No synthetic event is written into the user's live Codex configuration during tests. The tests verify exact session selection, duplicate titles, multiple concurrent chats, dead or paused app behavior, expiry, request correlation, and preservation of unrelated hooks.

Local verification: 25 core/integration tests passed, including 25 concurrent selected chats and four simultaneous separate hook processes. The first Windows run passed window construction and PowerShell parsing, and exposed SQLite write contention; the corrected version uses a persistent WAL connection and one transaction per event. The Windows workflow runs the full suite again, including the tray icon, before packaging a standalone app.

At build time, the Remote Desktop Commander connection for Arjuk reported offline. Therefore this session cannot certify installation, visible-card detection, audible output, phone delivery, or native-hook coverage on that PC.

Live acceptance checks after installation:

1. Review ControlledYOLO hooks in Codex and verify the app shows a real observed native event.
2. Select Bootstrap ControlPlane Console and a second chat. Leave a third chat unselected.
3. Exercise a harmless permission request in each selected chat and confirm its expected mode. The unselected chat must retain normal behavior.
4. Confirm selected chat handling while its window is hidden, for requests delivered through native hooks.
5. Pause the tray app and confirm normal approval behavior resumes; repeat after quitting it.
6. Test the repeated chime and acknowledgment, then confirm a new request starts a new alert.
7. Test the ntfy channel on the actual phone if configured. A successful HTTP send alone is not delivery proof.

V2 does not auto-answer all possible cards. Native automatic decisions are limited to supported local-tool permission requests. Visible-card detection is advisory. App-server integration for threads owned by a custom host is a possible later extension, not a feature claimed by this build.

## Microsoft Store installation correction in 2.0.1

Live installation exposed MSIX redirection of LocalAppData into the desktop app's package cache. Version 2.0.1 installs the app and its shared state directly under the Windows user profile so a normal Startup process and a packaged Codex process use the same location. A regression test verifies the default state directory ignores redirected LocalAppData.

The installed Codex 0.153.3 runtime successfully discovered all six native hooks for the three UE5 worker workspaces through its read-only hooks/list API. It reported those new definitions as untrusted, without parse errors. That runtime trust review is a remaining user step, not a successful automatic-approval test.
