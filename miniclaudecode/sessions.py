import json
import os
import tempfile
import uuid
from pathlib import Path
from .config import scrub


class Sessions:
    def __init__(self, state, root):
        self.folder = state / "sessions"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.root = str(root.resolve())
        self.id = uuid.uuid4().hex[:12]

    def save(self, messages, plan, active, mode):
        payload = {"id": self.id, "root": self.root, "messages": messages, "plan": plan,
                   "active_tools": sorted(active), "mode": mode}
        data = scrub(json.dumps(payload, ensure_ascii=False, indent=2))
        fd, name = tempfile.mkstemp(dir=self.folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
        os.replace(name, self.folder / (self.id + ".json"))

    def load(self, session_id):
        if not session_id.isalnum() or len(session_id) > 64:
            raise ValueError("Invalid session id")
        data = json.loads((self.folder / (session_id + ".json")).read_text(encoding="utf-8"))
        if data["root"] != self.root:
            raise ValueError("Session belongs to a different workspace")
        if not isinstance(data["messages"], list) or any(m.get("role") not in ("system", "user", "assistant", "tool") for m in data["messages"]):
            raise ValueError("Malformed session")
        self.id = session_id
        return data

    def list(self):
        return [p.stem for p in sorted(self.folder.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)]
