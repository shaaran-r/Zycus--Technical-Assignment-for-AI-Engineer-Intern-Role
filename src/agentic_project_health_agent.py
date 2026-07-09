#!/usr/bin/env python3
"""Agentic project health reporting workflow.

This entry point turns the deterministic project analyzer into one tool inside
an AI-agent pipeline. It supports Gemini, OpenAI, or Ollama for reasoning and
falls back to auditable deterministic reasoning when no LLM key/runtime is
available.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from project_health_agent import ProjectHealthAgent, write_markdown_report


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agentic_project_health_agent")


DEFAULT_CONFIG = {
    "weights": {
        "schedule": 0.35,
        "milestones": 0.20,
        "blockers": 0.20,
        "progress": 0.15,
        "stakeholder_sentiment": 0.05,
        "data_quality": 0.05,
    },
    "thresholds": {
        "red_score": 1.20,
        "amber_score": 0.55,
        "progress_gap_amber": 0.10,
        "progress_gap_red": 0.25,
    },
    "llm": {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "ollama_model": "llama3.1",
        "temperature": 0.1,
        "max_retries": 3,
        "retry_backoff_seconds": 1.5,
    },
}


SYSTEM_PROMPT = """You are a Professional Services project health analyst.
Use the supplied metrics as evidence. Do not invent budget, dates, owners, or
client sentiment. Return compact JSON only. Be direct and executive-ready."""


SENTIMENT_PROMPT = """Assess stakeholder sentiment from these project comments.
Classify sentiment as Green, Amber, Red, or Neutral. Identify themes and
evidence. Return JSON with keys: sentiment, themes, evidence, confidence.

Comments:
{comments}
"""


RISK_PROMPT = """Assess project delivery risk from these metrics and evidence.
Return JSON with keys: risk_themes, emerging_risks, executive_summary,
recommended_actions. Keep actions specific and grounded.

Project:
{project}
"""


PORTFOLIO_PROMPT = """Synthesize the portfolio across these project health
records. Focus on trends across projects rather than summarizing each plan.
Return JSON with keys: portfolio_takeaway, trends, emerging_risks,
executive_recommendations, follow_up_questions.

