from __future__ import annotations

import io
import json
import secrets
import threading
from collections import OrderedDict

from flask import (
    Flask, Response, request, render_template_string, send_file,
)

from aira.config import AuditConfig
from aira.orchestrator import AuditError, run_audit
from aira.viewer import render_html


app = Flask(__name__)

# Completed reports, addressed by an unguessable token.
#
# A single shared "latest report" file would hand whichever audit ran most
# recently to every other visitor, and would write to the working directory on
# each download - which also fails on a read-only container filesystem. Reports
# are therefore held in memory, keyed per run, and served from memory.
MAX_CACHED_REPORTS = 20
_REPORTS: "OrderedDict[str, dict]" = OrderedDict()
_REPORTS_LOCK = threading.Lock()


def _store_report(report: dict) -> str:
    """Cache a report and return its download token."""
    token = secrets.token_urlsafe(16)
    with _REPORTS_LOCK:
        _REPORTS[token] = report
        while len(_REPORTS) > MAX_CACHED_REPORTS:
            _REPORTS.popitem(last=False)
    return token


def _load_report(token: str) -> dict | None:
    with _REPORTS_LOCK:
        return _REPORTS.get(token)


HTML = r"""
<!doctype html>
<html lang="en">

<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>AI Website Readiness Auditor</title>

<style>

:root {
    --bg: #f4f5f7;
    --card: #ffffff;
    --card2: #fafafa;
    --text: #171717;
    --muted: #707070;
    --border: #dedede;
    --accent: #5b5cf0;
    --accent2: #7c3aed;
    --danger: #c62828;
    --shadow: 0 10px 30px rgba(0, 0, 0, .06);
}

[data-theme="dark"] {
    --bg: #101114;
    --card: #191b20;
    --card2: #15171b;
    --text: #f3f4f6;
    --muted: #9da1aa;
    --border: #2b2e35;
    --accent: #8586ff;
    --accent2: #a78bfa;
    --danger: #ff6b6b;
    --shadow: 0 12px 35px rgba(0, 0, 0, .25);
}

* {
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
}

body {
    margin: 0;
    background: var(--bg);
    color: var(--text);

    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    transition:
        background .2s ease,
        color .2s ease;
}

button,
input {
    font: inherit;
}


/* =========================
   TOP BAR
========================= */

.topbar {

    height: 70px;

    border-bottom: 1px solid var(--border);

    background: var(--card);

    display: flex;

    align-items: center;

    justify-content: space-between;

    padding: 0 28px;

    position: sticky;

    top: 0;

    z-index: 20;
}


.brand {

    display: flex;

    align-items: center;

    gap: 12px;

    font-weight: 700;
}


.brand-mark {

    width: 34px;

    height: 34px;

    border-radius: 9px;

    display: grid;

    place-items: center;

    color: white;

    background:
        linear-gradient(
            135deg,
            var(--accent),
            var(--accent2)
        );

    font-weight: 800;
}


.theme-btn {

    width: 40px;

    height: 40px;

    border: 1px solid var(--border);

    background: var(--card2);

    color: var(--text);

    border-radius: 10px;

    cursor: pointer;

    display: grid;

    place-items: center;

    font-size: 18px;

    transition:
        background .2s ease,
        transform .15s ease;
}


.theme-btn:hover {

    transform: scale(1.05);

}


/* =========================
   MAIN
========================= */

.container {

    max-width: 1180px;

    margin: auto;

    padding: 45px 22px 80px;
}


.hero {

    margin-bottom: 30px;
}


.hero h1 {

    font-size: 38px;

    line-height: 1.1;

    margin: 0 0 10px;

    letter-spacing: -1.5px;
}


.hero p {

    color: var(--muted);

    max-width: 700px;

    margin: 0;

    font-size: 16px;
}


/* =========================
   AUDIT FORM
========================= */

.audit-form {

    background: var(--card);

    border: 1px solid var(--border);

    border-radius: 16px;

    padding: 20px;

    box-shadow: var(--shadow);
}


.audit-form label {

    display: block;

    font-size: 13px;

    font-weight: 700;

    margin-bottom: 8px;
}


.form-row {

    display: flex;

    gap: 10px;
}


.url-input {

    flex: 1;

    min-width: 0;

    padding: 14px 15px;

    border: 1px solid var(--border);

    border-radius: 10px;

    background: var(--card2);

    color: var(--text);

    outline: none;
}


.url-input:focus {

    border-color: var(--accent);
}


.audit-btn {

    border: 0;

    border-radius: 10px;

    padding: 0 25px;

    color: white;

    background: var(--accent);

    font-weight: 700;

    cursor: pointer;

    transition:
        opacity .2s ease,
        transform .15s ease;
}


.audit-btn:hover {

    opacity: .9;

    transform: translateY(-1px);
}


/* =========================
   ERROR
========================= */

.error {

    margin-top: 15px;

    padding: 13px 15px;

    border-radius: 10px;

    background: rgba(198, 40, 40, .10);

    border: 1px solid rgba(198, 40, 40, .35);

    color: var(--danger);
}


/* =========================
   DASHBOARD
========================= */

.dashboard {

    margin-top: 28px;
}


.section-title {

    margin: 30px 0 13px;

    font-size: 19px;
}


.card {

    background: var(--card);

    border: 1px solid var(--border);

    border-radius: 16px;

    box-shadow: var(--shadow);
}


/* =========================
   SCORE
========================= */

.score-card {

    padding: 28px;
}


.score-layout {

    display: flex;

    align-items: center;

    gap: 45px;
}


.score-ring {

    width: 155px;

    height: 155px;

    border-radius: 50%;

    display: grid;

    place-items: center;

    flex-shrink: 0;

    background:
        conic-gradient(
            var(--accent)
            calc(var(--score) * 1%),
            var(--border) 0
        );

    position: relative;
}


.score-ring::before {

    content: "";

    position: absolute;

    inset: 11px;

    border-radius: 50%;

    background: var(--card);
}


.score-value {

    position: relative;

    text-align: center;
}


.score-number {

    display: block;

    font-size: 42px;

    line-height: 1;

    font-weight: 800;
}


.score-outof {

    color: var(--muted);

    font-size: 12px;
}


.dimensions {

    flex: 1;

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 15px 25px;
}


.dimension {

    font-size: 13px;
}


.dimension-head {

    display: flex;

    justify-content: space-between;

    margin-bottom: 5px;
}


.progress {

    height: 7px;

    border-radius: 99px;

    overflow: hidden;

    background: var(--border);
}


.progress i {

    display: block;

    height: 100%;

    border-radius: inherit;

    background:
        linear-gradient(
            90deg,
            var(--accent),
            var(--accent2)
        );
}


/* =========================
   STATS
========================= */

.stats {

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 12px;

    margin-top: 18px;
}


.stat {

    padding: 16px;

    background: var(--card);

    border: 1px solid var(--border);

    border-radius: 12px;
}


.stat-value {

    font-size: 24px;

    font-weight: 750;
}


.stat-label {

    color: var(--muted);

    font-size: 12px;

    margin-top: 3px;
}


/* =========================
   JOURNEY
========================= */

.journey {

    padding: 24px;

    overflow-x: auto;
}


.journey-track {

    min-width: 720px;

    display: flex;

    align-items: center;
}


.stage {

    flex: 1;

    text-align: center;

    position: relative;
}


.stage:not(:last-child)::after {

    content: "";

    position: absolute;

    top: 18px;

    left: 58%;

    right: -42%;

    height: 2px;

    background: var(--border);
}


.stage-dot {

    width: 36px;

    height: 36px;

    margin: auto;

    border-radius: 50%;

    display: grid;

    place-items: center;

    background: var(--card2);

    border: 2px solid var(--accent);

    position: relative;

    z-index: 2;

    font-size: 12px;

    font-weight: 800;
}


.stage-name {

    margin-top: 8px;

    font-size: 11px;

    font-weight: 700;

    letter-spacing: .04em;
}


.stage-desc {

    color: var(--muted);

    font-size: 10px;
}


/* =========================
   FINDINGS
========================= */

.finding-tools {

    display: flex;

    gap: 10px;

    margin-bottom: 13px;

    flex-wrap: wrap;
}


.finding-search {

    flex: 1;

    min-width: 220px;

    padding: 11px 13px;

    border: 1px solid var(--border);

    border-radius: 9px;

    background: var(--card);

    color: var(--text);

    outline: none;
}


.finding-search:focus {

    border-color: var(--accent);
}


.filter-btn {

    padding: 10px 13px;

    border-radius: 9px;

    border: 1px solid var(--border);

    background: var(--card);

    color: var(--text);

    cursor: pointer;
}


.filter-btn.active {

    background: var(--accent);

    color: white;

    border-color: var(--accent);
}


.finding {

    margin-bottom: 10px;

    overflow: hidden;
}


.finding summary {

    padding: 17px;

    cursor: pointer;

    list-style: none;
}


.finding summary::-webkit-details-marker {

    display: none;
}


.finding-title {

    display: flex;

    gap: 9px;

    align-items: flex-start;
}


.severity {

    color: white;

    padding: 3px 7px;

    border-radius: 5px;

    font-size: 10px;

    font-weight: 800;

    text-transform: uppercase;

    flex-shrink: 0;
}


.critical {

    background: #b3261e;
}


.high {

    background: #c2410c;
}


.medium {

    background: #a16207;
}


.low {

    background: #3f6212;
}


.finding-name {

    font-weight: 650;
}


.finding-meta {

    margin-top: 5px;

    color: var(--muted);

    font-size: 11px;
}


.finding-body {

    border-top: 1px solid var(--border);

    padding: 4px 18px 20px;
}


.finding-body h4 {

    margin: 16px 0 5px;

    color: var(--muted);

    text-transform: uppercase;

    letter-spacing: .05em;

    font-size: 11px;
}


.finding-body p {

    margin: 0;

    line-height: 1.55;

    font-size: 14px;
}


.finding-body ol {

    margin-top: 7px;

    padding-left: 22px;

    font-size: 14px;
}


.urls {

    word-break: break-all;

    color: var(--muted);

    font-size: 12px;
}


/* =========================
   AGENT REASONING & ROADMAP
========================= */

.reasoning-badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .04em;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: white;
}

.reasoning-card {
    padding: 24px;
}

.reasoning-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 20px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
    padding-bottom: 18px;
}

.bottleneck-badge {
    background: var(--card2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 14px;
    text-align: right;
    min-width: 140px;
}

.strategic-themes-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px;
}

.theme-card {
    background: var(--card2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
}

.roadmap-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 14px;
}

.phase-card {
    background: var(--card2);
    border: 1px solid var(--border);
    border-top: 3px solid var(--accent);
    border-radius: 10px;
    padding: 14px;
}

.phase-title {
    font-weight: 750;
    font-size: 13px;
    margin-bottom: 4px;
}

.phase-obj {
    color: var(--muted);
    font-size: 11px;
    margin-bottom: 10px;
    line-height: 1.4;
}

.phase-actions {
    margin: 0;
    padding-left: 18px;
    font-size: 12px;
    line-height: 1.5;
}

.reasoning-tag {
    display: inline-block;
    padding: 3px 8px;
    background: var(--card2);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 11px;
    color: var(--muted);
}


/* =========================
   ACTIONS
========================= */

.actions {

    display: flex;

    gap: 10px;

    flex-wrap: wrap;

    margin-top: 18px;
}


.action-btn {

    display: inline-block;

    padding: 10px 15px;

    border-radius: 9px;

    border: 1px solid var(--border);

    background: var(--card);

    color: var(--text);

    text-decoration: none;

    font-size: 13px;

    font-weight: 650;
}


.action-btn.primary {

    background: var(--accent);

    border-color: var(--accent);

    color: white;
}


/* =========================
   FOOTER
========================= */

.footer {

    text-align: center;

    color: var(--muted);

    font-size: 11px;

    margin-top: 45px;
}


/* =========================
   RESPONSIVE
========================= */

@media(max-width: 800px) {

    .score-layout {

        flex-direction: column;

        align-items: stretch;
    }

    .score-ring {

        margin: auto;
    }

    .dimensions {

        grid-template-columns: 1fr;
    }

    .stats {

        grid-template-columns:
            repeat(2, 1fr);
    }
}


@media(max-width: 600px) {

    .topbar {

        padding: 0 15px;
    }

    .container {

        padding:
            30px
            14px
            60px;
    }

    .hero h1 {

        font-size: 30px;
    }

    .form-row {

        flex-direction: column;
    }

    .audit-btn {

        padding: 13px;
    }

    .stats {

        grid-template-columns:
            1fr 1fr;
    }
}

</style>
</head>


<body>


<header class="topbar">

    <div class="brand">

        <div class="brand-mark">
            A
        </div>

        <span>
            AI Website Readiness Auditor
        </span>

    </div>


    <button
        class="theme-btn"
        onclick="toggleTheme()"
        id="themeButton"
        aria-label="Toggle dark mode"
        title="Toggle theme"
    >
        ⏾
    
    </button>

</header>



<main class="container">


<section class="hero">

    <h1>
        AI Website Readiness Auditor
    </h1>

    <p>
        Measure whether a website can be discovered, accessed,
        understood, extracted, trusted and represented by AI systems.
    </p>

</section>



<form
    class="audit-form"
    method="post"
>

    <label for="url">
        Website URL
    </label>


    <div class="form-row">

        <input
            id="url"
            class="url-input"
            name="url"
            type="url"
            placeholder="https://www.example.com"
            value="{{ url }}"
            required
        >


        <button
            class="audit-btn"
            type="submit"
        >
            Audit Website
        </button>

    </div>

</form>



{% if error %}

<div class="error">

    {{ error }}

</div>

{% endif %}



{% if report %}

{% set ai = report["ai_readiness"] %}
{% set summary = report["summary"] %}



<section class="dashboard">


<!-- =========================
     SCORE
========================= -->

<h2 class="section-title">
    AI Readiness
</h2>


<div class="card score-card">


    <div class="score-layout">


        <div
            class="score-ring"
            style="--score: {{ ai["overall"] if ai["overall"] is not none else 0 }}"
        >

            <div class="score-value">

                <span class="score-number">
                    {{ ai["overall"] if ai["overall"] is not none else "n/a" }}
                </span>

                <span class="score-outof">
                    {{ "out of 100" if ai["overall"] is not none else "not assessed" }}
                </span>

            </div>

        </div>



        <div class="dimensions">


        {% for name, value in ai["dimensions"].items() %}


            <div class="dimension">


                <div class="dimension-head">

                    <span>
                        {{ name }}
                    </span>


                    <b>

                    {% if value is none %}

                        n/a

                    {% else %}

                        {{ value }}

                    {% endif %}

                    </b>

                </div>


                <div class="progress">

                {% if value is not none %}

                    <i
                        style="width: {{ value }}%"
                    ></i>

                {% endif %}

                </div>


            </div>


        {% endfor %}


        </div>


    </div>


</div>



<!-- =========================
     STATS
========================= -->

<div class="stats">


    <div class="stat">

        <div class="stat-value">
            {{ summary["pages_crawled"] }}
        </div>

        <div class="stat-label">
            Pages crawled
        </div>

    </div>



    <div class="stat">

        <div class="stat-value">
            {{ summary["pages_rendered"] }}
        </div>

        <div class="stat-label">
            Pages rendered
        </div>

    </div>



    <div class="stat">

        <div class="stat-value">
            {{ summary["total_findings"] }}
        </div>

        <div class="stat-label">
            Findings
        </div>

    </div>



    <div class="stat">

        <div class="stat-value">
            {{ summary["runtime_seconds"] }}s
        </div>

        <div class="stat-label">
            Audit runtime
        </div>

    </div>


</div>



<!-- =========================
     JOURNEY
========================= -->

<h2 class="section-title">
    AI Discoverability Journey
</h2>


<div class="card journey">


<div class="journey-track">


{% for stage, desc in [

    ("DISCOVER", "Can AI find it?"),

    ("ACCESS", "Can AI reach it?"),

    ("UNDERSTAND", "Can AI understand it?"),

    ("EXTRACT", "Can AI extract facts?"),

    ("TRUST", "Can AI trust it?"),

    ("REPRESENT", "Can AI represent it?")

] %}


<div class="stage">


    <div class="stage-dot">

        {{ loop.index }}

    </div>


    <div class="stage-name">

        {{ stage }}

    </div>


    <div class="stage-desc">

        {{ desc }}

    </div>


</div>


{% endfor %}


</div>


</div>



<!-- =========================
     STRATEGIC REASONING & ROADMAP
========================= -->
{% if report.get("strategic_reasoning") %}
{% set sr = report["strategic_reasoning"] %}

<h2 class="section-title">
    Agent Reasoning & Strategic Roadmap
</h2>

<div class="card reasoning-card">

    <div class="reasoning-header">
        <div style="flex: 1; min-width: 280px;">
            <span class="reasoning-badge">Agent Synthesized</span>
            <h3 style="margin: 9px 0 6px; font-size: 17px;">Architectural Synthesis</h3>
            <p style="margin: 0; line-height: 1.6; font-size: 14px; color: var(--text);">
                {{ sr["executive_summary"] }}
            </p>
        </div>

        <div class="bottleneck-badge">
            <div style="font-size: 10px; color: var(--muted); text-transform: uppercase; font-weight: 700;">Primary Bottleneck</div>
            <div style="font-size: 16px; font-weight: 800; text-transform: uppercase; color: var(--accent); margin-top: 3px;">
                {{ sr["primary_bottleneck_stage"] }}
            </div>
        </div>
    </div>

    {% if sr.get("strategic_themes") %}
    <h4 style="margin: 22px 0 11px; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em;">Strategic Themes</h4>
    <div class="strategic-themes-grid">
        {% for theme in sr["strategic_themes"] %}
        <div class="theme-card">
            <b style="font-size: 13px; color: var(--text);">{{ theme["theme"] }}</b>
            <p style="margin: 5px 0 9px; font-size: 12px; color: var(--muted); line-height: 1.45;">{{ theme["diagnosis"] }}</p>
            <div style="font-size: 12px; border-left: 2px solid var(--accent); padding-left: 8px; line-height: 1.45;">
                <b style="color: var(--accent);">Fix:</b> {{ theme["strategic_recommendation"] }}
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {% if sr.get("remediation_roadmap") %}
    <h4 style="margin: 24px 0 11px; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em;">Phased Remediation Roadmap</h4>
    <div class="roadmap-grid">
        {% for phase in sr["remediation_roadmap"] %}
        <div class="phase-card">
            <div class="phase-title">{{ phase["phase"] }}</div>
            <div class="phase-obj">{{ phase["objective"] }}</div>
            <ul class="phase-actions">
                {% for action in phase["actions"] %}
                <li>{{ action }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endfor %}
    </div>
    {% endif %}

</div>

{% endif %}



<!-- =========================
     FINDINGS
========================= -->

<h2 class="section-title">
    Findings
</h2>



<div class="finding-tools">


    <input
        class="finding-search"
        id="findingSearch"
        placeholder="Search findings..."
        oninput="filterFindings()"
    >


    <button
        class="filter-btn active"
        onclick="setFilter('all', this)"
        type="button"
    >
        All
    </button>


    <button
        class="filter-btn"
        onclick="setFilter('critical', this)"
        type="button"
    >
        Critical
    </button>


    <button
        class="filter-btn"
        onclick="setFilter('high', this)"
        type="button"
    >
        High
    </button>


    <button
        class="filter-btn"
        onclick="setFilter('medium', this)"
        type="button"
    >
        Medium
    </button>


    <button
        class="filter-btn"
        onclick="setFilter('low', this)"
        type="button"
    >
        Low
    </button>


</div>



<div id="findingsContainer">


{% for f in report["findings"] %}


<details
    class="finding card"
    data-severity="{{ f["severity"] }}"
    data-search="
        {{ (
            f["title"]
            ~ " "
            ~ f["evidence"]
            ~ " "
            ~ f["impact"]
        )|lower }}
    "
>


<summary>


    <div class="finding-title">


        <span
            class="severity {{ f["severity"] }}"
        >
            {{ f["severity"] }}
        </span>


        <div>


            <div class="finding-name">

                {{ f["title"] }}

            </div>


            <div class="finding-meta">

                {{ f["id"] }}

                · Stage:
                {{ f["journey_stage"] or "-" }}

                · Priority:
                {{ f["suggested_action"]["priority"] }}

                · Confidence:
                {{ f["confidence"] }}

                {% if f.get("enhanced_by_reasoning") %}
                · <span class="reasoning-badge">Agent Reasoned</span>
                {% endif %}

            </div>


        </div>


    </div>


</summary>



<div class="finding-body">


    <h4>
        Evidence
    </h4>


    <p>
        {{ f["evidence"] }}
    </p>


    {% if f.get("reasoning") and f["reasoning"].get("root_cause_analysis") %}

    <h4>
        Grounded Root Cause
    </h4>

    <p>
        {{ f["reasoning"]["root_cause_analysis"] }}
    </p>

    {% endif %}


    <h4>
        Why it matters
    </h4>


    <p>
        {{ f["impact"] }}
    </p>


    {% if f.get("reasoning") and f["reasoning"].get("ai_agent_impact") %}

    <h4>
        Autonomous AI Agent Impact
    </h4>

    <p>
        {{ f["reasoning"]["ai_agent_impact"] }}
    </p>

    {% endif %}


    {% if f.get("reasoning") and f["reasoning"].get("remediation_phase") %}

    <div style="margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap;">
        <span class="reasoning-tag">{{ f["reasoning"]["remediation_phase"] }}</span>
        <span class="reasoning-tag">Effort: {{ f["reasoning"]["estimated_effort"]|upper }}</span>
    </div>

    {% endif %}


    <h4>
        Recommended fix
    </h4>


    <p>
        {{ f["suggested_action"]["summary"] }}
    </p>



    {% if f["suggested_action"]["steps"] %}


    <h4>
        Implementation steps
    </h4>


    <ol>


    {% for step in f["suggested_action"]["steps"] %}

        <li>
            {{ step }}
        </li>

    {% endfor %}


    </ol>


    {% endif %}



    {% if f["affected_urls"] %}


    <h4>
        Affected URLs
    </h4>


    <div class="urls">


        {% for affected_url in f["affected_urls"][:8] %}

            {{ affected_url }}<br>

        {% endfor %}


    </div>


    {% endif %}


</div>


</details>


{% endfor %}


</div>



<!-- =========================
     DOWNLOADS
========================= -->

<div class="actions">


    <a
        class="action-btn primary"
        href="/download/json/{{ report_token }}"
    >
        Download JSON Report
    </a>


    <a
        class="action-btn"
        href="/download/html/{{ report_token }}"
        target="_blank"
    >
        Open HTML Report
    </a>


</div>



</section>


{% endif %}



<div class="footer">

    AI Website Readiness Auditor ·
    Evidence-backed website analysis

</div>


</main>



<script>


/* =========================
   THEME
========================= */


function updateThemeButton() {

    const dark =
        document.documentElement
            .getAttribute("data-theme")
        === "dark";


    document.getElementById(
        "themeButton"
    ).textContent =
        dark ? "☀︎" : "⏾";

}


function toggleTheme() {

    const html =
        document.documentElement;


    const dark =
        html.getAttribute("data-theme")
        === "dark";


    if (dark) {

        html.removeAttribute(
            "data-theme"
        );

        localStorage.setItem(
            "aira-theme",
            "light"
        );

    } else {

        html.setAttribute(
            "data-theme",
            "dark"
        );

        localStorage.setItem(
            "aira-theme",
            "dark"
        );

    }


    updateThemeButton();

}


function loadTheme() {

    const saved =
        localStorage.getItem(
            "aira-theme"
        );


    if (saved === "dark") {

        document.documentElement
            .setAttribute(
                "data-theme",
                "dark"
            );

    }


    updateThemeButton();

}



/* =========================
   FINDING FILTERS
========================= */


let currentFilter = "all";


function setFilter(
    filter,
    button
) {

    currentFilter = filter;


    document
        .querySelectorAll(
            ".filter-btn"
        )
        .forEach(
            btn =>
                btn.classList.remove(
                    "active"
                )
        );


    button.classList.add(
        "active"
    );


    filterFindings();

}



function filterFindings() {

    const input =
        document.getElementById(
            "findingSearch"
        );


    const search =
        input
            ? input.value.toLowerCase()
            : "";


    document
        .querySelectorAll(
            ".finding"
        )
        .forEach(
            card => {


                const severity =
                    card.dataset.severity;


                const text =
                    card.dataset.search;


                const matchesSeverity =
                    currentFilter === "all"
                    ||
                    severity === currentFilter;


                const matchesSearch =
                    !search
                    ||
                    text.includes(
                        search
                    );


                card.style.display =
                    matchesSeverity
                    &&
                    matchesSearch
                        ? ""
                        : "none";

            }
        );

}



/* =========================
   INITIALIZE
========================= */


loadTheme();


</script>


</body>

</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():

    report = None
    error = None
    url = ""
    report_token = None

    if request.method == "POST":

        url = request.form.get(
            "url",
            ""
        ).strip()


        if not url:

            error = (
                "Please enter a website URL."
            )

        else:

            try:

                config = AuditConfig()


                report = run_audit(
                    url,
                    config,
                    include_evidence_model=False,
                )


                report_token = _store_report(report)


            except AuditError as exc:

                error = str(exc)


            except Exception as exc:

                error = (
                    f"Unexpected error: {exc}"
                )


    return render_template_string(
        HTML,
        report=report,
        error=error,
        url=url,
        report_token=report_token,
    )


@app.route("/download/json/<token>")
def download_json(token: str):
    """Serve one specific report, not whichever ran last."""
    report = _load_report(token)
    if report is None:
        return "Report not found. Run an audit and use the link on that page.", 404

    payload = json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")
    return send_file(
        io.BytesIO(payload),
        as_attachment=True,
        download_name="ai-readiness-report.json",
        mimetype="application/json",
    )


@app.route("/download/html/<token>")
def download_html(token: str):
    """Render the HTML view in memory - nothing is written to disk."""
    report = _load_report(token)
    if report is None:
        return "Report not found. Run an audit and use the link on that page.", 404

    return Response(render_html(report), mimetype="text/html")


@app.route("/healthz")
def healthz():
    """Liveness probe for a container platform."""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    import os

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        debug=False,
    )