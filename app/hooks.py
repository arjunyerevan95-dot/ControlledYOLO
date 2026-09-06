"""Non-destructive hook registration; Codex's own trust review remains in place."""
import copy
import json
from pathlib import Path
import shutil
import sys
import time

from core import EVENTS

MARKER = "ControlledYOLO native bridge"


def merge_hooks(config, command, remove=False):
    result = copy.deepcopy(config)
    if not isinstance(result, dict) or not isinstance(result.get("hooks", {}), dict):
        raise ValueError("Existing hooks.json has an unsupported format; it was not changed.")
    hooks = result.setdefault("hooks", {})
    for event in sorted(EVENTS):
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"Existing {event} configuration is not a list; it was not changed.")
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list):
                raise ValueError("Existing hook entry is unsupported; it was not changed.")
            handlers = [h for h in entry.get("hooks", []) if not (isinstance(h, dict) and h.get("statusMessage") == MARKER)]
            if handlers or not entry.get("hooks"):
                item = copy.deepcopy(entry)
                item["hooks"] = handlers
                kept.append(item)
        if not remove:
            kept.append({"hooks": [{"type": "command", "command": command, "commandWindows": command,
                                    "timeout": 3 if event in {"SessionEnd", "Interrupt"} else 8, "statusMessage": MARKER}]})
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return result


def register(codex_home, executable=None, script=None, remove=False):
    folder = Path(codex_home)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "hooks.json"
    old_bytes = path.read_bytes() if path.exists() else None
    existing = json.loads(old_bytes.decode("utf-8-sig")) if old_bytes else {}
    executable = str(executable or sys.executable)
    if Path(executable).name.lower() == "pythonw.exe":
        executable = str(Path(executable).with_name("python.exe"))
    args = [executable]
    if not getattr(sys, "frozen", False):
        args.append(str(script or Path(__file__).with_name("main.py").resolve()))
    args.append("--hook")
    if any(any(c in a for c in '\"\r\n%!') for a in args):
        raise ValueError("The executable path contains unsupported shell characters.")
    command = " ".join('"' + a + '"' for a in args)
    updated = merge_hooks(existing, command, remove)
    if updated == existing:
        return path
    if old_bytes is not None:
        shutil.copy2(path, folder / ("hooks.json.controlledyolo-backup-" + str(time.time_ns())))
    temporary = path.with_name("hooks.json.controlledyolo-new")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    # Detect a concurrent edit rather than overwrite it.
    if (path.read_bytes() if path.exists() else None) != old_bytes:
        temporary.unlink()
        raise RuntimeError("hooks.json changed during setup; retry after the other editor finishes.")
    temporary.replace(path)
    return path
