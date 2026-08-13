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

The current container uses the per-chat subscription dispatcher from
`deploy/server.crontab`. It checks due subscriptions once per minute and uses
Asia/Shanghai for every saved schedule:

```bash
chmod +x /workspace/deploy/paper-subscription-dispatcher.sh
crontab /workspace/deploy/server.crontab
```

Supported Feishu commands:

```text
@HumanGroupBot 订阅 世界模型、视频生成、人体动作
@HumanGroupBot 推送时间 09:30
@HumanGroupBot 工作日推送
@HumanGroupBot 每天推送
@HumanGroupBot 暂停论文推送
@HumanGroupBot 恢复论文推送
@HumanGroupBot 查看订阅
```

Paper titles, authors, abstracts, dates and URLs are forced to the values from
the arXiv feed. Model output is used only for Chinese interpretation and
ranking. A recommendation must have verified official public code, a complete
Teaser/Figure 1 and a distinct network or method architecture figure. Papers
that fail any of these checks are skipped instead of being sent as text-only
cards.

The weekly roundup runs on Monday at 09:00 Asia/Shanghai by default. It sends
three unique papers in each category (12 total): Motion Generation, Video,
Embodied AI and World Models. It prioritizes the previous calendar week and
uses the preceding 30 days only as a fallback. Configure it with:

```dotenv
WEEKLY_PUSH_WEEKDAY=0
WEEKLY_PUSH_TIME=09:00
```

Optional alphaXiv discovery is enabled with `ALPHAXIV_API_KEY`. The key belongs
only in `feishu_bot/.env`; never commit it. alphaXiv results are treated as a
discovery signal and are resolved through arXiv again before recommendation.

AI news may be delivered to a different group from paper recommendations:

```dotenv
FEISHU_CHAT_ID=oc_paper_group
FEISHU_NEWS_CHAT_ID=oc_news_group
```

If `FEISHU_NEWS_CHAT_ID` is empty, news falls back to `FEISHU_CHAT_ID` for
backward compatibility.

Access can be granted to individual users or to every member of selected
groups. Group authorization is scoped to that group and does not grant its
members access from other chats:

```dotenv
FEISHU_ALLOWED_OPEN_IDS=ou_owner
FEISHU_ALLOWED_CHAT_IDS=oc_shared_group
```

Conversational memory is stored in `data/chat_memory.db` and partitioned by
Feishu `chat_id`. Each group can have a separate role profile, and only its
most recent turns are injected into GLM, Yuanbao or ChatGPT web requests.
`CHAT_MEMORY_CONTEXT_TURNS` controls the context window (default 6, maximum
12). Runtime memory databases are excluded from Git.

## Public callback

For production, use a fixed ngrok domain or a named Cloudflare Tunnel. Temporary
domains can change after restart and require the Feishu callback URL to be
updated again.
