"""One-command portable bootstrap; agent is the default, not a demo script."""
import hashlib
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    venv = root / ".venv"
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    requirements = root / "requirements-lock.txt"
    if not requirements.exists():
        requirements = root / "requirements.txt"
    stamp = venv / ".requirements.sha256"
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    if not stamp.exists() or stamp.read_text() != expected:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        stamp.write_text(expected)
    args = sys.argv[1:]
    mode = args.pop(0) if args and args[0] in ("agent", "audit", "test", "check") else "agent"
    if mode == "agent":
        if "--workspace" not in args:
            workspace = root / "workspace"
            workspace.mkdir(exist_ok=True)
            args = ["--workspace", str(workspace), *args]
        command = [str(python), "-m", "miniclaudecode", *args]
    elif mode == "audit":
        command = [str(python), "-m", "audit", *args]
    elif mode == "test":
        command = [str(python), "-m", "pytest", "tests", "-q", *args]
    else:
        command = [str(python), "-m", "audit", "--offline-check", *args]
    return subprocess.run(command, cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
