"""Reasoning providers for interpreting and synthesizing audit evidence.

Architecture:
- ReasoningProvider (ABC): Base contract for enriching findings and synthesizing strategy.
- DeterministicReasoningProvider: Fast, 100% deterministic, zero-dependency, zero API key
  fallback that synthesizes root-cause analysis, AI agent impacts, and phased roadmaps
  directly from measured evidence.
- LLMReasoningProvider: Optional lightweight client using existing `httpx` (OpenAI, Gemini,
  or Anthropic compatible) that receives compact structured summaries and validates all
  outputs against evidence grounding guardrails with automatic fallback.
"""
from __future__ import annotations

import abc
import json
import logging
import os
from typing import Any

from aira.evidence import SiteEvidence
from aira.findings import Finding
from aira.reasoning.validation import extract_known_urls, sanitize_text_grounding

log = logging.getLogger("aira.reasoning")


class ReasoningProvider(abc.ABC):
    """Abstract interface for audit reasoning and strategic interpretation."""

    @abc.abstractmethod
    def enrich_finding(
        self,
        finding: Finding,
        evidence: SiteEvidence,
        related_findings: list[Finding],
    ) -> dict[str, Any]:
        """Produce grounded explanatory reasoning for a specific finding."""
        pass

    @abc.abstractmethod
    def synthesize_strategy(
        self,
        evidence: SiteEvidence,
        findings: list[Finding],
    ) -> dict[str, Any]:
        """Produce an overarching strategic diagnosis and phased remediation roadmap."""
        pass


