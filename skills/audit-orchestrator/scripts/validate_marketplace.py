#!/usr/bin/env python3
"""Validate marketplace.json and every SKILL.md without any network access.

    python validate_marketplace.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _bootstrap import bootstrap

ROOT = bootstrap()

REQUIRED_MANIFEST_KEYS = ("name", "version", "description", "entrypoint", "skills")
REQUIRED_SKILL_KEYS = ("name", "path", "description")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def check() -> list[str]:
    problems: list[str] = []
    manifest_path = ROOT / "marketplace.json"
    if not manifest_path.exists():
        return ["marketplace.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"marketplace.json is not valid JSON: {exc}"]

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            problems.append(f"marketplace.json missing key: {key}")
    if not (ROOT / "README.md").exists():
        problems.append("README.md is missing at the marketplace root")

    skills = manifest.get("skills", [])
    names = [s.get("name") for s in skills]
    if len(names) != len(set(names)):
        problems.append("duplicate skill names in marketplace.json")

    entrypoints = [s for s in skills if s.get("entrypoint")]
    if len(entrypoints) != 1:
        problems.append(
            f"exactly one skill must be marked as entrypoint, found {len(entrypoints)}")
    elif manifest.get("entrypoint") != entrypoints[0].get("name"):
        problems.append("manifest.entrypoint does not match the skill flagged as entrypoint")

    for skill in skills:
        for key in REQUIRED_SKILL_KEYS:
            if key not in skill:
                problems.append(f"skill entry missing {key}: {skill}")
        path = ROOT / skill.get("path", "")
        if not path.is_dir():
            problems.append(f"skill path does not exist: {skill.get('path')}")
            continue
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            problems.append(f"{skill.get('name')}: SKILL.md is missing")
            continue
        text = skill_md.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            problems.append(f"{skill.get('name')}: SKILL.md has no YAML frontmatter")
            continue
        front = m.group(1)
        for key in ("name", "description"):
            if not re.search(rf"^{key}\s*:", front, re.M):
                problems.append(f"{skill.get('name')}: SKILL.md frontmatter missing '{key}'")
        name_match = re.search(r"^name\s*:\s*(.+)$", front, re.M)
        if name_match and name_match.group(1).strip().strip("\"'") != skill.get("name"):
            problems.append(
                f"{skill.get('name')}: SKILL.md frontmatter name does not match the manifest")
        if len(text) > 20000:
            problems.append(f"{skill.get('name')}: SKILL.md is unusually large")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("MARKETPLACE INVALID")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("MARKETPLACE VALID: manifest, entrypoint and all SKILL.md files check out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
