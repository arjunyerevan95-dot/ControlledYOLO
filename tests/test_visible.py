import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core import Store, index_titles, terminal_command


class VisibleApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000
        self.store = Store(self.temp.name, clock=lambda: self.now)
        self.store.upsert_chat("one", "Worker 1")
        self.store.configure_chat("one", True, "auto_local")
        self.store.heartbeat("test")
        self.titles = {"one": "Worker 1", "two": "Worker 2"}
        self.card = dict(session_id="one", title="Worker 1", key="button:command-hash",
                         command="python script.py", running_command="Running python script.py")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def allowed(self):
        return self.store.authorize_visible(self.card, self.titles)

    def test_live_selection_and_fresh_policy(self):
        self.assertTrue(self.allowed())
        for selected, mode in [(False, "auto_local"), (True, "notify")]:
            self.store.configure_chat("one", selected, mode)
            self.assertFalse(self.allowed())
        self.store.configure_chat("one", True, "auto_local")
        self.store.set("paused", True)
        self.assertFalse(self.allowed())
        self.store.set("paused", False)
        self.store.set("visible_monitor", False)
        self.assertFalse(self.allowed())

    def test_expiry_dead_and_future_heartbeat(self):
        self.now += 12
        self.assertFalse(self.allowed())
        self.now = 999
        self.assertFalse(self.allowed())
        self.now = 1000
        self.store.configure_chat("one", True, "auto_local", minutes=1)
        self.now += 60
        self.store.heartbeat("test")
        self.assertFalse(self.allowed())

    def test_renamed_missing_and_duplicate_titles_fail_closed(self):
        for titles in [{}, {"one": "Renamed"}, {"one": "Worker 1", "two": "worker 1"}]:
            self.titles = titles
            self.assertFalse(self.allowed())
        self.titles = {"one": "Worker 1"}
        self.store.upsert_chat("two", "Worker 1")
        self.assertFalse(self.allowed())

    def test_unknown_or_mismatched_command_never_allows(self):
        for command in ["", "mcp__send_email", "Approve", "pythonista x", "python\x00 x"]:
            self.card.update(command=command, running_command="Running " + command)
            self.assertFalse(self.allowed())
        self.card.update(command="gh api some/path", running_command="Running python other.py")
        self.assertFalse(self.allowed())

    def test_powershell_script_assignment_uses_same_selected_chat_policy(self):
        command = "$priorEditor = Get-Process -Id 21852 -ErrorAction SilentlyContinue\nif ($priorEditor) { $priorEditor.WaitForExit(30000) }"
        self.card.update(command=command, running_command="Running " + command)
        self.assertTrue(self.allowed())
        self.store.configure_chat("one", False, "auto_local")
        self.assertFalse(self.allowed())
        self.store.configure_chat("one", True, "notify")
        self.assertFalse(self.allowed())
        self.store.configure_chat("one", True, "auto_local")
        self.store.set("paused", True)
        self.assertFalse(self.allowed())

    def test_powershell_command_forms_and_invalid_lookalikes(self):
        for command in ["$priorEditor = Get-Process -Id 21852", " \n# Save/restart check\n$editor = $null",
                        "$env:EXAMPLE = 'test'", "Get-Process -Name UnrealEditor", "Start-Process example.exe"]:
            with self.subTest(command=command):
                self.assertTrue(terminal_command(command))
        for command in ["$priorEditor", "$priorEditor == something", "$priorEditor = ", "# comment only",
                        "Get permission", "Get-", "mcp__tool request", "Approve"]:
            with self.subTest(command=command):
                self.assertFalse(terminal_command(command))

    def test_flattened_accessibility_label_keeps_full_command_policy(self):
        command = "git -C example push origin worker/test\nif ($LASTEXITCODE -ne 0) { throw 'Push failed' }\ngit -C example ls-remote origin"
        self.card.update(command=command, running_command="Running " + " ".join(command.split()))
        self.assertTrue(self.allowed())
        self.assertEqual(self.card["command"], command)
        for label in ["Running git -C example push origin worker/test", "Running git -C example push origin main",
                      "Running " + " ".join(command.split()).replace("Push failed", "Different script")]:
            self.card["running_command"] = label
            self.assertFalse(self.allowed())

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell layout regression")
    def test_real_powershell_layout_function(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(root / "tests/visible_layout.ps1"), str(root / "app/VisibleMonitor.ps1")],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("11 layout cases passed", result.stdout)

    def test_approval_clears_only_exact_card_and_new_command_is_distinct(self):
        other = dict(self.card, key="button:different-command-hash")
        self.store.visible_snapshot([self.card, other])
        self.store.record_visible_approval(self.card)
        self.store.visible_snapshot([self.card, other])
        self.assertEqual(len(self.store.attention()), 1)
        self.assertEqual(len([r for r in self.store.requests() if r["status"] == "allowed_by_ui"]), 1)
        self.assertNotIn("python script.py", json.dumps(self.store.requests()))

    def test_full_index_uses_latest_name_and_rejects_partial_input(self):
        path = Path(self.temp.name) / "session_index.jsonl"
        path.write_text('\n'.join(json.dumps(r) for r in [
            {"id": "one", "thread_name": "Old"},
            {"id": "one", "thread_name": "Worker 1"},
            {"id": "two", "thread_name": "Worker 2"}]), encoding="utf-8")
        self.assertEqual(index_titles(path), self.titles)
        with path.open("a") as f:
            f.write('\n{"id":')
        with self.assertRaises(ValueError):
            index_titles(path)

    def test_helper_process_reads_current_policy_and_fails_closed(self):
        path = Path(self.temp.name) / "session_index.jsonl"
        path.write_text(json.dumps({"id": "one", "thread_name": "Worker 1"}), encoding="utf-8")
        self.store.clock = time.time
        self.store.heartbeat("live")
        entry = Path(__file__).resolve().parents[1] / "app/main.py"
        def invoke(payload):
            result = subprocess.run([sys.executable, str(entry), "--check-visible"], input=payload,
                                    capture_output=True, timeout=5,
                                    env=dict(os.environ, CONTROLLEDYOLO_HOME=self.temp.name, CODEX_HOME=self.temp.name))
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["allow"]
        self.assertTrue(invoke(json.dumps(self.card).encode()))
        command = "$priorEditor = Get-Process -Id 21852\nif ($priorEditor) { $priorEditor.WaitForExit(30000) }"
        script_card = dict(self.card, command=command, running_command="Running " + command)
        self.assertTrue(invoke(json.dumps(script_card).encode()))
        script_card["running_command"] = "Running " + " ".join(command.split())
        self.assertTrue(invoke(json.dumps(script_card).encode()))
        self.store.set("paused", True)
        self.assertFalse(invoke(json.dumps(self.card).encode()))
        self.assertFalse(invoke(json.dumps(script_card).encode()))
        self.assertFalse(invoke(b"malformed"))
