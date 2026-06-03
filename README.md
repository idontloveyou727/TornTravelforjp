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

Japan travel recommendations can be toggled directly in `.env.jp`:

```bash
ENABLE_AIRSTRIP=1
ENABLE_BUSINESS_CLASS=1
```

Set a value to `0` to hide that travel type from restock recommendations and disable its departure reminder.

Prediction interval history stays at 10 recent cycles by default. Accuracy is tracked separately with `PREDICTION_ACCURACY_HISTORY_WINDOW=50`, so the displayed accuracy is calculated from up to the latest 50 evaluated predictions.

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

The workflow is `.github/workflows/monitor.yml`. It only supports manual `workflow_dispatch` runs, so an external cronjob can trigger it without GitHub's built-in schedule.

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

UK starts with seeded depletion-rate and depletion-to-restock interval data in `data/github_actions_state_uk.json`, with accuracy reset. Japan starts from default state and creates `data/github_actions_state_jp.json` on the first successful Japan run.

## Notes

- Discord payload format stays compact: restock detected, next predicted restock, prediction interval, prediction ID, and recommended departures.
- The formatter no longer hard-codes `UK`; messages use the configured/event country.
- External cron timing still depends on GitHub Actions queue time after dispatch, so reminders include the configured delay buffer but cannot guarantee real-time delivery.
