# ControlledYOLO 2

A Windows tray app for watching selected Codex chats, repeating a chime when they need attention, and using Codex's native local-tool approval hooks where available.

This is a successor to the working PowerShell utility. The original download remains unchanged at `downloads/CodexTargetedDumbMode.zip.b64`.

## Install

Download `downloads/ControlledYOLO-2.0.3.zip`, extract it, and run `Install.cmd`. The adjacent `.sha256` file contains its checksum. The copy-paste bootstrap is in `docs/BOOTSTRAP.txt`.

The installer uses your existing Python 3.10+ with tkinter. If it cannot find one, it installs Python 3.12 for your Windows user with winget. No administrator account is required. A Windows CI build also produces a package with a bundled executable that does not require Python.

The app lives under `%USERPROFILE%\ControlledYOLO\app`, with its settings under `%USERPROFILE%\ControlledYOLO\state`. Using the user-profile folder avoids Microsoft Store/MSIX app-data redirection, so desktop startup and Codex hooks share the same files. The installer adds Desktop and Startup shortcuts. `Install.ps1 -NoStartup` omits the Startup shortcut.

Setup merges ControlledYOLO's entries into the current Codex host's `hooks.json`, preserving existing entries and backing up the original file. It uses `CODEX_HOME` when that environment variable is set, otherwise your user profile's `.codex` directory. **Review the new hook definitions once using `/hooks` in Codex.** Setup does not edit hook trust records or change Codex's permission, sandbox, organization, or account settings.

Bootstrap ControlPlane Console is selected for native local-tool approval if exactly one matching title exists in the local chat index. Otherwise the app asks you to choose its actual ID. Other chats are discovered from hook events or, when present, the local `session_index.jsonl` label index. That index is an optional compatibility aid, not an approval-state API. You can also add a chat by ID.

## Everyday use

1. Select any number of chats in the Chats tab. Ctrl-click or Shift-click to select multiple rows.
2. Choose **Notify only** or **Auto local approvals**. Set an optional duration, or leave it running until you stop it.
3. Close the window to leave the app in the tray. Green means running, amber means attention is needed, and gray means paused.
4. Acknowledge an alert to silence its reminders. This does not approve it. Resolve the request in Codex when it needs your decision.

The tray menu opens the window, pauses/resumes the app, tests the chime, and quits. Pausing suspends both automatic decisions and repeated alerts. Closing the app also disables automatic hook decisions after its heartbeat expires (at most 12 seconds); a normal exit clears the heartbeat immediately.

## What automatic mode covers

Native automatic mode returns the documented `allow` decision only for `PermissionRequest` events named `Bash` or `apply_patch`, with a selected exact session ID, an active duration, and a live unpaused tray app. The host remains responsible for enforcing its policies. Other managed hook decisions and platform restrictions are not overridden.

MCP tools, account/authentication flows, Computer Use app permissions, and arbitrary question cards are not automatically answered by this version. A hook-observed permission request in a selected chat can still generate an alert. Codex's subagent hooks use their parent session ID, so selecting a parent chat also covers its local-tool subagents.

The app displays **Native events observed** only after receiving real hook events from that runtime. Installing hook definitions alone does not establish support in an older desktop version. A Windows app, a WSL runtime, and a remote host may have different `CODEX_HOME` directories; install on the host that actually runs the chats.

Version 2.0.3 adds an optional Windows UI Automation fallback for Auto local chats. It invokes Allow once without focusing the window, using the current card’s command, a matching Running command, and an exact unique chat header. Immediately before acting, a hidden helper checks the selected chat ID, latest index name, duplicate titles, expiry, pause state, and live tray heartbeat. The UI is checked again after that lookup. Recognized command prefixes are python, python3, py, pwsh, powershell, cmd, git, and gh, with optional .exe. These identify terminal cards; they are not a command safety review. Only command hashes are retained. Unknown layouts remain notify-only.

ChatGPT need not have keyboard focus, but the fallback needs the chat and card exposed in Windows accessibility. It cannot switch to hidden chats, guarantee detection when minimized, or handle several chats hidden behind one active tab. Multiple selected chats are eligible when their cards are exposed in open windows. Native delivery remains necessary for complete hidden-chat coverage. A disappearing card alone does not clear a reminder; successful UI approval or acknowledgement does.

Version 2.0.3 also recognizes directly submitted PowerShell variable-assignment scripts and common PowerShell cmdlets, including leading whitespace and line comments. It handles the terminal card's optional Expand/Collapse control and does not require an approval-options dropdown. Exact running-command correlation, unique selected-chat identity, and all pause/expiry/heartbeat checks remain required. Unknown intervening controls are not skipped. This remains command recognition, not a safety classification of the command's effects.

## Phone alerts

Subscribe to a private ntfy topic in the ntfy iOS/Android app and enter that topic's HTTPS URL in Settings. Supply an access token if your server requires one. Test delivery from the app. Topic names on public servers should be unguessable; authenticated topics are preferable.

Unacknowledged requests are sent immediately and repeated every two minutes. Failed sends retry no more often than every 30 seconds per request. Delivery still depends on ntfy, the server, iOS notification settings, and network availability. The app reports server acceptance, not guaranteed phone delivery.

Only a chat label and a generic attention message are sent. Commands, arguments, transcripts, and session IDs are not sent. The URL/token are stored in the local SQLite settings database; they are not included in this repository or download. Clearing the URL disables phone alerts.

## Updates and removal

Run the new installer's `Install.cmd` to update. It requests a graceful exit of the previous v2 app before copying files. The legacy utility is separate and is not automatically stopped or changed. Avoid running two approval mechanisms for the same selected chats during migration.

Run `Uninstall.cmd` from the installed app folder to stop v2, remove its hooks, and remove its shortcuts. Existing unrelated hooks remain intact. App files, settings, and hook backups are retained so you can recover them; delete the local ControlledYOLO folder afterward if desired.

## Development and verification

```text
python scripts/make_assets.py
python -m unittest discover -s tests -v
python app/main.py --demo
```

Demo mode uses temporary isolated state and does not install hooks, scan live windows, send phone alerts, or grant real permissions. Tests exercise session isolation, concurrency, pause/expiry/heartbeat handling, request lifecycle, acknowledgement, notification payloads, and non-destructive hook installation. Windows CI additionally parses the PowerShell scripts and opens/refreshes/closes the actual Tk window.

Windows CI is a runtime/package check. It does not prove live Codex event coverage or successful installation on your PC. See `docs/VALIDATION.md` for the exact delivery status and remaining live checks.

## References

- [Codex hook input, trust, and decision contract](https://learn.chatgpt.com/docs/hooks)
- [Native permission modes](https://learn.chatgpt.com/docs/permission-modes)
- [Auto-review coverage](https://learn.chatgpt.com/docs/sandboxing/auto-review)
- [ntfy publishing](https://docs.ntfy.sh/publish/)
