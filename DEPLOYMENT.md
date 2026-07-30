# Server deployment

The production checkout is expected at `/workspace`, with the application in
`/workspace/feishu_bot` and its virtual environment at `/workspace/.venv`.

## API service

```bash
cp deploy/systemd/feishu-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now feishu-bot.service
curl --fail http://127.0.0.1:8000/health
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