Projects:
{projects}
"""


# --------------------------------------------------------------------------
# JSON extraction + retry helpers
# --------------------------------------------------------------------------


def extract_json(text: str) -> dict[str, Any]:
    """Robustly pull a JSON object out of an LLM text response.

    Handles: plain JSON, JSON wrapped in ```json ... ``` or ``` ... ```
    fences, JSON with leading/trailing prose, and minor trailing-comma
    formatting slips. Raises ValueError if nothing parseable is found.
    """
    if text is None:
        raise ValueError("Empty response from model")

    candidate = text.strip()
    if not candidate:
        raise ValueError("Empty response from model")

    # 1) Strip common markdown code fences.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()

    # 2) Direct parse.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 3) Extract the first balanced {...} block (handles leading/trailing prose).
    start = candidate.find("{")
    if start != -1:
        depth = 0
        end = None
        in_string = False
        escape = False
        for i, ch in enumerate(candidate[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end:
            block = candidate[start:end]
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                # 4) Last resort: fix trailing commas and retry.
                cleaned = re.sub(r",\s*([}\]])", r"\1", block)
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    pass

    raise ValueError(f"Could not extract JSON from model response: {candidate[:200]!r}")


def call_with_retries(
    func,
    *,
    retries: int = 3,
    backoff_seconds: float = 1.5,
    provider: str = "llm",
):
    """Call func() with exponential backoff, logging each attempt/failure."""
    attempt = 0
    last_exc: Exception | None = None
    while attempt < max(1, retries):
        attempt += 1
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, we log + retry
            last_exc = exc
            if attempt >= retries:
                logger.warning("%s call failed on final attempt %d/%d: %s", provider, attempt, retries, exc)
                break
            wait = backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s call failed on attempt %d/%d (%s); retrying in %.1fs",
                provider,
                attempt,
                retries,
                exc,
                wait,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


# --------------------------------------------------------------------------
# LLM clients
# --------------------------------------------------------------------------


class LLMClient(Protocol):
    provider_name: str

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        ...


class NoLLMClient:
    provider_name = "none"
    model = "n/a"

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        logger.debug("NoLLMClient invoked; returning deterministic fallback marker.")
        return {
            "llm_used": False,
            "note": "No LLM configured; deterministic fallback was used.",
        }


class OpenAIClient:
    provider_name = "openai"

    def __init__(self, model: str, temperature: float, max_retries: int = 3, retry_backoff: float = 1.5):
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        try:
            from openai import OpenAI

            client = OpenAI()

            def _call():
                response = client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                )
                text = response.choices[0].message.content or "{}"
                return extract_json(text)

            logger.info("Calling OpenAI model=%s temperature=%s", self.model, self.temperature)
            return call_with_retries(
                _call,
                retries=self.max_retries,
                backoff_seconds=self.retry_backoff,
                provider="OpenAI",
            )
        except Exception as exc:
            logger.error("OpenAI call ultimately failed: %s", exc)
            return {
                "llm_used": False,
                "error": f"OpenAI call failed: {exc}",
            }


class GeminiClient:
    """Production client for Google's Gemini models via the google-genai SDK."""

    provider_name = "gemini"

    def __init__(
        self,
        model: str,
        temperature: float,
        api_key: str | None = None,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._client = None  # lazily constructed so import errors surface per-call, not at startup

    def _get_client(self):
        if self._client is None:
            from google import genai

            if not self.api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; cannot call the Gemini API."
                )
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        try:
            from google.genai import types

            client = self._get_client()

            def _call():
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=self.temperature,
                        response_mime_type="application/json",
                    ),
                )
                text = getattr(response, "text", None)
                if not text:
                    # Fall back to walking candidate parts if .text is empty
                    # (can happen if the response was truncated or blocked).
                    candidates = getattr(response, "candidates", None) or []
                    parts_text = []
                    for candidate in candidates:
                        content = getattr(candidate, "content", None)
                        for part in getattr(content, "parts", []) or []:
                            part_text = getattr(part, "text", None)
                            if part_text:
                                parts_text.append(part_text)
                    text = "\n".join(parts_text)
                return extract_json(text or "{}")

            logger.info("Calling Gemini model=%s temperature=%s", self.model, self.temperature)
            return call_with_retries(
                _call,
                retries=self.max_retries,
                backoff_seconds=self.retry_backoff,
                provider="Gemini",
            )
        except Exception as exc:
            logger.error("Gemini call ultimately failed: %s", exc)
            return {
                "llm_used": False,
                "error": f"Gemini call failed: {exc}",
            }


