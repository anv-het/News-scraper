# Health Folder Guide

This document explains how to organize and reuse a standard `health` folder across projects.

## 1) Purpose of the `health` folder

The `health` folder is a project quality and observability area. It keeps checks, logs, status snapshots, and operational notes in one place so teams can quickly understand whether the project is healthy.

Use it for:
- Runtime health summaries
- Data quality checks
- Scraper/API status
- Error and retry tracking
- Daily/weekly operational snapshots

## 2) Target locations

Current projects using this pattern:
- `F:\Corp Actions\health`
- `F:\News\main_scrapper_v2\health`
- `F:\X-Scraper\X-Scraper\health`

## 3) Recommended structure inside `health`

```text
health/
  README.md
  health.md
  checks/
    source_availability.md
    schema_validation.md
    freshness_rules.md
  reports/
    daily/
    weekly/
    monthly/
  logs/
    app/
    errors/
    retries/
  snapshots/
    latest.json
    history/
  alerts/
    alert_rules.md
    incidents.md
  config/
    thresholds.example.json
    pipelines.example.yaml
  scripts/
    run_health_checks.ps1
    summarize_health.ps1
```

## 4) What each folder stores

- `checks/`: Definitions of what you validate (availability, schema, freshness, duplicates).
- `reports/`: Human-readable health reports by time period.
- `logs/`: Execution logs and failure logs.
- `snapshots/`: Machine-readable status outputs for dashboards/automation.
- `alerts/`: Trigger rules and incident history.
- `config/`: Thresholds and behavior settings.
- `scripts/`: Utility scripts to generate checks/reports.

## 5) Standard file conventions

- Date format: `YYYY-MM-DD`.
- Timestamp format: ISO 8601 (`2026-03-27T10:30:00Z`).
- Report naming: `health_report_YYYY-MM-DD.md`.
- Snapshot naming: `health_snapshot_YYYY-MM-DD.json`.
- Log naming: `component_YYYY-MM-DD.log`.

## 6) Minimum metrics to track

Track these in reports/snapshots:
- Source availability (`up/down`, response time)
- Success rate (records collected vs expected)
- Error rate (total errors, top error types)
- Freshness (last successful run time)
- Duplicates (count and ratio)
- Retry behavior (attempt count, final status)
- Throughput (records per minute)

## 7) Example `latest.json` schema

```json
{
  "generated_at": "2026-03-27T10:30:00Z",
  "project": "main_scrapper_v2",
  "status": "healthy",
  "metrics": {
    "sources_up": 8,
    "sources_total": 9,
    "success_rate": 0.97,
    "error_rate": 0.03,
    "freshness_minutes": 12,
    "duplicates": 4,
    "throughput_rpm": 230
  },
  "notes": [
    "Source X had intermittent timeout between 09:10 and 09:18 UTC"
  ]
}
```

## 8) Quick setup for a new project

1. Create project health root:
   - `<project_root>\\health`
2. Create standard subfolders:
   - `checks`, `reports`, `logs`, `snapshots`, `alerts`, `config`, `scripts`
3. Add this `health.md` as the operating guide.
4. Add `README.md` with project-specific owner/contact/runbook links.
5. Add initial threshold config under `config/`.
6. Add a script in `scripts/` to generate daily report and latest snapshot.

## 9) PowerShell scaffold command (new project)

```powershell
$base = "F:\YourProject\health"
$dirs = @(
  "checks",
  "reports\\daily",
  "reports\\weekly",
  "reports\\monthly",
  "logs\\app",
  "logs\\errors",
  "logs\\retries",
  "snapshots\\history",
  "alerts",
  "config",
  "scripts"
)

New-Item -ItemType Directory -Path $base -Force | Out-Null
$dirs | ForEach-Object {
  New-Item -ItemType Directory -Path (Join-Path $base $_) -Force | Out-Null
}
```

## 10) Suggested ownership model

- Assign one folder owner per project.
- Review `latest.json` and `reports/daily` at least once per business day.
- Archive old logs monthly.
- Keep threshold changes in version control.

## 11) Versioning and change control

- Store all `health` files in Git.
- Update `health.md` when structure changes.
- Keep an entry in `reports/weekly` for major incidents and fixes.

## 12) Optional enhancements

- Add automatic health score (0-100).
- Push snapshot to monitoring dashboard.
- Add alerting integration (email/Teams/Slack/webhook).
- Add SLA/SLO summary section in weekly report.

---

If you copy this structure to another project, keep section 2 (paths) updated and customize thresholds/metrics to that project.
