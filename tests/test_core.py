import concurrent.futures
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core import Store
from hooks import merge_hooks, register
from main import select_title
from notifications import validate_url, send


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.store = Store(self.temp.name, clock=lambda: self.now)
        for sid in ("one", "two", "unselected"):
            self.store.upsert_chat(sid, "Same title" if sid != "unselected" else "Third")
        self.store.configure_chat("one", True, "auto_local")
        self.store.configure_chat("two", True, "notify")
        self.store.heartbeat("test")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def event(self, session="one", kind="PermissionRequest", tool="Bash", turn="turn-a", command="echo hello"):
        return {"session_id": session, "hook_event_name": kind, "tool_name": tool,
                "turn_id": turn, "tool_input": {"command": command}}

    def test_allow_selected_local_chat_only(self):
        expected = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        self.assertEqual(self.store.handle_hook(self.event()), expected)
        self.assertEqual(self.store.handle_hook(self.event("unselected")), {})
        self.assertEqual(self.store.handle_hook(self.event("two")), {})
        self.assertEqual(len(self.store.attention()), 1)

    def test_same_title_never_shares_native_permission(self):
        self.assertTrue(self.store.handle_hook(self.event("one")))
        self.assertFalse(self.store.handle_hook(self.event("two")))

    def test_pause_and_expiry(self):
        self.store.set("paused", True)
        self.assertFalse(self.store.handle_hook(self.event()))
        self.store.set("paused", False)
        self.store.configure_chat("one", True, "auto_local", minutes=1)
        self.now += 60
        self.store.heartbeat("test")
        self.assertFalse(self.store.handle_hook(self.event()))

    def test_dead_or_future_heartbeat_never_allows(self):
        self.now += 13
        self.assertFalse(self.store.handle_hook(self.event()))
        self.now = 999
        self.assertFalse(self.store.handle_hook(self.event()))
        self.store.stop_heartbeat("test")
        self.assertFalse(self.store.handle_hook(self.event()))

    def test_other_instance_cannot_clear_heartbeat(self):
        self.store.stop_heartbeat("other-owner")
        self.assertTrue(self.store.handle_hook(self.event()))

    def test_unknown_tool_mcp_and_missing_turn_do_not_allow(self):
        for tool in ("mcp__mail__send", "Approve", "Bash;other", "Edit", "Unknown tool"):
            self.assertFalse(self.store.handle_hook(self.event(tool=tool)))
        self.assertFalse(self.store.handle_hook(self.event(turn="")))

    def test_malformed_and_unsupported_events(self):
        for value in (None, [], {}, self.event(session=""), self.event(session="title with spaces"), self.event(kind="Notification")):
            self.assertEqual(self.store.handle_hook(value), {})

    def test_exact_completion_correlation(self):
        self.store.handle_hook(self.event("two", command="A"))
        self.store.handle_hook(self.event("two", command="B"))
        self.store.handle_hook(self.event("two", kind="PostToolUse", command="A"))
        self.assertEqual(len(self.store.attention()), 1)
        self.store.handle_hook(self.event("one", kind="PostToolUse", command="B"))
        self.assertEqual(len(self.store.attention()), 1)

    def test_identical_parallel_calls_clear_one_at_a_time(self):
        self.store.handle_hook(self.event("two"))
        self.store.handle_hook(self.event("two"))
        self.store.handle_hook(self.event("two", kind="PostToolUse"))
        self.assertEqual(len(self.store.attention()), 1)

    def test_stop_clears_only_its_turn(self):
        self.store.handle_hook(self.event("two", turn="first"))
        self.store.handle_hook(self.event("two", turn="second"))
        self.store.handle_hook(self.event("two", kind="Stop", turn="first"))
        self.assertEqual([r["turn_id"] for r in self.store.attention()], ["second"])
        self.store.handle_hook(self.event("two", kind="Stop", turn=""))
        self.assertEqual(len(self.store.attention()), 1)

    def test_acknowledge_silences_without_approving(self):
        self.store.handle_hook(self.event("two"))
        row = self.store.attention()[0]
        self.store.acknowledge([row["id"]])
        self.assertEqual(self.store.attention(), [])
        self.assertEqual(self.store.requests()[0]["status"], "pending")
        self.store.handle_hook(self.event("two", command="new request"))
        self.assertEqual(len(self.store.attention()), 1)

    def test_persistence_and_no_command_storage(self):
        self.store.handle_hook(self.event("two", command="secret-argument-not-to-be-stored"))
        other = Store(self.temp.name, clock=lambda: self.now)
        self.assertEqual(len(other.attention()), 1)
        self.assertNotIn(b"secret-argument-not-to-be-stored", self.store.path.read_bytes())
        other.close()

    def test_many_chats_and_concurrent_requests(self):
        for n in range(25):
            self.store.upsert_chat(f"chat-{n}", f"Chat {n}")
            self.store.configure_chat(f"chat-{n}", True, "auto_local")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            result = list(executor.map(lambda n: self.store.handle_hook(self.event(f"chat-{n}")), range(25)))
        self.assertTrue(all(result))
        self.assertEqual(len(self.store.requests()), 25)

    def test_separate_hook_processes_share_selected_policy(self):
        import time
        self.store.clock = time.time
        self.store.heartbeat("live-test")
        entry = Path(__file__).resolve().parents[1] / "app/main.py"
        def invoke(n):
            return subprocess.run([sys.executable, str(entry), "--hook"], input=json.dumps(self.event(command=f"test-{n}")).encode(),
                                  capture_output=True, env=dict(os.environ, CONTROLLEDYOLO_HOME=self.temp.name), timeout=8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(invoke, range(4)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"], "allow")

    def test_visible_cards_do_not_authorize_and_duplicate_title_ignored(self):
        self.store.visible_snapshot([{"title": "Same title", "key": "button-a"}])
        self.assertEqual(self.store.requests(), [])
        self.store.upsert_chat("two", "Distinct title")
        self.store.visible_snapshot([{"title": "Distinct title", "key": "button-a"}])
        self.assertEqual(len(self.store.attention()), 1)
        self.assertEqual(self.store.requests()[0]["source"], "visible")

    def test_hidden_visible_card_not_falsely_resolved(self):
        self.store.upsert_chat("two", "Distinct title")
        card = {"title": "Distinct title", "key": "button-a"}
        self.store.visible_snapshot([card])
        self.store.visible_snapshot([card])
        self.assertEqual(len(self.store.attention()), 1)
        self.store.acknowledge([self.store.attention()[0]["id"]])
        self.store.visible_snapshot([])
        self.store.visible_snapshot([card])
        self.assertEqual(len(self.store.attention()), 1)
        self.assertEqual(len(self.store.requests()), 2)

    def test_index_is_labels_only_and_respects_existing_selection(self):
        path = Path(self.temp.name) / "index.jsonl"
        path.write_text('\n'.join(["bad", json.dumps({"id": "one", "thread_name": "Renamed"}),
                                   json.dumps({"id": "new-id", "thread_name": "New chat"}),
                                   json.dumps({"id": "not an id", "thread_name": "Bad"})]))
        self.assertEqual(self.store.import_index(path), 2)
        rows = {c["id"]: c for c in self.store.chats()}
        self.assertEqual(rows["one"]["mode"], "auto_local")
        self.assertFalse(rows["new-id"]["selected"])
        self.assertIsNone(rows["new-id"]["native_seen"])

    def test_title_selection_requires_unique_exact_match(self):
        self.assertFalse(select_title(self.store, "Same title", "auto_local"))
        self.assertFalse(select_title(self.store, "Same", "auto_local"))
        self.assertTrue(select_title(self.store, "Third", "notify"))


class HookSetupTests(unittest.TestCase):
    def test_preserves_unrelated_handlers_and_is_idempotent(self):
        original = {"description": "My hooks", "hooks": {"PermissionRequest": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-check"}]}], "OtherEvent": []}}
        copied = copy.deepcopy(original)
        first = merge_hooks(original, '"python" "main.py" "--hook"')
        self.assertEqual(original, copied)
        self.assertEqual(first, merge_hooks(first, '"python" "main.py" "--hook"'))
        self.assertEqual(merge_hooks(first, "", remove=True), original)

    def test_invalid_existing_config_is_untouched(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "hooks.json"
            path.write_text('{"hooks": ["unsupported"]}')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                register(home)
            self.assertEqual(before, path.read_bytes())

    def test_backup_and_remove(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "hooks.json"
            path.write_text('{"hooks":{}}')
            register(home, executable="python.exe", script="C:/A Folder/main.py")
            self.assertEqual(len(list(Path(home).glob("*backup*"))), 1)
            config = json.loads(path.read_text())
            self.assertIn('"C:/A Folder/main.py"', config["hooks"]["PermissionRequest"][0]["hooks"][0]["command"])
            register(home, executable="python.exe", remove=True)
            self.assertEqual(json.loads(path.read_text()), {"hooks": {}})

    def test_pythonw_replaced_for_hook_stdout(self):
        with tempfile.TemporaryDirectory() as home:
            path = register(home, executable="C:/Python/pythonw.exe", script="C:/App/main.py")
            command = json.loads(path.read_text())["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
            self.assertIn("python.exe", command)
            self.assertNotIn("pythonw.exe", command)

    def test_hook_process_preserves_normal_flow_on_bad_input(self):
        main = Path(__file__).resolve().parents[1] / "app/main.py"
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run([sys.executable, str(main), "--hook"], input=b"not-json", capture_output=True,
                                    env=dict(os.environ, CONTROLLEDYOLO_HOME=home))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


class PushTests(unittest.TestCase):
    def test_https_topic_only(self):
        self.assertEqual(validate_url("https://ntfy.sh/private-topic"), "https://ntfy.sh/private-topic")
        for url in ("http://ntfy.sh/topic", "https://user:pass@ntfy.sh/topic", "https://ntfy.sh/topic?token=x", "https://ntfy.sh/"):
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_push_has_no_transcript_or_tool_payload(self):
        with patch("notifications.urllib.request.build_opener") as mocked:
            mocked.return_value.open.return_value.__enter__.return_value.status = 200
            send("https://ntfy.sh/test-topic", "test-token", "Chat title")
            request = mocked.return_value.open.call_args.args[0]
            self.assertIn(b"Chat title", request.data)
            self.assertNotIn(b"command", request.data)
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")


@unittest.skipUnless(os.name == "nt", "Windows GUI and PowerShell smoke tests")
class WindowsTests(unittest.TestCase):
    def test_tray_starts_updates_and_closes(self):
        from tray import Tray
        tray = Tray(lambda action: None)
        try:
            self.assertTrue(tray.start(), tray.error or "Tray did not initialize")
            tray.state("attention", "ControlledYOLO Windows smoke test")
        finally:
            tray.close()
            if tray.thread.is_alive():
                tray.thread.join(3)
        self.assertFalse(tray.thread.is_alive())

    def test_powershell_syntax(self):
        root = Path(__file__).resolve().parents[1]
        code = "$files = Get-ChildItem -LiteralPath $args[0] -Filter *.ps1 -Recurse; foreach ($file in $files) { $tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 } }"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False) as script:
            script.write(code)
        try:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-File", script.name, str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            Path(script.name).unlink()

    def test_window_constructs_refreshes_and_closes(self):
        from main import App
        with tempfile.TemporaryDirectory() as home:
            store = Store(home)
            store.upsert_chat("smoke-chat", "Smoke test")
            store.configure_chat("smoke-chat", True)
            app = App(store, demo=True)
            app.root.after(1200, app.quit)
            app.run()
            self.assertEqual(store.get("heartbeat"), {})
            store.close()


if __name__ == "__main__":
    unittest.main()
