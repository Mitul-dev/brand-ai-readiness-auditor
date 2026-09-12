"""Optional single-file HTML renderer for a report.

Deliberately small: no build step, no framework, no external assets. It exists so
a non-expert can read the report; it is not part of the marketplace contract.
"""
from __future__ import annotations

import html
import json
from typing import Any

SEV_COLOR = {"critical": "#b3261e", "high": "#c2410c",
             "medium": "#a16207", "low": "#3f6212"}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1b1b1a;--mut:#6b6b66;--line:#e4e4e0}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#eeeeec;
--mut:#9a9a94;--line:#33332f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px;margin-bottom:24px}
.score{display:flex;gap:24px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:20px;flex-wrap:wrap}
.big{font-size:44px;font-weight:650;line-height:1}
.dims{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;flex:1;min-width:260px}
.dim{font-size:13px}.bar{height:6px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:#4b6bfb}
.counts{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.pill{font-size:12px;padding:4px 10px;border-radius:99px;border:1px solid var(--line);background:var(--card)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;
margin-bottom:10px;overflow:hidden}
summary{cursor:pointer;padding:14px 16px;list-style:none;display:flex;gap:10px;align-items:flex-start}
summary::-webkit-details-marker{display:none}
.sev{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
color:#fff;border-radius:5px;padding:3px 7px;white-space:nowrap;margin-top:1px}
.ttl{font-weight:550}.meta{color:var(--mut);font-size:12px;margin-top:3px}
.body{padding:0 16px 16px;border-top:1px solid var(--line);margin-top:2px}
.body h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.body p,.body li{margin:4px 0}code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto}
.urls{word-break:break-all;color:var(--mut);font-size:12px}
.empty{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:24px;text-align:center;color:var(--mut)}
"""


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def render_html(report: dict[str, Any]) -> str:
    ai = report.get("ai_readiness", {})
    s = report.get("summary", {})
    dims = []
    for label, value in (ai.get("dimensions") or {}).items():
        if value is None:
            dims.append(f'<div class="dim">{_esc(label)} <b>n/a</b>'
                        f'<div class="bar"></div></div>')
        else:
            dims.append(f'<div class="dim">{_esc(label)} <b>{value}</b>'
                        f'<div class="bar"><i style="width:{value}%"></i></div></div>')
    counts = "".join(
        f'<span class="pill">{k} {s.get(k, 0)}</span>'
        for k in ("critical", "high", "medium", "low"))

    cards = []
    for f in report.get("findings", []):
        sev = f.get("severity", "medium")
        td = f.get("technical_details", {})
        steps = "".join(f"<li>{_esc(x)}</li>"
                        for x in f.get("suggested_action", {}).get("steps", []))
        metrics = json.dumps(td.get("metrics", {}), indent=2)
        urls = ", ".join(f.get("affected_urls", [])[:8])
        cards.append(f"""
<details>
  <summary>
    <span class="sev" style="background:{SEV_COLOR.get(sev, '#666')}">{_esc(sev)}</span>
    <span><span class="ttl">{_esc(f.get('title'))}</span>
      <div class="meta">{_esc(f.get('id'))} &middot; {_esc(f.get('category'))}
      {'&middot; stage: ' + _esc(f.get('journey_stage')) if f.get('journey_stage') else ''}
      &middot; priority {_esc(f.get('suggested_action', {}).get('priority'))}
      &middot; confidence {_esc(f.get('confidence'))}</div></span>
  </summary>
  <div class="body">
    <h4>Problem</h4><p>{_esc(f.get('title'))}</p>
    <h4>Evidence</h4><p>{_esc(td.get('observation') or f.get('evidence'))}</p>
    {'<p class="meta">' + _esc(td.get('details')) + '</p>' if td.get('details') else ''}
    <h4>Metrics</h4><pre>{_esc(metrics)}</pre>
    <h4>Why it matters</h4><p>{_esc(f.get('impact'))}</p>
    <h4>Recommended fix</h4><p>{_esc(f.get('suggested_action', {}).get('summary'))}</p>
    <ol>{steps}</ol>
    <h4>Priority &amp; confidence</h4>
    <p class="meta">{_esc(f.get('priority_reason'))}<br>{_esc(f.get('confidence_reason'))}</p>
    {'<h4>Affected URLs</h4><p class="urls">' + _esc(urls) + '</p>' if urls else ''}
  </div>
</details>""")

    body = "".join(cards) or '<div class="empty">No findings: nothing in the ' \
                             'collected evidence met a check threshold.</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Readiness Report - {_esc(report.get('site'))}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>AI Readiness Report - {_esc(report.get('site'))}</h1>
<div class="sub">Audited {_esc(report.get('audited_at'))} &middot;
{_esc(s.get('pages_crawled'))} pages crawled &middot;
{_esc(s.get('pages_rendered'))} rendered &middot;
{_esc(s.get('runtime_seconds'))}s</div>
<div class="score"><div><div class="big">{
    "n/a" if ai.get("overall") is None else _esc(ai.get("overall"))}</div>
<div class="sub" style="margin:0">{
    "not assessed" if ai.get("overall") is None else "of 100"}</div></div>
<div class="dims">{''.join(dims)}</div></div>
<div class="counts"><span class="pill"><b>{_esc(s.get('total_findings'))}</b> findings</span>{counts}</div>
{body}
</div></body></html>"""
