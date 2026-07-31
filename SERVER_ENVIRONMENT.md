# Server environment

This file documents the reproducible parts of the deployed Feishu bot server.
It intentionally contains no passwords, tokens, cookies, proxy credentials, or
browser session data.

## Host layout

- Repository: `/workspace`
- Application: `/workspace/feishu_bot`
- Python environment: `/workspace/.venv`
- FastAPI port: `8000`
- Mihomo mixed port: `127.0.0.1:7890`
- Mihomo controller: `127.0.0.1:9090`
- Chromium CDP: `127.0.0.1:9222`
- noVNC: `127.0.0.1:6080`
- VNC: `127.0.0.1:5900`
- Swap: `/swapfile` (2 GiB)

All browser and proxy control ports are loopback-only. Do not expose them to
the public network.

## Persistent data excluded from Git

- `/workspace/feishu_bot/.env`
- `/workspace/feishu_bot/state/`
- `/etc/mihomo/config.yaml`
- `/root/.ssh/feishu_bot_github_ed25519`

Back these up only through a secure secrets-management channel. Never commit
them to GitHub.

## Background recovery

Root crontab is defined in `deploy/server.crontab` and runs:

- `/usr/local/sbin/mihomo-watchdog`
- `/workspace/deploy/chatgpt-browser-watchdog.sh`

FastAPI and Cloudflare Tunnel should be checked after any host wake or reboot:

```bash
curl --fail http://127.0.0.1:8000/health
pgrep -af "uvicorn main:app|cloudflared tunnel|mihomo"
```

The ChatGPT browser health endpoint is:

```bash
curl --fail http://127.0.0.1:9222/json/version
```

## Restore checklist

1. Clone the repository into `/workspace`.
2. Create `/workspace/.venv` and install `requirements.txt`.
3. Restore `.env`, Mihomo configuration, and browser state securely.
4. Install the crontab from `deploy/server.crontab`.
5. Start FastAPI and Cloudflare Tunnel.
6. Run the unit tests and both local/public health checks.
