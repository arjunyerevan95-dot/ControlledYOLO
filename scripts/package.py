"""Build a deterministic source or bundled Windows ZIP and a base64 transport copy."""
import argparse
import base64
import hashlib
import json
import shutil
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("--exe")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
paths = []
for name in ("app", "scripts", "tests", "docs"):
    paths.extend(p for p in (root / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
paths.extend(root / name for name in ("README.md", "Install.cmd", "Install.ps1", "Launch.ps1", "Uninstall.cmd", "Uninstall.ps1"))
paths.append(root / "downloads/CodexTargetedDumbMode.zip.b64")
out = root / "dist"
out.mkdir(exist_ok=True)
name = "ControlledYOLO-2.0.3-windows" if args.exe else "ControlledYOLO-2.0.3"
target = out / (name + ".zip")
manifest = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
runtime = Path(args.exe).parent if args.exe else None
runtime_files = sorted(p for p in runtime.rglob("*") if p.is_file()) if runtime else []
for p in runtime_files:
    manifest[str(p.relative_to(runtime)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    def add(name, data):
        info = zipfile.ZipInfo("ControlledYOLO/" + name, date_time=(2026, 9, 6, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, data)
    for p in sorted(paths):
        add(str(p.relative_to(root)).replace("\\", "/"), p.read_bytes())
    for p in runtime_files:
        add(str(p.relative_to(runtime)).replace("\\", "/"), p.read_bytes())
    add("MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode())
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
digest = hashlib.sha256(target.read_bytes()).hexdigest()
(out / (name + ".sha256")).write_text(digest + "  " + target.name + "\n", encoding="ascii")
if not args.exe:
    shutil.copy2(target, root / "downloads" / target.name)
    shutil.copy2(out / (name + ".sha256"), root / "downloads" / (name + ".sha256"))
    (root / "downloads" / (name + ".zip.b64")).write_text(base64.b64encode(target.read_bytes()).decode() + "\n", encoding="ascii")
print(json.dumps({"path": str(target), "bytes": target.stat().st_size, "sha256": digest, "files": len(manifest)}))
