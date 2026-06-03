# YATA UK + Japan Item 206 Restock Monitors

Python background worker for YATA travel stock monitoring. This fork runs two item `206` monitors from one GitHub Actions workflow:

- UK bot, using `.env.uk` and `data/github_actions_state_uk.json`.
- Japan bot, using `.env.jp` and `data/github_actions_state_jp.json`.

Both bots read YATA travel export data, track stock transitions, estimate restock/depletion timing, predict the next restock cycle, and send Discord webhook messages.

## Environment Files

The repository includes safe, non-secret env files:

```bash
.env.uk
.env.jp
```

Do not commit Discord webhooks. GitHub Actions injects them from repository secrets.

Important Japan settings:

```bash
COUNTRY=Japan
TARGET_COUNTRY_ALIASES=Japan,Tokyo,jap,jpn
AIRSTRIP_DURATION_MINUTES=158
BUSINESS_CLASS_DURATION_MINUTES=68
AIRSTRIP_TARGET_RESTOCK_CYCLE=2
BUSINESS_CLASS_TARGET_RESTOCK_CYCLE=1
```

Japan Airstrip targets the projected second restock because the flight is long enough to miss the first restock. Japan Business Class targets the first predicted restock.

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run one UK check:

```powershell
$env:ENV_FILE=".env.uk"
python monitor.py --once
```

Run one Japan check:

```powershell
$env:ENV_FILE=".env.jp"
python monitor.py --once
```

Run tests:

```powershell
pytest
```

## GitHub Actions

The workflow is `.github/workflows/monitor.yml`. It supports manual runs and a scheduled run every 5 minutes.

Create these repository secrets:

```bash
DISCORD_WEBHOOK_URL_UK
DISCORD_WEBHOOK_URL_JP
```

The workflow runs both bots in parallel, uploads each state file as an artifact, then commits the updated JSON state files in one final job to avoid concurrent pushes.

State files:

```bash
data/github_actions_state_uk.json
data/github_actions_state_jp.json
```

The UK state is seeded from the original monitor state. The Japan state is created by the first successful Japan workflow run.

## Notes

- Discord payload format stays compact: restock detected, next predicted restock, prediction interval, prediction ID, and recommended departures.
- The formatter no longer hard-codes `UK`; messages use the configured/event country.
- GitHub scheduled workflows can be delayed or skipped during platform congestion, so reminders include the configured delay buffer but cannot guarantee real-time delivery.
