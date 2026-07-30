# Server deployment

The production checkout is expected at `/workspace`, with the application in
`/workspace/feishu_bot` and its virtual environment at `/workspace/.venv`.

## API service

On a systemd host:

```bash
cp deploy/systemd/feishu-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now feishu-bot.service
curl --fail http://127.0.0.1:8000/health
```

On the Firecracker container used by the current server, PID 1 is not systemd.
Install the health watchdog in root's crontab instead:

```bash
chmod +x /workspace/deploy/feishu-watchdog.sh
(crontab -l 2>/dev/null; echo '* * * * * /workspace/deploy/feishu-watchdog.sh >> /workspace/watchdog.log 2>&1') | crontab -
```

## Yuanbao

Yuanbao is opt-in. Put the account owner's Playwright login state at:

```text
/workspace/feishu_bot/state/yuanbao_state.json
```

The state file must not be committed and should have mode `0600`. Install the
browser runtime with:

```bash
/workspace/.venv/bin/playwright install --with-deps chromium
```

Ask it from Feishu with `问元宝 <问题>` or `元宝：<问题>`. If Yuanbao is unavailable,
the bot automatically falls back to GLM.

Every request explicitly selects and verifies DeepSeek with deep thinking by
default. Override these settings only when needed:

```dotenv
YUANBAO_MODEL=deepseek
YUANBAO_DEEP_THINKING=true
YUANBAO_ANSWER_TIMEOUT_SECONDS=90
YUANBAO_MAX_ANSWER_CHARS=12000
```

The response extractor waits for streaming output to stabilize, formats
sections and bullet lists for Feishu, and appends newly generated source links.

## Daily scheduler

Set `FEISHU_CHAT_ID` before enabling the scheduler:

```bash
cp deploy/systemd/feishu-scheduler.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now feishu-scheduler.service
```

## Public callback

For production, use a named Cloudflare Tunnel with a fixed hostname. Quick
Tunnels under `trycloudflare.com` are temporary and can change after restart.
