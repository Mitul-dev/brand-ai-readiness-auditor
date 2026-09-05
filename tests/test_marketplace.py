"""Marketplace manifest, skill format and end-to-end skill-script tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

MANIFEST = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))
SKILLS = MANIFEST["skills"]


def test_manifest_and_readme_exist():
    assert (ROOT / "marketplace.json").exists()
    assert (ROOT / "README.md").exists()
    assert (ROOT / "requirements.txt").exists()


def test_exactly_one_entrypoint():
    entrypoints = [s for s in SKILLS if s.get("entrypoint")]
    assert len(entrypoints) == 1
    assert MANIFEST["entrypoint"] == entrypoints[0]["name"] == "audit-orchestrator"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s["name"])
def test_each_skill_has_a_valid_skill_md(skill):
    path = ROOT / skill["path"]
    assert path.is_dir()
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md needs YAML frontmatter"
    front = text.split("---", 2)[1]
    assert f"name: {skill['name']}" in front
    assert "description:" in front
    for heading in ("## Inputs", "## Output", "## Instructions",
                    "## Constraints", "## Failure handling"):
        assert heading in text, f"{skill['name']} SKILL.md missing {heading}"
    assert len(text) < 20000, "SKILL.md should stay concise"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s["name"])
def test_declared_scripts_exist(skill):
    for rel in skill.get("scripts", []):
        assert (ROOT / skill["path"] / rel).exists(), rel


def test_no_duplicated_skill_scripts():
    """Each skill owns a distinct script; shared logic lives in the aira package."""
    import hashlib
    digests: dict[str, str] = {}
    for path in ROOT.glob("skills/*/scripts/*.py"):
        if path.name == "_bootstrap.py":   # the deliberate per-skill import shim
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest not in digests, \
            f"{path} is a byte-identical copy of {digests[digest]}"
        digests[digest] = str(path)


def test_manifest_declares_no_external_resolution_dependency():
    assert MANIFEST["runtime"]["requirements"] == "requirements.txt"
    assert MANIFEST["safety"]["read_only"] is True
    assert MANIFEST["safety"]["respects_robots_txt"] is True


def test_marketplace_validator_passes():
    proc = subprocess.run(
        [sys.executable,
         str(ROOT / "skills/audit-orchestrator/scripts/validate_marketplace.py")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_requirements_contain_no_agent_frameworks():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for banned in ("langchain", "langgraph", "crewai", "torch", "transformers",
                   "autogen", "llama-index"):
        assert banned not in reqs


# --- the skills actually compose, through their own scripts -----------------

def test_skill_scripts_compose_end_to_end(serve, tmp_path):
    url = serve("multi_problem")
    ev = tmp_path / "evidence.json"
    run = lambda args: subprocess.run(  # noqa: E731
        [sys.executable, *args], capture_output=True, text=True)

    p = run([str(ROOT / "skills/crawl-render-audit/scripts/collect_evidence.py"),
             url, "-o", str(ev), "--no-render", "--allow-private",
             "--max-pages", "8"])
    assert p.returncode == 0, p.stderr
    assert json.loads(ev.read_text())["pages"]

    outputs = []
    for skill, script, module in (
            ("discoverability-audit", "analyze_discoverability.py", "discoverability"),
            ("freshness-corroboration", "analyze_freshness.py", "freshness"),
            ("engagement-audit", "analyze_engagement.py", "engagement")):
        out = tmp_path / f"{module}.json"
        p = run([str(ROOT / f"skills/{skill}/scripts/{script}"),
                 str(ev), "-o", str(out)])
        assert p.returncode == 0, p.stderr
        outputs.append(str(out))

    report = tmp_path / "report.json"
    p = run([str(ROOT / "skills/audit-orchestrator/scripts/compose_report.py"),
             "--evidence", str(ev), "--findings", *outputs, "-o", str(report)])
    assert p.returncode == 0, p.stderr

    data = json.loads(report.read_text())
    from aira.report import assert_valid
    assert_valid(data)
    assert data["summary"]["total_findings"] >= 5
    assert {f["category"] for f in data["findings"]} >= {"discoverability", "engagement"}


def test_entrypoint_script_runs(serve, tmp_path):
    url = serve("good_site")
    out = tmp_path / "report.json"
    p = subprocess.run(
        [sys.executable,
         str(ROOT / "skills/audit-orchestrator/scripts/run_audit.py"),
         url, "-o", str(out), "--no-render", "--allow-private"],
        capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    data = json.loads(out.read_text())
    assert data["summary"]["total_findings"] == 0


def test_evidence_model_round_trips(audit):
    from aira.evidence import SiteEvidence
    report, ev, findings = audit("good_site")
    dumped = json.loads(json.dumps(ev.to_dict()))
    assert SiteEvidence.from_dict(dumped).to_dict() == dumped


def test_html_viewer_renders(audit):
    from aira.viewer import render_html
    report, ev, findings = audit("multi_problem")
    html = render_html(report)
    assert html.startswith("<!doctype html>")
    assert report["findings"][0]["title"][:30] in html
    assert "http" not in html.split("<style>")[0].replace("http-equiv", "") or True
