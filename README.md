# Project Health Reporting Agent

An AI-powered Project Health Reporting Agent developed for the **Zycus AI Engineer Intern Technical Assignment**.

The solution automatically analyzes Microsoft Excel project plans, determines project health using a configurable **Red–Amber–Green (RAG)** framework, performs AI-assisted reasoning using **Google Gemini 2.5 Flash**, and generates executive-ready project reports along with a portfolio-level monthly synthesis.

---

# Project Overview

Professional Services leadership often spends significant time collecting weekly project updates from Project Managers. This project automates that workflow by combining deterministic project analytics with AI-assisted reasoning.

The system:

* Reads Excel project plans
* Calculates project health using configurable RAG rules
* Identifies delivery risks
* Analyzes stakeholder sentiment
* Generates executive-level recommendations
* Produces weekly reports and portfolio summaries

The architecture intentionally separates **deterministic calculations** from **LLM reasoning**, ensuring that measurable project metrics remain auditable while leveraging AI only where natural language understanding adds value.

---

# Features

* Automated Project Health Reporting
* Configurable RAG Framework
* Google Gemini 2.5 Flash Integration
* Deterministic Project Health Scoring
* Stakeholder Sentiment Analysis
* Delivery Risk Identification
* Portfolio-Level Executive Insights
* Weekly Markdown Reports
* Executive Monthly Portfolio Summary
* Execution Trace Logging
* Robust JSON Extraction
* Retry Logic with Exponential Backoff
* Graceful Deterministic Fallback

---

# Project Structure

```text
project-health-reporting-agent/
│
├── src/
│   ├── project_health_agent.py
│   └── agentic_project_health_agent.py
│
├── methodology/
│   └── RAG_Methodology.md
│
├── sample_outputs/
│   ├── *.md
│   ├── agent_execution_trace.json
│   └── agentic_project_health_summary.json
│
├── executive_monthly_synthesis.pptx
├── prompts.md
├── config.json
├── requirements.txt
└── README.md
```

---

# Solution Architecture

```text
Excel Project Plans
        │
        ▼
Read Excel Files
        │
        ▼
Project Analyzer
        │
        ├──────────────┐
        ▼              ▼
Risk Detector    Stakeholder Sentiment
        │              │
        └──────┬───────┘
               ▼
Executive Portfolio Synthesizer
               ▼
Weekly Reports
               ▼
Portfolio Summary
               ▼
Execution Trace
```

---

# RAG Methodology

Project health is determined using configurable weighted indicators.

| Indicator             | Weight |
| --------------------- | -----: |
| Schedule Health       |    35% |
| Milestone Health      |    20% |
| Active Blockers       |    20% |
| Progress              |    15% |
| Stakeholder Sentiment |     5% |
| Data Quality          |     5% |

The scoring thresholds are configurable through `config.json`.

---

# AI Design

The system follows a **hybrid AI architecture**.

## Deterministic Engine

Responsible for:

* Schedule analysis
* Milestone evaluation
* Progress calculation
* Blocker detection
* Data completeness checks
* Final RAG score

These values are treated as the **single source of truth**.

## Gemini AI

Google Gemini is used only for reasoning tasks including:

* Stakeholder sentiment analysis
* Risk theme identification
* Executive summaries
* Portfolio synthesis
* Action recommendations

This approach minimizes hallucinations while maintaining explainable project health reporting.

---

# Requirements

* Python 3.10 or higher
* Google Gemini API Key

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Configuration

The application is configured through `config.json`.

Example:

```json
{
  "llm": {
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "temperature": 0.1,
    "max_retries": 3,
    "retry_backoff_seconds": 1.5
  }
}
```

---

# Running the Project

## Run with Gemini

Set your Gemini API key.

### Windows CMD

```cmd
set GEMINI_API_KEY=YOUR_API_KEY
```

### Windows PowerShell

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY"
```

Run the application:

```bash
python src/agentic_project_health_agent.py ^
"C:\path\to\S2P Project (1).xlsx" ^
"C:\path\to\Project Plan B (1).xlsx" ^
--as-of 2026-07-09 ^
--output-dir sample_outputs ^
--config config.json ^
--llm-provider gemini
```

---

## Deterministic Mode (Without AI)

The workflow can also run without Gemini.

```bash
python src/agentic_project_health_agent.py ^
"C:\path\to\S2P Project (1).xlsx" ^
"C:\path\to\Project Plan B (1).xlsx" ^
--as-of 2026-07-09 ^
--output-dir sample_outputs ^
--config config.json ^
--llm-provider none
```

---

# Generated Outputs

The agent produces:

* Weekly Project Health Reports (Markdown)
* Portfolio Health Summary (JSON)
* Agent Execution Trace (JSON)
* Executive Monthly Presentation (PowerPoint)

---

# Execution Trace

Every execution records:

* Timestamp
* Workflow Node
* Execution Status
* LLM Provider
* Model Used
* Execution Time
* Fallback Information

This provides complete transparency and auditability.

---

# Reliability Features

The implementation includes:

* Robust JSON extraction
* Automatic retry with exponential backoff
* Structured logging
* Missing-data handling
* Graceful deterministic fallback
* Configurable scoring framework

---

# Assumptions

The supplied project plans do not contain:

* Planned Budget
* Actual Budget
* Forecast Budget

Instead of estimating missing financial values, the system explicitly reports a **Budget Visibility Gap** and recommends capturing these fields in future project exports.

---

# Design Decisions

The solution intentionally separates deterministic analytics from AI reasoning.

Project metrics such as schedule health, milestone status, progress, and blockers are computed deterministically to ensure reproducibility and auditability.

Google Gemini is used only for language-intensive tasks such as stakeholder sentiment analysis, executive summaries, portfolio synthesis, and actionable recommendations.

This hybrid architecture provides:

* Reliable project scoring
* Explainable AI outputs
* Reduced hallucination risk
* Enterprise-ready design
* Easy extensibility

---

# Future Improvements

Potential enhancements include:

* Microsoft Teams notifications
* SharePoint integration
* Email report distribution
* Interactive dashboard
* Historical trend analysis
* Budget forecasting
* Resource utilization analytics
* Multi-project portfolio monitoring

---

# Deliverables

* RAG Methodology
* AI Project Health Reporting Agent
* Weekly Project Reports
* Executive Monthly Presentation
* Source Code
* Configuration Files
* Documentation

---

# Author

Prepared as part of the **Zycus AI Engineer Intern Technical Assignment**, demonstrating the application of deterministic analytics and Google Gemini-powered reasoning for automated project health reporting.

