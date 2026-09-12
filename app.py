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
<!DOCTYPE html>
<html class="dark" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>AI Website Readiness Auditor | Enterprise LLM &amp; Agentic SEO Intelligence</title>
<!-- Tailwind CSS v3 with forms & container queries -->
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: {
              50: '#eef2ff',
              100: '#e0e7ff',
              400: '#818cf8',
              500: '#6366f1',
              600: '#4f46e5',
              700: '#4338ca',
            },
            surface: {
              base: '#0B0F17',
              panel: '#111726',
              elevated: '#161F33',
              border: '#1E293B',
              borderSubtle: '#293548'
            }
          },
          fontFamily: {
            sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
            mono: ['JetBrains Mono', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', 'monospace']
          },
          animation: {
            'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            'spin-slow': 'spin 8s linear infinite',
            'scanline': 'scan 2.5s ease-in-out infinite alternate',
          },
          keyframes: {
            scan: {
              '0%': { transform: 'translateY(-100%)' },
              '100%': { transform: 'translateY(100%)' },
            }
          }
        }
      }
    };
  </script>
<!-- Google Font Preconnect & Fonts -->
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&amp;family=JetBrains+Mono:wght@400;500;600;700&amp;display=swap" rel="stylesheet"/>
<style data-purpose="custom-enhancements">
    body {
      font-family: 'Inter', sans-serif;
      background-color: #0B0F17;
      color: #E2E8F0;
    }
    .font-mono-digits {
      font-family: 'JetBrains Mono', monospace;
      font-feature-settings: "tnum" 1, "zero" 1;
    }
    .mesh-gradient-bg {
      background-image: 
        radial-gradient(at 15% 15%, rgba(99, 102, 241, 0.12) 0px, transparent 45%),
        radial-gradient(at 85% 20%, rgba(139, 92, 246, 0.10) 0px, transparent 40%),
        radial-gradient(at 50% 60%, rgba(16, 185, 129, 0.04) 0px, transparent 50%);
    }
    .custom-scroll::-webkit-scrollbar {
      width: 5px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: #0F172A;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: #334155;
      border-radius: 9999px;
    }
    .glow-indigo {
      box-shadow: 0 0 25px -4px rgba(99, 102, 241, 0.35);
    }
    .glass-card {
      background: rgba(17, 23, 38, 0.75);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
  </style>
</head>
<body class="min-h-screen mesh-gradient-bg antialiased selection:bg-indigo-500 selection:text-white flex flex-col justify-between">
<!-- BEGIN: TopNavigation -->
<header class="w-full border-b border-surface-border/80 sticky top-0 z-50 bg-[#0B0F17]/90 backdrop-blur-md">
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
<!-- Brand & Title -->
<div class="flex items-center gap-3.5">
<div class="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-indigo-600 to-purple-600 text-white font-black text-lg shadow-lg shadow-indigo-600/30">
<span class="tracking-tight">A</span>
<!-- Subtle corner tech notch -->
<div class="absolute -top-0.5 -right-0.5 w-2 h-2 bg-purple-300 rounded-full animate-ping opacity-60"></div>
<div class="absolute -top-0.5 -right-0.5 w-2 h-2 bg-purple-400 rounded-full"></div>
</div>
<div class="flex items-center gap-2">
<a class="font-semibold text-white tracking-tight text-base hover:text-indigo-300 transition-colors" href="#">
            AI Website Readiness Auditor
          </a>
</div>
</div>
<!-- Navigation Links -->
<nav class="hidden md:flex items-center gap-7 text-xs font-medium text-slate-300">
</nav>
<!-- System Health & Actions -->
<div class="flex items-center gap-4">
<!-- Theme & Control Icon Button -->
<button aria-label="Settings and options" class="w-9 h-9 flex items-center justify-center rounded-lg bg-surface-panel hover:bg-surface-elevated border border-surface-border text-slate-300 hover:text-white transition-colors" type="button" onclick="toggleTheme()">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewbox="0 0 24 24">
<path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>
</svg>
</button>
</div>
</div>
</header>
<!-- END: TopNavigation -->
<!-- BEGIN: MainContent -->
<main class="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-10 flex flex-col gap-8 justify-center main-container">
<!-- BEGIN: HeroHeaderSection -->
<section class="text-center max-w-3xl mx-auto space-y-3" data-purpose="hero-header">
<div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-medium mb-1">
<svg class="w-3.5 h-3.5 text-indigo-400 animate-spin-slow" fill="none" stroke="currentColor" viewbox="0 0 24 24">
<path d="M13 10V3L4 14h7v7l9-11h-7z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>
</svg>
<span>Generative Engine Optimization (GEO) &amp; Agent Readiness</span>
</div>
<h1 class="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight leading-tight">
        AI Website Readiness Auditor
      </h1>
<p class="text-sm sm:text-base text-slate-400 max-w-2xl mx-auto leading-relaxed">
        Measure whether a website can be discovered, accessed, understood, extracted, trusted and represented by modern AI systems &amp; autonomous agents.
      </p>
</section>
<!-- END: HeroHeaderSection -->
<!-- BEGIN: AuditInputBox -->
<section class="w-full" data-purpose="audit-input-form">
<div class="glass-card rounded-2xl p-3 sm:p-4 shadow-2xl relative group focus-within:border-indigo-500/60 transition-all duration-300">
<form class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 audit-form" method="POST">
<!-- Protocol & Target URL Field -->
<div class="relative flex-1 flex items-center bg-slate-950/70 rounded-xl border border-slate-800 group-hover:border-slate-700/90 focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-500/20 transition-all px-3 py-2.5">
<!-- Globe Icon -->
<div class="text-slate-500 mr-2.5 flex items-center">
<svg class="w-5 h-5 text-indigo-400/90" fill="none" stroke="currentColor" viewbox="0 0 24 24">
<path d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>
</svg>
</div>
<!-- Protocol Badge -->
<span class="text-xs font-mono font-medium text-slate-400 bg-slate-800/80 px-2 py-1 rounded mr-2 hidden sm:inline-block border border-slate-700/50">
              HTTPS
            </span>
<!-- Actual Input Element -->
<input aria-label="Target Website URL" name="url" class="bg-transparent text-sm sm:text-base font-mono text-white placeholder-slate-500 focus:outline-none w-full border-none p-0 focus:ring-0 selection:bg-indigo-600 url-input" placeholder="https://example.com" type="url" value="{{ url }}" required/>
<!-- Clear/Action Button -->
<button aria-label="Clear input" class="text-slate-500 hover:text-slate-300 p-1" type="button" onclick="document.querySelector('.url-input').value=''">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewbox="0 0 24 24">
<path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>
</svg>
</button>
</div>
<!-- Submit / Running Audit Button -->
<button class="audit-btn flex items-center justify-center gap-2.5 px-7 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-500 hover:to-indigo-600 text-white font-semibold text-sm transition-all duration-200 glow-indigo shrink-0 active:scale-[0.98]" id="audit-action-button" type="submit">
<svg class="animate-spin h-4 w-4 text-white hidden spinner-icon" fill="none" viewbox="0 0 24 24">
<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
<path class="opacity-75" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" fill="currentColor"></path>
</svg>
<span class="btn-text">Audit Website</span>
</button>
</form>
</div>
</section>
<!-- END: AuditInputBox -->

{% if error %}
<section class="w-full error-section">
    <div class="glass-card rounded-2xl p-5 border border-red-500/30 bg-red-900/10">
        <div class="flex items-start gap-3 text-red-400">
            <svg class="w-5 h-5 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <p class="text-sm">{{ error }}</p>
        </div>
    </div>
</section>
{% endif %}

<!-- BEGIN: LiveAuditConsole -->
<section class="w-full" id="loadingPanel" style="display: none;" aria-live="polite">
<div class="glass-card rounded-2xl border border-surface-border overflow-hidden shadow-2xl relative">
<!-- Top Status Subheader Bar -->
<div class="bg-surface-elevated/80 border-b border-surface-border px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 text-xs">
<!-- Current Target & Pulse -->
<div class="flex items-center gap-2.5">
<div class="relative flex h-2.5 w-2.5">
<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500"></span>
</div>
<div class="flex items-center gap-1.5 font-mono">
<span class="text-slate-400 uppercase tracking-widest text-[11px]">AUDITING</span>
<span class="text-white font-semibold tracking-wide" id="loadingDomain"></span>
</div>
</div>
</div>
<!-- Center Counter Display -->
<div class="p-8 sm:p-10 flex flex-col items-center justify-center text-center relative overflow-hidden bg-gradient-to-b from-[#111726]/60 to-[#0B0F17]/90">
<!-- Ambient Glow behind digital timer -->
<div class="absolute w-72 h-36 bg-indigo-600/15 rounded-full blur-3xl pointer-events-none -top-6"></div>
<p class="text-xs uppercase tracking-[0.25em] text-slate-400 font-semibold mb-2 flex items-center justify-center gap-1.5 w-full">
<svg class="w-3.5 h-3.5 text-indigo-400 animate-pulse" fill="none" stroke="currentColor" viewbox="0 0 24 24">
<path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>
</svg>
            Elapsed Execution Time
          </p>
<!-- Large High-Fidelity Monospace Timer -->
<div id="loadingTimer" class="font-mono-digits text-6xl sm:text-7xl font-bold tracking-tight text-white mb-2 filter drop-shadow-[0_4px_16px_rgba(99,102,241,0.3)]">
            00:00
          </div>
<!-- Current Stage Status with Animated Ellipsis -->
<div class="flex items-center justify-center gap-2 text-indigo-400 font-medium text-sm sm:text-base mt-2 w-full">
<span>Crawling and analyzing website</span>
<div class="flex gap-1 items-center">
<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce"></span>
<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce [animation-delay:0.2s]"></span>
<span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce [animation-delay:0.4s]"></span>
</div>
</div>
</div>
</div>
</section>
<!-- END: LiveAuditConsole -->

{% if report %}
{% set ai = report["ai_readiness"] %}
{% set summary = report["summary"] %}

<!-- BEGIN: Results Dashboard -->
<section class="w-full dashboard-section">
    <div class="text-center mb-8">
        <p class="text-slate-400 text-sm">
            Audit completed in <span class="font-mono text-indigo-400 font-semibold">{{ "%02d:%02d"|format((summary["runtime_seconds"]|int) // 60, (summary["runtime_seconds"]|int) % 60) }}</span>
        </p>
    </div>

    <!-- Overall Score Card -->
    <div class="glass-card rounded-2xl p-6 sm:p-8 mb-8 border border-surface-border">
        <div class="flex flex-col md:flex-row items-center gap-10">
            <!-- Score Ring (Vanilla CSS equivalent converted to Tailwind) -->
            <div class="relative w-40 h-40 rounded-full flex items-center justify-center shrink-0"
                 style="background: conic-gradient(#6366f1 {{ ai['overall'] if ai['overall'] is not none else 0 }}%, #1E293B 0);">
                <div class="absolute inset-2 rounded-full bg-surface-panel flex flex-col items-center justify-center">
                    <span class="text-4xl font-bold text-white">{{ ai["overall"] if ai["overall"] is not none else "n/a" }}</span>
                    <span class="text-xs text-slate-400">out of 100</span>
                </div>
            </div>

            <!-- Dimensions -->
            <div class="flex-1 w-full grid grid-cols-1 sm:grid-cols-2 gap-4">
                {% for name, value in ai["dimensions"].items() %}
                <div class="bg-slate-900/50 rounded-lg p-4 border border-slate-800">
                    <div class="flex justify-between text-sm mb-2">
                        <span class="text-slate-300 font-medium">{{ name }}</span>
                        <span class="text-indigo-400 font-bold">{% if value is none %}n/a{% else %}{{ value }}{% endif %}</span>
                    </div>
                    <div class="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        {% if value is not none %}
                        <div class="h-full bg-indigo-500 rounded-full" style="width: {{ value }}%;"></div>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <!-- Stats Grid -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div class="glass-card rounded-xl p-4 border border-surface-border text-center">
            <div class="text-2xl font-mono text-white mb-1">{{ summary["pages_crawled"] }}</div>
            <div class="text-xs text-slate-400 uppercase tracking-wide">Pages Crawled</div>
        </div>
        <div class="glass-card rounded-xl p-4 border border-surface-border text-center">
            <div class="text-2xl font-mono text-white mb-1">{{ summary["pages_rendered"] }}</div>
            <div class="text-xs text-slate-400 uppercase tracking-wide">Pages Rendered</div>
        </div>
        <div class="glass-card rounded-xl p-4 border border-surface-border text-center">
            <div class="text-2xl font-mono text-white mb-1">{{ summary["total_findings"] }}</div>
            <div class="text-xs text-slate-400 uppercase tracking-wide">Total Findings</div>
        </div>
        <div class="glass-card rounded-xl p-4 border border-surface-border text-center flex gap-3 justify-center">
            <div class="text-center">
                <div class="text-xl font-mono text-red-400 mb-1">{{ summary["high"] }}</div>
                <div class="text-[10px] text-slate-400 uppercase">High</div>
            </div>
            <div class="text-center">
                <div class="text-xl font-mono text-amber-400 mb-1">{{ summary["medium"] }}</div>
                <div class="text-[10px] text-slate-400 uppercase">Med</div>
            </div>
            <div class="text-center">
                <div class="text-xl font-mono text-indigo-400 mb-1">{{ summary["low"] }}</div>
                <div class="text-[10px] text-slate-400 uppercase">Low</div>
            </div>
        </div>
    </div>

    <!-- Findings -->
    {% if report["findings"] %}
    <h3 class="text-xl font-bold text-white mb-4 mt-8 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-indigo-500"></span>
        Actionable Findings
    </h3>
    <div class="space-y-4">
        {% for finding in report["findings"] %}
        <div class="glass-card rounded-xl p-5 border border-surface-border relative overflow-hidden group hover:border-indigo-500/30 transition-colors">
            <!-- Severity indicator line -->
            <div class="absolute left-0 top-0 bottom-0 w-1 {% if finding["severity"] == 'critical' or finding["severity"] == 'high' %}bg-red-500{% elif finding["severity"] == 'medium' %}bg-amber-500{% else %}bg-indigo-500{% endif %}"></div>
            
            <div class="pl-2">
                <div class="flex flex-wrap items-center gap-3 mb-2">
                    <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider
                        {% if finding["severity"] == 'critical' or finding["severity"] == 'high' %}bg-red-500/10 text-red-400 border border-red-500/20
                        {% elif finding["severity"] == 'medium' %}bg-amber-500/10 text-amber-400 border border-amber-500/20
                        {% else %}bg-indigo-500/10 text-indigo-400 border border-indigo-500/20{% endif %}">
                        {{ finding["severity"] }}
                    </span>
                    <span class="text-slate-300 font-semibold">{{ finding["title"] }}</span>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
                        <div class="text-xs text-slate-500 font-medium uppercase mb-1">Evidence</div>
                        <div class="text-sm text-slate-300 font-mono">{{ finding["evidence"] }}</div>
                    </div>
                    <div class="bg-indigo-950/20 rounded-lg p-3 border border-indigo-500/20">
                        <div class="text-xs text-indigo-400/70 font-medium uppercase mb-1">Recommendation</div>
                        <div class="text-sm text-indigo-200">{{ finding["suggested_action"]["summary"] }}</div>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <!-- Downloads -->
    <div class="mt-12 flex justify-center gap-4">
        <a href="/download/json/{{ report_token }}" class="px-6 py-2.5 rounded-lg bg-surface-panel hover:bg-surface-elevated border border-surface-border text-slate-300 text-sm font-medium transition-colors flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
            Raw JSON
        </a>
        <a href="/download/html/{{ report_token }}" class="px-6 py-2.5 rounded-lg bg-surface-panel hover:bg-surface-elevated border border-surface-border text-slate-300 text-sm font-medium transition-colors flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
            HTML View
        </a>
    </div>

</section>
<!-- END: Results Dashboard -->
{% endif %}

</main>
<!-- END: MainContent -->
<!-- BEGIN: PageFooter -->
<footer class="w-full border-t border-surface-border/60 py-6 text-xs text-slate-500">
<div class="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
<div class="flex items-center gap-3">
<span class="font-medium text-slate-400">AI Website Readiness Auditor</span>
<span>•</span>
<span>Evidence-backed website analysis</span>
</div>
</div>
</footer>
<!-- END: PageFooter -->

<script>
// Light/Dark Theme logic
function toggleTheme() {
    const html = document.documentElement;
    if (html.classList.contains('dark')) {
        html.classList.remove('dark');
        localStorage.setItem('theme', 'light');
    } else {
        html.classList.add('dark');
        localStorage.setItem('theme', 'dark');
    }
}
// Load theme on start
if (localStorage.theme === 'light') {
    document.documentElement.classList.remove('dark');
} else {
    document.documentElement.classList.add('dark');
}

// Intercept form submission
let timerInterval = null;

document.addEventListener('submit', async function(e) {
    if (!e.target.matches('.audit-form')) return;
    
    e.preventDefault();
    const form = e.target;
    
    if (form.dataset.submitting) return;
    form.dataset.submitting = 'true';
    
    const btn = form.querySelector('.audit-btn');
    const btnText = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.spinner-icon');
    
    btn.disabled = true;
    btn.style.opacity = '0.7';
    btn.style.cursor = 'not-allowed';
    btnText.innerText = 'Auditing...';
    spinner.classList.remove('hidden');
    
    // Hide existing elements
    const dash = document.querySelector('.dashboard-section');
    if (dash) dash.style.display = 'none';
    const err = document.querySelector('.error-section');
    if (err) err.style.display = 'none';
    
    // Show loading
    const loading = document.getElementById('loadingPanel');
    loading.style.display = 'block';
    
    try {
        const urlVal = form.querySelector('.url-input').value;
        const url = new URL(urlVal);
        document.getElementById('loadingDomain').innerText = url.hostname;
    } catch(err) {
        document.getElementById('loadingDomain').innerText = form.querySelector('.url-input').value;
    }
    
    const timerEl = document.getElementById('loadingTimer');
    timerEl.innerText = '00:00';
    let start = Date.now();
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        let elapsed = Math.floor((Date.now() - start) / 1000);
        let m = String(Math.floor(elapsed / 60)).padStart(2, '0');
        let s = String(elapsed % 60).padStart(2, '0');
        timerEl.innerText = `${m}:${s}`;
    }, 1000);
    
    try {
        const formData = new FormData(form);
        const response = await fetch('/', {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'fetch' }
        });
        
        const html = await response.text();
        
        if (!response.ok) {
            throw new Error('Server returned ' + response.status + ': ' + html.substring(0, 200));
        }
        
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        const newContainer = doc.querySelector('.main-container');
        if (!newContainer) {
            throw new Error('Server returned an unexpected response.');
        }
        
        // Update the main container
        document.querySelector('.main-container').innerHTML = newContainer.innerHTML;
        
        // Timer stops because the container is replaced, but we should clear the interval
        clearInterval(timerInterval);
        
    } catch (error) {
        console.error('Audit fetch error:', error);
        clearInterval(timerInterval);
        form.dataset.submitting = '';
        btn.disabled = false;
        btn.style.opacity = '';
        btn.style.cursor = 'pointer';
        btnText.innerText = 'Audit Website';
        spinner.classList.add('hidden');
        loading.style.display = 'none';
        
        // Show an error with the actual message
        const msg = error.message || 'Network error: Failed to reach the audit server.';
        let errEl = document.querySelector('.error-section');
        if (!errEl) {
            errEl = document.createElement('section');
            errEl.className = 'w-full error-section';
            errEl.innerHTML = `
            <div class="glass-card rounded-2xl p-5 border border-red-500/30 bg-red-900/10">
                <div class="flex items-start gap-3 text-red-400">
                    <p class="text-sm"></p>
                </div>
            </div>`;
            form.closest('section').insertAdjacentElement('afterend', errEl);
        }
        errEl.querySelector('p').innerText = msg;
        errEl.style.display = 'block';
    }
});
</script>
</body></html>

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

                config = AuditConfig(
                    max_pages=10,
                    max_depth=2,
                    max_rendered_pages=3,
                    total_crawl_budget_s=60.0,
                    render_budget_s=30.0,
                )

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