# Running in Production

> **Status:** This guide covers the essentials. Detailed hardening recipes coming soon.

agent-os is designed for production from day one — no database to manage, no message queue to monitor, no complex deployment pipeline.

## Scheduling with Cron

agent-os agents run as cron jobs, not daemons. This is deliberate: cron is simpler, more debuggable, and survives restarts without process managers.

```bash
# Agent cycles — check for work every 15 minutes
*/15 * * * * cd /path/to/company && agent-os cycle agent-001-builder
*/15 * * * * cd /path/to/company && agent-os cycle agent-002-marketer

# Standing orders — daily
0 8 * * * cd /path/to/company && agent-os standing-orders agent-001-builder
0 9 * * * cd /path/to/company && agent-os standing-orders agent-002-marketer

# Drive consultations — weekday evenings, weekend 3x/day
0 17 * * 1-5 cd /path/to/company && agent-os drives agent-001-builder
0 8,13,18 * * 0,6 cd /path/to/company && agent-os drives agent-001-builder

# Dream cycles — nightly, staggered
0 2 * * * cd /path/to/company && agent-os dream agent-001-builder
10 2 * * * cd /path/to/company && agent-os dream agent-002-marketer
```

Stagger agent schedules to avoid concurrent API calls competing for rate limits.

## Backups

The filesystem **is** your data. Back it up like any directory:

```bash
# Git (recommended) — automatic audit trail
cd /path/to/company && git add -A && git commit -m "auto-commit $(date)"

# rsync to remote
rsync -av /path/to/company/ backup-server:/backups/company/

# Tarball
tar czf company-$(date +%Y%m%d).tar.gz /path/to/company/
```

Git is the natural choice — you get versioning, diff, and blame for free. Consider auto-committing on a schedule.

## Monitoring

### Log Files

Agent activity logs are JSONL files at `agents/logs/{agent-id}/YYYY-MM-DD.jsonl`:

```jsonl
{"timestamp": "2026-03-01T10:00:00Z", "action": "task_claimed", "detail": "task-042", "agent": "agent-001"}
{"timestamp": "2026-03-01T10:05:00Z", "action": "task_completed", "detail": "task-042", "agent": "agent-001"}
```

### Cost Logs

API spend is tracked per-invocation in `finance/costs/`. Monitor for budget anomalies:

```bash
# Total spend today
grep "$(date +%Y-%m-%d)" finance/costs/*.jsonl | jq -s 'map(.cost_usd) | add'
```

### Health Checks

Use the dashboard (`agent-os dashboard`) for real-time health, or query the filesystem directly:

```bash
# Are agents working?
ls agents/tasks/in-progress/

# Are tasks getting stuck?
find agents/tasks/in-progress/ -mtime +1 -name "*.md"

# What failed recently?
ls -lt agents/tasks/failed/ | head
```

## Log Rotation

JSONL log files grow daily. Rotate or archive old logs:

```bash
# Archive logs older than 30 days
find agents/logs/ -name "*.jsonl" -mtime +30 -exec gzip {} \;
```

## Security

- **API keys** — Set `ANTHROPIC_API_KEY` as an environment variable, not in files. Never commit secrets to the company filesystem.
- **File permissions** — The company directory contains all operational data. Restrict access appropriately.
- **Network** — agent-os makes outbound API calls only. No inbound ports needed (except the dashboard, if enabled).

## Resource Requirements

agent-os is lightweight:

- **CPU** — Minimal. Agents are I/O-bound (waiting on API calls).
- **Memory** — Under 200MB per agent invocation.
- **Disk** — Grows with task history and logs. A company with 5 agents produces ~10-50MB/month of markdown and JSONL.
- **Network** — Outbound HTTPS to Anthropic API. Bandwidth is minimal.

A $5-10/month VPS handles multiple agents comfortably. Corvyd runs 5 agents on a single Hetzner VPS.
