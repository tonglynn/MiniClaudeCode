"""Five modes; deny rules and dangerous-command checks precede confirmations."""
import fnmatch
import hashlib
import json
import re

MODES = ("read_only", "ask", "auto_edit", "auto", "plan")
DANGEROUS = [
    ("recursive_rm", r"\brm\s+[^\n]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)"),
    ("windows_recursive_delete", r"\b(?:remove-item|del|rmdir|rd)\b[^\n]*(?:-recurse|/s)"),
    ("format_volume", r"\bformat(?:\.com)?\s+[a-z]:"),
    ("diskpart", r"\bdiskpart\b"),
    ("shutdown", r"\b(?:shutdown|reboot|restart-computer|stop-computer)\b"),
    ("raw_disk_write", r"\bdd\b[^\n]*\bof="),
    ("git_hard_reset", r"\bgit\s+reset\s+--hard\b"),
    ("git_clean", r"\bgit\s+clean\b[^\n]*-[a-z]*[fd]"),
    ("git_force_push", r"\bgit\s+push\b[^\n]*(?:--force|-f\b)"),
    ("download_execute", r"\b(?:curl|wget|iwr|invoke-webrequest)\b[^\n]*\|\s*(?:sh|bash|iex|invoke-expression)\b"),
    ("encoded_shell", r"\b(?:powershell|pwsh)\b[^\n]*-(?:enc\b|encodedcommand\b)"),
    ("world_writable", r"\bchmod\b[^\n]*777\b"),
    ("credential_path", r"(?:\.ssh[/\\](?:id_|authorized_keys)|\.aws[/\\]credentials|\.provider_private\.json)"),
    ("shell_chain", r"(?:&&|\|\||;|\$\(|`|\r|\n)"),
    ("script_eval", r"\b(?:python(?:\.exe)?\s+-c|node(?:\.exe)?\s+-e|invoke-expression|iex)\b"),
    ("privilege_change", r"\b(?:sudo|runas|takeown|icacls)\b"),
]


class Denied(PermissionError):
    pass


class Policy:
    def __init__(self, mode="ask", rules=None, confirm=None):
        if mode not in MODES:
            raise ValueError(f"Unknown permission mode: {mode}")
        self.mode, self.rules, self.confirm = mode, rules or {"allow": [], "deny": []}, confirm
        self.whitelist = set()

    def dangerous(self, command):
        return [name for name, pattern in DANGEROUS if re.search(pattern, command, re.I)]

    async def check(self, name, args, effect):
        signature = name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)
        command = " ".join(args.get("argv", [])) if isinstance(args.get("argv"), list) else signature
        if name == "run_command":
            hits = self.dangerous(command)
            if hits:
                raise Denied("dangerous_command:" + ",".join(hits))
        if any(fnmatch.fnmatchcase(signature, p) for p in self.rules.get("deny", [])):
            raise Denied("declarative_deny")
        if self.mode in ("read_only", "plan") and effect in ("write", "exec"):
            raise Denied("mode_denied:" + self.mode)
        if effect in ("read", "internal"):
            return
        digest = hashlib.sha256(signature.encode()).hexdigest()
        if digest in self.whitelist:
            return
        allowed = any(fnmatch.fnmatchcase(signature, p) for p in self.rules.get("allow", []))
        if allowed or self.mode == "auto" or (self.mode == "auto_edit" and effect == "write"):
            return
        response = await self.confirm(name, args) if self.confirm else "no"
        if response == "always":
            self.whitelist.add(digest)
        elif response != "yes":
            raise Denied("confirmation_denied")
