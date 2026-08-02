#!/usr/bin/env python3
"""Fail CI if a likely wallet secret or populated runtime env is tracked."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX_KEY = re.compile(r"(?<![0-9A-Fa-f])(?:0x)?[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
ALLOW_SUFFIXES = {".md", ".py", ".js", ".ts", ".sol", ".json", ".yml", ".yaml", ".example", ".txt"}


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / p.decode() for p in out.split(b"\0") if p]


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        lowered = rel.lower()
        if lowered.endswith(".env") or "/local/" in lowered:
            failures.append(f"tracked runtime secret path: {rel}")
            continue
        if path.suffix.lower() not in ALLOW_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in HEX_KEY.finditer(text):
            token = match.group(0)
            stripped = token.removeprefix("0x")
            if len(set(stripped.lower())) <= 2:
                continue
            context = text[max(0, match.start() - 80): match.start()].lower()
            if "sha" in context or "hash" in context or "block" in context or "commit" in context:
                continue
            failures.append(f"possible 32-byte secret in {rel}")
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
