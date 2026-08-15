# Slack setup via Slack CLI (match notifications)

This project posts high-match opportunity alerts to Slack using the **same credential model as Slack CLI / Bolt apps**, not Incoming Webhooks (webhooks remain a legacy fallback only).

**Docs:** [Slack CLI](https://docs.slack.dev/tools/slack-cli/) · [Authorize CLI](https://docs.slack.dev/tools/slack-cli/guides/authorizing-the-slack-cli) · [Bolt Python tokens](https://docs.slack.dev/tools/bolt-python/getting-started)

---

## What you paste into this repo

| Variable | Example | Required? | Role |
|----------|---------|-----------|------|
| `SLACK_BOT_TOKEN` | `xoxb-...` | **Yes** (preferred path) | Bot User OAuth token → `chat.postMessage` |
| `SLACK_CHANNEL_ID` | `C0123ABCD` or `#bid-alerts-test` | **Yes** (with bot token) | Where to post |
| `SLACK_APP_TOKEN` | `xapp-...` | Optional | Socket Mode / `slack run` only; **not** used for match posts |
| `SLACK_MATCH_NOTIFY_ENABLED` | `true` | Default true | Master switch |
| `TEAMS_MATCH_SCORE_THRESHOLD` | `40` | Shared with Teams | Min score 0–100 |
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/...` | Legacy only | Fallback if bot token unset |

Install SDK:

```powershell
pip install -e ".[slack]"
```

---

## Path A — Slack CLI (recommended)

### 1. Install & login

Windows: follow [Install Slack CLI for Windows](https://docs.slack.dev/tools/slack-cli/guides/installing-the-slack-cli-for-windows).

```powershell
slack version
slack login
# Complete /slackauthticket + challenge in Slack
slack auth list
```

Auth data for the **CLI itself** lives in `~/.slack/credentials.json` (do not commit).  
**This Python app does not read that file** — you still paste **app** tokens into repo `.env` (below).

### 2. Create or open a Bolt/CLI app

Either:

```powershell
# Optional: separate Bolt sample app to mint tokens quickly
slack create bid-alerts-app --template slack-samples/bolt-python-getting-started-app
cd bid-alerts-app
slack run
# Select create/install app when prompted
```

Or create an app from [api.slack.com/apps](https://api.slack.com/apps) / `slack app settings` for an existing CLI project.

### 3. Scopes & install

In app settings → **OAuth & Permissions** → Bot Token Scopes, ensure at least:

- `chat:write` (required)
- `chat:write.public` (optional; post to public channels without join)

**Reinstall** the app to the **test workspace** after adding scopes.

Invite the bot to the target channel (if private, or if missing `chat:write.public`):

```text
/invite @YourBotName
```

### 4. Copy tokens (CLI / Bolt style)

| Token | Where in Slack app UI |
|-------|------------------------|
| **Bot User OAuth Token** `xoxb-...` | OAuth & Permissions → *Bot User OAuth Token* → env `SLACK_BOT_TOKEN` |
| **App-Level Token** `xapp-...` | Basic Information → App-Level Tokens (`connections:write`) → env `SLACK_APP_TOKEN` (only if you also run Bolt Socket Mode) |

### 5. Channel ID

In Slack (desktop): channel name → **View channel details** → bottom **Channel ID** `C...`  
Or use `#channel-name` if the bot can resolve it.

### 6. Paste into **repo-root** `.env`

```env
# Slack CLI / Bolt config (preferred)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_CHANNEL_ID=C0123456789
# Optional (not used by match notify):
# SLACK_APP_TOKEN=xapp-your-app-token

SLACK_MATCH_NOTIFY_ENABLED=true
TEAMS_MATCH_SCORE_THRESHOLD=40

# Quiet Teams while testing Slack:
TEAMS_MATCH_NOTIFY_ENABLED=false
```

### 7. Verify settings load

```powershell
cd <repository-root>
.\.venv\Scripts\Activate.ps1
pip install -e ".[slack]"

python -c "from opportunity_ingest.config import get_settings; s=get_settings(); print('web_api', s.slack_web_api_configured()); print('token', bool(s.resolved_slack_bot_token())); print('channel', s.resolved_slack_channel_id()); print('threshold', s.teams_match_score_threshold)"
```

Expect: `web_api True`, token True, channel set.

### 8. Smoke-test Web API (no full pipeline)

```powershell
python -c @"
from opportunity_ingest.config import get_settings
from opportunity_ingest.notify import post_slack_chat_message
s = get_settings()
post_slack_chat_message(
    bot_token=s.resolved_slack_bot_token(),
    channel=s.resolved_slack_channel_id(),
    text='contractbiddingsystem Slack CLI config OK',
    blocks=None,
)
print('posted ok')
"@
```

Message should appear in the configured channel.

### 9. End-to-end match notify (lower threshold once)

```env
TEAMS_MATCH_SCORE_THRESHOLD=1
```

```powershell
python -m opportunity_ingest interpret-rank --status New --limit 5 --no-sync-sheets
```

Console should show `slack=True`. Then set threshold back to **40**.

---

## Path B — Tokens without full `slack create`

If you already have a test app:

1. Install app to test workspace with `chat:write`.  
2. Copy `xoxb-` bot token → `SLACK_BOT_TOKEN`.  
3. Set `SLACK_CHANNEL_ID`.  
4. Same verify steps §7–9.

This is still the **CLI/Bolt env contract** (`SLACK_BOT_TOKEN` + channel), even if you did not use `slack create`.

---

## Legacy Incoming Webhook (not preferred)

If only a `hooks.slack.com` URL exists, set:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

The app logs a **warning** and uses the webhook. Migrate to bot token when possible.

---

## Troubleshooting

| Error / symptom | Fix |
|-----------------|-----|
| `slack-sdk not installed` | `pip install -e ".[slack]"` |
| `not_authed` / `invalid_auth` | Wrong/revoked bot token; reinstall app |
| `channel_not_found` | Bad `SLACK_CHANNEL_ID`; use `C...` ID |
| `not_in_channel` | `/invite @bot` into channel |
| `missing_scope` | Add `chat:write`, reinstall app |
| `web_api False` | Both token **and** channel required |
| No post, threshold | Lower `TEAMS_MATCH_SCORE_THRESHOLD` for test |

---

## Security

- Never commit `.env`, tokens, or `~/.slack/credentials.json`.  
- Prefer a **test workspace** / [developer sandbox](https://docs.slack.dev/tools/developer-sandboxes).  
- Rotate bot tokens if leaked.