class DeterministicReasoningProvider(ReasoningProvider):
    """Heuristic, grounded reasoning engine that operates deterministically on evidence."""

    # Stage-level AI system impacts
    STAGE_IMPACTS = {
        "discover": (
            "Autonomous crawlers and search agents cannot index or retrieve site resources, "
            "preventing the brand from appearing in AI knowledge bases or live retrieval queries."
        ),
        "access": (
            "AI agents encounter technical barriers (HTTP errors, client-side rendering hurdles, "
            "or excessive link depth), causing search engines and LLM agents to drop pages or "
            "substitute stale cached representations."
        ),
        "understand": (
            "Content lacks semantic structure (headings, meta tags, or sufficient body text), "
            "forcing language models to guess context or generate low-confidence summaries."
        ),
        "extract": (
            "Machine-readable structured data is missing or malformed, preventing AI agents "
            "from extracting discrete business entities, product specs, pricing, and operating facts."
        ),
        "trust": (
            "Entity verification signals and corroborating profiles are absent, reducing "
            "AI confidence in brand authority and increasing susceptibility to hallucinated competitors."
        ),
        "represent": (
            "Inconsistent facts across pages create contradictory training or retrieval signals, "
            "leading AI models to misrepresent core brand facts to end users."
        ),
    }

    PHASE_MAP = {
        "critical": "Phase 1: Immediate Access & Crawl Recovery (0-7 Days)",
        "high": "Phase 1: Immediate Access & Crawl Recovery (0-7 Days)",
        "medium": "Phase 2: Structured Knowledge & Semantic Architecture (7-21 Days)",
        "low": "Phase 3: Authority Corroboration & Context Enrichment (21-45 Days)",
    }

    EFFORT_MAP = {
        "robots_blocks_site": "low",
        "site_unreachable": "medium",
        "noindex_on_important_page": "low",
        "ai_crawler_blocked": "low",
        "missing_organization_identity": "low",
        "invalid_structured_data": "low",
        "missing_product_structured_data": "medium",
        "js_dependent_content": "high",
        "thin_important_page": "medium",
        "facts_in_images": "medium",
        "important_page_deep": "medium",
        "important_page_orphaned": "medium",
        "weak_navigation": "medium",
        "no_next_step": "low",
        "entity_name_conflict": "low",
        "contact_fact_conflict": "low",
    }

    def enrich_finding(
        self,
        finding: Finding,
        evidence: SiteEvidence,
        related_findings: list[Finding],
    ) -> dict[str, Any]:
        stage = finding.journey_stage or "discover"
        ai_impact = self.STAGE_IMPACTS.get(stage, "May impair autonomous AI agent understanding.")
        
        # Build concrete, grounded root cause explanation
        root_cause = self._diagnose_root_cause(finding, evidence)
        phase = self.PHASE_MAP.get(finding.severity, "Phase 2: Structured Knowledge (7-21 Days)")
        effort = self.EFFORT_MAP.get(finding.check_id, "medium")

        return {
            "root_cause_analysis": root_cause,
            "ai_agent_impact": ai_impact,
            "remediation_phase": phase,
            "estimated_effort": effort,
            "cross_finding_dependencies": [
                rf.id for rf in related_findings if rf.id != finding.id and rf.category == finding.category
            ][:3],
        }

    def _diagnose_root_cause(self, finding: Finding, evidence: SiteEvidence) -> str:
        cid = finding.check_id
        obs = finding.evidence.observation
        metrics = finding.evidence.metrics

        if cid == "robots_blocks_site":
            return f"The robots.txt file contains a Disallow rule covering all paths, completely prohibiting AI search crawlers."
        elif cid == "ai_crawler_blocked":
            blocked = metrics.get("blocked_agents", [])
            return f"Explicit disallow directives in robots.txt restrict specialized AI bot user-agents: {', '.join(blocked) or obs}."
        elif cid == "js_dependent_content":
            ratio = metrics.get("added_word_ratio")
            pct = f"{int(ratio * 100)}%" if ratio is not None else "a high percentage"
            return (
                f"Core textual content is generated dynamically via client-side JavaScript ({pct} added upon execution). "
                "Non-headless AI indexers parse only raw HTTP response HTML, rendering this content invisible."
            )
        elif cid in ("missing_organization_identity", "invalid_structured_data"):
            return (
                "Schema.org JSON-LD markup is absent or fails schema validation. AI engines rely on explicit "
                "JSON-LD nodes to ground entity graphs."
            )
        elif cid == "important_page_deep":
            depth = metrics.get("depth", 3)
            return (
                f"Page is located {depth} click-hops away from the homepage without direct cross-linking. "
                "AI web spiders operate under strict crawl budgets and frequently truncate traversal beyond depth 2."
            )
        elif cid == "thin_important_page":
            wc = metrics.get("word_count", 0)
            return (
                f"Page body has only {wc} words of extractable text, falling below semantic density thresholds "
                "needed for LLM retrieval and question-answering."
            )
        elif cid in ("entity_name_conflict", "contact_fact_conflict"):
            return (
                "Structured schema definitions diverge from visual copy on high-priority pages, "
                "generating conflicting token signals during AI entity alignment."
            )
        return (
            f"Observed measurement '{obs}' deviates from AI indexing and extraction standards."
        )

    def synthesize_strategy(
        self,
        evidence: SiteEvidence,
        findings: list[Finding],
    ) -> dict[str, Any]:
        """Construct comprehensive executive summary and structured 3-phase remediation plan."""
        total_pages = len(evidence.pages)
        rendered_pages = evidence.rendered_page_count
        findings_by_stage: dict[str, list[Finding]] = {}
        findings_by_sev: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for f in findings:
            stage = f.journey_stage or "discover"
            findings_by_stage.setdefault(stage, []).append(f)
            findings_by_sev[f.severity] = findings_by_sev.get(f.severity, 0) + 1

        # Identify primary architectural bottleneck
        most_affected_stage = max(
            findings_by_stage.keys(), key=lambda s: len(findings_by_stage[s]), default="none"
        ) if findings_by_stage else "none"

        # Formulate strategic themes
        themes: list[dict[str, str]] = []
        if any(f.journey_stage in ("discover", "access") for f in findings):
            themes.append({
                "theme": "Crawler Ingestion & Access Guardrails",
                "diagnosis": (
                    f"Crawlers face barriers reaching content. {len(findings_by_stage.get('discover', []))} "
                    f"discovery and {len(findings_by_stage.get('access', []))} access issues were identified."
                ),
                "strategic_recommendation": (
                    "Ensure robots.txt allows AI user-agents, provide a clean XML sitemap, and "
                    "serve critical content in static HTML rather than client-side execution."
                ),
            })
        if any(f.journey_stage in ("understand", "extract") for f in findings):
            themes.append({
                "theme": "Machine-Readable Knowledge & Semantic Graph",
                "diagnosis": (
                    f"Extractability is impaired. {len(findings_by_stage.get('extract', []))} structured "
                    "data/extraction gaps prevent discrete entity disambiguation."
                ),
                "strategic_recommendation": (
                    "Implement validated Schema.org Organization, WebSite, and Product JSON-LD entities. "
                    "Align structured attributes identically with on-page human-visible text."
                ),
            })
        if any(f.journey_stage in ("trust", "represent") for f in findings):
            themes.append({
                "theme": "Entity Authority & Contextual Retention",
                "diagnosis": (
                    "Cross-page entity consistency or external authority corroboration requires strengthening."
                ),
                "strategic_recommendation": (
                    "Link official social/corporate profiles via sameAs properties and provide clear "
                    "navigation trails and calls-to-action on interior landing pages."
                ),
            })

        # Phased roadmap
        p1_actions = [f"Fix {f.title} ({f.id})" for f in findings if f.severity in ("critical", "high")][:5]
        p2_actions = [f"Remediate {f.title} ({f.id})" for f in findings if f.severity == "medium"][:5]
        p3_actions = [f"Optimize {f.title} ({f.id})" for f in findings if f.severity == "low"][:5]

        roadmap = [
            {
                "phase": "Phase 1: Immediate Unblocking (Days 0-7)",
                "objective": "Eliminate crawl blockers, HTTP errors, and indexing restrictions.",
                "actions": p1_actions or ["Review robots.txt and HTTP status codes (currently clean)."],
            },
            {
                "phase": "Phase 2: Semantic Graph & Structured Data (Days 7-21)",
                "objective": "Publish valid Schema.org entities and resolve content depth/JS dependency.",
                "actions": p2_actions or ["Maintain structured schema hygiene."],
            },
            {
                "phase": "Phase 3: Authority, Corroboration & Next Steps (Days 21-45)",
                "objective": "Strengthen external entity corroboration and interior user/agent journey continuity.",
                "actions": p3_actions or ["Audit outbound entity citations and navigation paths."],
            },
        ]

        exec_summary = (
            f"Audit analyzed {total_pages} page(s) ({rendered_pages} rendered) on {evidence.site}. "
            f"Identified {len(findings)} total finding(s): {findings_by_sev['critical']} critical, "
            f"{findings_by_sev['high']} high, {findings_by_sev['medium']} medium, and {findings_by_sev['low']} low. "
            f"The primary architectural constraint is concentrated in the '{most_affected_stage.upper()}' stage. "
            "Executing the phased remediation plan will systematically upgrade AI discoverability and extraction fidelity."
        )

        return {
            "executive_summary": exec_summary,
            "primary_bottleneck_stage": most_affected_stage,
            "strategic_themes": themes,
            "remediation_roadmap": roadmap,
            "findings_by_stage_count": {s: len(fs) for s, fs in findings_by_stage.items()},
        }


