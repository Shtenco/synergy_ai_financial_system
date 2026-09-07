#!/usr/bin/env python3
"""Fail CI if the new SYNERGY runtime surface tracks a wallet secret."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX_KEY = re.compile(r"(?<![0-9A-Fa-f])(?:0x)?[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
# Deliberately use horizontal whitespace only. ``\s`` also matches newlines and
# can misread an empty `PRIVATE_KEY=` template as if the next ENV assignment
# were its value.
PRIVATE_KEY_ASSIGNMENT = re.compile(r"(?im)^[ \t]*PRIVATE_KEY[ \t]*=[ \t]*([^\r\n]*)$")

SECURITY_SURFACE = (
    "runtime/synergy_agent/",
    "ai_centrobank/synergy_runtime_guard.py",
    "scripts/synergy_secure_vault.py",
    "scripts/synergy_agent_preflight.py",
    "scripts/run_synergy_agent_guarded.py",
    "scripts/check_no_synergy_secrets.py",
    "tests/test_synergy_runtime_guard.py",
    "docs/SYNERGY_RL_SAFE_EXECUTION.md",
    ".github/workflows/synergy-rl-security.yml",
    "requirements-synergy-agent.txt",
)


def tracked_paths() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [p.decode() for p in out.split(b"\0") if p]


def in_security_surface(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in SECURITY_SURFACE)


def main() -> int:
    failures: list[str] = []
    for rel in tracked_paths():
        # This workflow is intentionally a scoped guard for the new SYNERGY
        # runtime surface. Historical repository files are handled by broader
        # repository hygiene work and must not make this targeted gate unusable.
        if not in_security_surface(rel):
            continue

        lowered = rel.lower()
        if rel.startswith("runtime/synergy_agent/local/") and not rel.endswith("/.gitkeep"):
            failures.append(f"tracked runtime secret path: {rel}")
            continue
        if lowered.endswith(".env"):
            failures.append(f"tracked env file in runtime security surface: {rel}")
            continue

        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for assignment in PRIVATE_KEY_ASSIGNMENT.finditer(text):
            value = assignment.group(1).strip().strip('"\'')
            if value and value not in {"${PRIVATE_KEY}", "<PRIVATE_KEY>", "REDACTED"}:
                failures.append(f"populated PRIVATE_KEY assignment in {rel}")
                break
        else:
            for match in HEX_KEY.finditer(text):
                stripped = match.group(0).removeprefix("0x")
                if len(set(stripped.lower())) <= 2:
                    continue
                context = text[max(0, match.start() - 100): match.start()].lower()
                if any(word in context for word in ("sha", "hash", "commit", "block")):
                    continue
                failures.append(f"possible 32-byte wallet secret in {rel}")
                break

    if failures:
        print("SECRET SCAN FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("SECRET SCAN PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