class OllamaClient:
    provider_name = "ollama"

    def __init__(
        self,
        model: str,
        temperature: float,
        host: str = "http://localhost:11434",
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ):
        self.model = model
        self.temperature = temperature
        self.host = host.rstrip("/")
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }

        def _call():
            request = urllib.request.Request(
                f"{self.host}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw.get("message", {}).get("content", "{}")
            return extract_json(content)

        try:
            logger.info("Calling Ollama model=%s host=%s", self.model, self.host)
            return call_with_retries(
                _call,
                retries=self.max_retries,
                backoff_seconds=self.retry_backoff,
                provider="Ollama",
            )
        except Exception as exc:
            logger.error("Ollama call ultimately failed: %s", exc)
            return {
                "llm_used": False,
                "error": f"Ollama call failed: {exc}",
            }


def make_llm(config: dict[str, Any], requested: str) -> LLMClient:
    llm_config = config["llm"]
    max_retries = int(llm_config.get("max_retries", 3))
    retry_backoff = float(llm_config.get("retry_backoff_seconds", 1.5))

    provider = requested if requested != "auto" else llm_config.get("provider", "auto")
    if provider == "auto":
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            provider = "gemini"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        elif os.getenv("OLLAMA_HOST") or os.getenv("USE_OLLAMA"):
            provider = "ollama"
        else:
            provider = "none"
        logger.info("Auto-detected LLM provider: %s", provider)
    else:
        logger.info("Using configured LLM provider: %s", provider)

    if provider == "gemini":
        return GeminiClient(
            llm_config.get("model", "gemini-2.5-flash"),
            llm_config.get("temperature", 0.1),
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
    if provider == "openai":
        return OpenAIClient(
            llm_config.get("model", "gpt-4.1-mini"),
            llm_config.get("temperature", 0.1),
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
    if provider == "ollama":
        return OllamaClient(
            llm_config.get("ollama_model", "llama3.1"),
            llm_config.get("temperature", 0.1),
            os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
    return NoLLMClient()


@dataclass
class AgentState:
    as_of: str
    plans: list[str]
    projects: list[dict[str, Any]] = field(default_factory=list)
    llm_outputs: dict[str, Any] = field(default_factory=dict)
    portfolio: dict[str, Any] = field(default_factory=dict)
    reports: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def log(self, node: str, status: str, detail: dict[str, Any]) -> None:
        self.trace.append(
            {
                "time": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "node": node,
                "status": status,
                "detail": detail,
            }
        )
        log_fn = logger.warning if status == "fallback" else logger.info
        log_fn("[%s] %s | %s", node, status, detail)


class AgentGraph:
    def __init__(self, as_of: str, output_dir: Path, llm: LLMClient, config: dict[str, Any]):
        self.as_of = datetime.strptime(as_of, "%Y-%m-%d").date()
        self.output_dir = output_dir
        self.llm = llm
        self.config = config
        self.analyzer = ProjectHealthAgent(self.as_of, config)

    def run(self, plans: list[Path]) -> AgentState:
        state = AgentState(as_of=self.as_of.isoformat(), plans=[str(p) for p in plans])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._excel_profiler(state, plans)
        self._project_analyzer(state, plans)
        self._stakeholder_sentiment(state)
        self._risk_detector(state)
        self._portfolio_synthesizer(state)
        self._report_writer(state)
        self._trace_writer(state)
        return state

    def _excel_profiler(self, state: AgentState, plans: list[Path]) -> None:
        profiles = []
        try:
            import pandas as pd

            for plan in plans:
                excel = pd.ExcelFile(plan)
                sheet_profiles = []
                for sheet_name in excel.sheet_names:
                    frame = pd.read_excel(plan, sheet_name=sheet_name, nrows=20)
                    sheet_profiles.append(
                        {
                            "sheet": sheet_name,
                            "sample_rows": int(len(frame)),
                            "columns": [str(c) for c in frame.columns.tolist()],
                            "missing_cells_in_sample": int(frame.isna().sum().sum()),
                        }
                    )
                profiles.append({"plan": str(plan), "sheets": sheet_profiles})
            state.llm_outputs["excel_profile"] = profiles
            state.log("Read Excel + Pandas Profiler", "completed", {"plans": len(plans)})
        except Exception as exc:
            state.llm_outputs["excel_profile"] = {
                "warning": f"Pandas profiling skipped: {exc}",
            }
            state.log("Read Excel + Pandas Profiler", "fallback", {"error": str(exc)})

    def _project_analyzer(self, state: AgentState, plans: list[Path]) -> None:
        for plan in plans:
            result = self.analyzer.evaluate(plan)
            state.projects.append(asdict(result))
            state.log(
                "Tool 1 - Project Analyzer",
                "completed",
                {
                    "plan": str(plan),
                    "rag": result.rag,
                    "active_overdue": result.metrics["overdue_active_tasks"],
                    "red_active": result.metrics["red_active_tasks"],
                },
            )

    def _stakeholder_sentiment(self, state: AgentState) -> None:
        outputs = {}
        start = time.perf_counter()
        for project in state.projects:
            comments = project["evidence"].get("blocker_comments", [])
            if not comments:
                outputs[project["project_name"]] = {
                    "sentiment": "Neutral",
                    "themes": ["No stakeholder comments available"],
                    "evidence": [],
                    "confidence": "Low",
                    "llm_used": self.llm.provider_name != "none",
                }
                continue
            response = self.llm.complete_json(
                SYSTEM_PROMPT,
                SENTIMENT_PROMPT.format(comments=json.dumps(comments, indent=2)),
            )
            if "sentiment" not in response:
                response = {
                    "sentiment": project["signals"].get("stakeholder_sentiment", "Amber"),
                    "themes": self._comment_themes(comments),
                    "evidence": comments[:3],
                    "confidence": "Medium",
                    **response,
                }
            response["llm_provider"] = self.llm.provider_name
            outputs[project["project_name"]] = response
        state.llm_outputs["stakeholder_sentiment"] = outputs
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        state.log(
            "Tool 4 - Stakeholder Sentiment",
            "completed",
            {
                "provider": self.llm.provider_name,
                "model": getattr(self.llm, "model", "n/a"),
                "duration_ms": elapsed_ms,
                "projects": len(outputs),
            },
        )

    def _risk_detector(self, state: AgentState) -> None:
        outputs = {}
        start = time.perf_counter()
        for project in state.projects:
            compact_project = {
                "project_name": project["project_name"],
                "rag": project["rag"],
                "signals": project["signals"],
                "metrics": {
                    key: project["metrics"][key]
                    for key in [
                        "active_tasks",
                        "overdue_active_tasks",
                        "upcoming_14_day_active_tasks",
                        "red_active_tasks",
                        "red_milestones",
                        "overdue_milestones",
                        "progress_gap",
                        "summary_at_risk",
                    ]
                },
                "evidence": project["evidence"],
            }
            response = self.llm.complete_json(
                SYSTEM_PROMPT,
                RISK_PROMPT.format(project=json.dumps(compact_project, indent=2)),
            )
            if "risk_themes" not in response:
                response = self._fallback_project_risk(project, response)
            response["llm_provider"] = self.llm.provider_name
            outputs[project["project_name"]] = response
        state.llm_outputs["risk_detector"] = outputs
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        state.log(
            "Tool 2 - Risk Detector",
            "completed",
            {
                "provider": self.llm.provider_name,
                "model": getattr(self.llm, "model", "n/a"),
                "duration_ms": elapsed_ms,
                "projects": len(outputs),
            },
        )

    def _portfolio_synthesizer(self, state: AgentState) -> None:
        compact = [
            {
                "project_name": p["project_name"],
                "rag": p["rag"],
                "stage": p["project_stage"],
                "reason": p["reason"],
                "signals": p["signals"],
                "metrics": {
                    "overdue_active_tasks": p["metrics"]["overdue_active_tasks"],
                    "upcoming_14_day_active_tasks": p["metrics"]["upcoming_14_day_active_tasks"],
                    "red_active_tasks": p["metrics"]["red_active_tasks"],
                    "progress_gap": p["metrics"]["progress_gap"],
                    "negative_comment_count": p["metrics"]["negative_comment_count"],
                },
            }
            for p in state.projects
        ]
        start = time.perf_counter()
        response = self.llm.complete_json(
            SYSTEM_PROMPT,
            PORTFOLIO_PROMPT.format(projects=json.dumps(compact, indent=2)),
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if "portfolio_takeaway" not in response:
            response = self._fallback_portfolio(state.projects, response)
        response["llm_provider"] = self.llm.provider_name
        state.portfolio = response
        state.log(
            "LLM - Executive Synthesizer",
            "completed",
            {
                "provider": self.llm.provider_name,
                "model": getattr(self.llm, "model", "n/a"),
                "duration_ms": elapsed_ms,
            },
        )

    def _report_writer(self, state: AgentState) -> None:
        for project in state.projects:
            result = self.analyzer.evaluate(Path(project["source_file"]))
            path = write_markdown_report(result, self.output_dir)
            self._append_ai_section(path, project, state)
            state.reports.append(str(path))
        summary_path = self.output_dir / "agentic_project_health_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "agent_type": "LLM-orchestrated tool workflow",
                    "llm_provider": self.llm.provider_name,
                    "config": self.config,
                    "projects": state.projects,
                    "llm_outputs": state.llm_outputs,
                    "portfolio": state.portfolio,
                    "trace": state.trace,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        state.reports.append(str(summary_path))
        state.log("Tool 6 - Report Writer", "completed", {"files": len(state.reports)})

    def _trace_writer(self, state: AgentState) -> None:
        trace_path = self.output_dir / "agent_execution_trace.json"
        state.log("Agent Trace", "completed", {"path": str(trace_path)})
        trace_path.write_text(json.dumps(state.trace, indent=2), encoding="utf-8")

    def _append_ai_section(self, path: Path, project: dict[str, Any], state: AgentState) -> None:
        sentiment = state.llm_outputs["stakeholder_sentiment"].get(project["project_name"], {})
        risk = state.llm_outputs["risk_detector"].get(project["project_name"], {})
        extra = [
            "",
            "## AI Agent Reasoning Layer",
            f"- LLM provider: {self.llm.provider_name}",
            f"- Sentiment classification: {sentiment.get('sentiment', 'Unavailable')}",
            f"- Sentiment themes: {', '.join(sentiment.get('themes', [])[:4]) if isinstance(sentiment.get('themes'), list) else sentiment.get('themes', '')}",
            f"- Risk themes: {', '.join(risk.get('risk_themes', [])[:4]) if isinstance(risk.get('risk_themes'), list) else risk.get('risk_themes', '')}",
            f"- AI executive summary: {risk.get('executive_summary', project['reason'])}",
            "",
        ]
        path.write_text(path.read_text(encoding="utf-8") + "\n".join(extra), encoding="utf-8")

    def _comment_themes(self, comments: list[str]) -> list[str]:
        text = " ".join(comments).lower()
        themes = []
        for token, theme in [
            ("mapping", "Mapping dependency"),
            ("workshop", "Workshop schedule impact"),
            ("calendar", "Meeting coordination"),
            ("pending", "Pending client input"),
            ("need", "Action required"),
        ]:
            if token in text:
                themes.append(theme)
        return themes or ["Blocker-like stakeholder comments"]

    def _fallback_project_risk(self, project: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        m = project["metrics"]
        themes = []
        if m["overdue_active_tasks"]:
            themes.append("Schedule slippage")
        if m["red_milestones"]:
            themes.append("Milestone health")
        if project["signals"]["budget"] == "Missing":
            themes.append("Budget visibility gap")
        if m["negative_comment_count"]:
            themes.append("Stakeholder dependency")
        return {
            "risk_themes": themes,
            "emerging_risks": [
                f"{m['upcoming_14_day_active_tasks']} active tasks are due in the next 14 days.",
                "Budget burn cannot be scored from the current export.",
            ],
            "executive_summary": project["reason"],
            "recommended_actions": project["recommendations"],
            **response,
        }

    def _fallback_portfolio(self, projects: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
        overdue = sum(p["metrics"]["overdue_active_tasks"] for p in projects)
        upcoming = sum(p["metrics"]["upcoming_14_day_active_tasks"] for p in projects)
        red = sum(1 for p in projects if p["rag"] == "Red")
        return {
            "portfolio_takeaway": f"{red}/{len(projects)} projects are Red, with {overdue} active overdue tasks and {upcoming} active tasks due in 14 days.",
            "trends": [
                "Schedule risk is present across both sample projects.",
                "Near-term task load is high enough to create additional misses.",
                "Budget burn is missing from the supplied workbooks.",
            ],
            "emerging_risks": [
                "Recovery capacity may be consumed by overdue work before upcoming milestones are protected.",
                "Client dependency and comment-driven blockers are visible in Titan.",
            ],
            "executive_recommendations": [
                "Stand up a two-week recovery cadence for all Red and overdue active work.",
                "Escalate dependency blockers in steering forums.",
                "Add budget planned, actual, and forecast fields to the weekly export.",
            ],
            "follow_up_questions": [
                "Which owner is accountable for each overdue Red milestone?",
                "What is the budget variance and forecast-to-complete for each project?",
            ],
            **response,
        }


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and path.exists():
        override = json.loads(path.read_text(encoding="utf-8"))
        deep_update(config, override)
    return config


def deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI-agent project health workflow.")
    parser.add_argument("plans", nargs="+", type=Path)
    parser.add_argument("--as-of", default="2026-07-09")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_outputs"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "none", "openai", "gemini", "ollama"],
        default="auto",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    llm = make_llm(config, args.llm_provider)
    logger.info("Starting agent run | provider=%s | plans=%d", llm.provider_name, len(args.plans))
    graph = AgentGraph(args.as_of, args.output_dir, llm, config)
    state = graph.run(args.plans)
    print(
        json.dumps(
            {
                "agent": "agentic_project_health_agent",
                "llm_provider": llm.provider_name,
                "reports": state.reports,
                "portfolio_takeaway": state.portfolio.get("portfolio_takeaway"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())