class LLMReasoningProvider(ReasoningProvider):
    """Optional LLM provider using existing `httpx` to query OpenAI/Gemini/Anthropic compatible APIs.
    
    Strict constraints:
    - Never receives raw HTML; only compact structured evidence.
    - Grounded against observed URLs and metrics.
    - Gracefully falls back to DeterministicReasoningProvider upon timeout or error.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 6.0,
        fallback: ReasoningProvider | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("AIRA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (
            base_url
            or os.getenv("AIRA_LLM_BASE_URL")
            or "https://api.openai.com/v1/chat/completions"
        )
        self.model = model or os.getenv("AIRA_LLM_MODEL") or "gpt-4o-mini"
        self.timeout = float(os.getenv("AIRA_LLM_TIMEOUT", timeout))
        self.fallback = fallback or DeterministicReasoningProvider()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def enrich_finding(
        self,
        finding: Finding,
        evidence: SiteEvidence,
        related_findings: list[Finding],
    ) -> dict[str, Any]:
        if not self.is_configured():
            return self.fallback.enrich_finding(finding, evidence, related_findings)

        try:
            prompt = self._build_finding_prompt(finding, evidence)
            response_json = self._call_llm_json(prompt)
            known_urls = extract_known_urls(evidence, [finding])
            
            root_cause = sanitize_text_grounding(
                response_json.get("root_cause_analysis", ""), known_urls
            ) or self.fallback.enrich_finding(finding, evidence, related_findings)["root_cause_analysis"]
            
            ai_impact = sanitize_text_grounding(
                response_json.get("ai_agent_impact", ""), known_urls
            ) or self.fallback.enrich_finding(finding, evidence, related_findings)["ai_agent_impact"]

            return {
                "root_cause_analysis": root_cause,
                "ai_agent_impact": ai_impact,
                "remediation_phase": response_json.get(
                    "remediation_phase", "Phase 2: Structured Knowledge (7-21 Days)"
                ),
                "estimated_effort": response_json.get("estimated_effort", "medium"),
                "cross_finding_dependencies": [
                    rf.id for rf in related_findings if rf.id != finding.id
                ][:3],
            }
        except Exception as exc:
            log.warning("LLM reasoning for finding %s failed (%s); using deterministic fallback", finding.id, exc)
            return self.fallback.enrich_finding(finding, evidence, related_findings)

    def synthesize_strategy(
        self,
        evidence: SiteEvidence,
        findings: list[Finding],
    ) -> dict[str, Any]:
        if not self.is_configured():
            return self.fallback.synthesize_strategy(evidence, findings)

        try:
            prompt = self._build_strategy_prompt(evidence, findings)
            response_json = self._call_llm_json(prompt)
            known_urls = extract_known_urls(evidence, findings)

            exec_summary = sanitize_text_grounding(
                response_json.get("executive_summary", ""), known_urls
            )
            fallback_res = self.fallback.synthesize_strategy(evidence, findings)

            return {
                "executive_summary": exec_summary or fallback_res["executive_summary"],
                "primary_bottleneck_stage": response_json.get(
                    "primary_bottleneck_stage", fallback_res["primary_bottleneck_stage"]
                ),
                "strategic_themes": response_json.get(
                    "strategic_themes", fallback_res["strategic_themes"]
                ),
                "remediation_roadmap": response_json.get(
                    "remediation_roadmap", fallback_res["remediation_roadmap"]
                ),
                "findings_by_stage_count": fallback_res["findings_by_stage_count"],
            }
        except Exception as exc:
            log.warning("LLM strategy synthesis failed (%s); using deterministic fallback", exc)
            return self.fallback.synthesize_strategy(evidence, findings)

    def _call_llm_json(self, system_and_user_prompt: str) -> dict[str, Any]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert AI readiness auditor. You reason only about objective evidence "
                        "provided in the prompt. Return strictly valid JSON with no markdown formatting."
                    ),
                },
                {"role": "user", "content": system_and_user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.base_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

    def _build_finding_prompt(self, finding: Finding, evidence: SiteEvidence) -> str:
        compact_evidence = {
            "check_id": finding.check_id,
            "title": finding.title,
            "stage": finding.journey_stage,
            "severity": finding.severity,
            "observation": finding.evidence.observation,
            "metrics": finding.evidence.metrics,
            "url": finding.evidence.url,
        }
        return (
            f"Analyze this specific audit finding and provide grounded reasoning.\n"
            f"Site: {evidence.site}\n"
            f"Finding Data: {json.dumps(compact_evidence)}\n\n"
            "Return JSON with keys: 'root_cause_analysis', 'ai_agent_impact', 'remediation_phase', 'estimated_effort'."
        )

    def _build_strategy_prompt(self, evidence: SiteEvidence, findings: list[Finding]) -> str:
        compact_findings = [
            {
                "id": f.id,
                "title": f.title,
                "severity": f.severity,
                "stage": f.journey_stage,
                "check_id": f.check_id,
                "observation": f.evidence.observation,
            }
            for f in findings[:15]
        ]
        return (
            f"Synthesize the overarching strategic roadmap for {evidence.site}.\n"
            f"Pages audited: {len(evidence.pages)}.\n"
            f"Findings: {json.dumps(compact_findings)}\n\n"
            "Return JSON with keys: 'executive_summary', 'primary_bottleneck_stage', 'strategic_themes', 'remediation_roadmap'."
        )
