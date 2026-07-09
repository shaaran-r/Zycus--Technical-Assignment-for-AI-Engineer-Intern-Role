# Project Health RAG Methodology

This framework assigns Red, Amber, or Green project health from multiple signals rather than a single PM-entered color. It assumes project plans may be exported from delivery tooling and may contain incomplete fields, formula errors, or missing budget data.

## Signals and Mapping

| Signal | Green | Amber | Red |
| --- | --- | --- | --- |
| Schedule slippage | No active overdue work and plan health mostly Green | Any active overdue work, any Amber/Yellow schedule labels, or limited Red work | Summary schedule is Red, Red active tasks are material, or overdue active work is material |
| Budget burn | Actuals and forecast within tolerance | Forecast variance needs review | Budget overrun or forecast breach |
| Milestone health | Milestones complete or on track | Upcoming milestone at risk | Active milestone is overdue or marked Red |
| Blockers and dependencies | No open at-risk/on-hold items | Some at-risk flags or blocker-like comments | Summary risk is High, on-hold work exists, or key dependencies block milestones |
| Stakeholder sentiment | Comments are positive or neutral | Isolated concern words such as pending, need, impacted | Multiple blocker-like comments or escalation language |
| Progress vs elapsed time | Percent complete is at or ahead of elapsed timeline | 10-25 percentage points behind elapsed timeline | More than 25 percentage points behind elapsed timeline |
| Data quality | Core fields present | Important missing/messy fields, but enough data to score | Core plan cannot be read reliably |

## Overall RAG Logic

The agent weights schedule most heavily because leadership primarily needs early warning on delivery commitments. The default weights are schedule 35%, milestones 20%, blockers 20%, progress 15%, sentiment 5%, and data quality 5%. These values are configurable in `config.json`, so a delivery leader can tune the model for a specific account or PMO standard. Budget is included in the framework but treated as neutral/missing when not present in the workbook.

The final status becomes Red when schedule is Red and blockers are Amber/Red, or when the weighted risk score crosses the Red threshold. It becomes Amber when there are meaningful warning signs but no combined critical pattern. It remains Green only when schedule, blockers, milestones, and progress are all healthy.

## Assumptions

Schedule Health values of Yellow are mapped to Amber. Tasks with statuses such as Completed or Not Applicable are not counted as active overdue work. End Date is treated as the planned date when no usable baseline is available. Stakeholder sentiment is inferred from comments and status notes with simple keyword scoring, so it is directional rather than a substitute for direct customer feedback. Missing budget fields are disclosed as a data gap and not fabricated.

In the agentic version, deterministic metrics remain the source of truth, while an LLM can be used to classify stakeholder sentiment, group risk themes, and draft executive recommendations from the extracted evidence. If no LLM is configured, the workflow still runs with a deterministic fallback and records that in the trace.
