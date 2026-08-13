import json
from datetime import datetime
from zoneinfo import ZoneInfo

import tech_news


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _subscription():
    return {
        "chat_id": "oc_test",
        "public_accounts": ["量子位", "机器之心"],
        "companies": ["OpenAI", "NVIDIA"],
        "x_accounts": ["OpenAI", "AnthropicAI", "nvidia"],
        "push_time": "21:00",
        "enabled": True,
    }


def test_default_accounts_are_deduplicated():
    assert tech_news.DEFAULT_PUBLIC_ACCOUNTS.count("量子位") == 1
    assert set(tech_news.DEFAULT_PUBLIC_ACCOUNTS) == {
        "量子位",
        "机器之心",
        "新智元",
        "CVer",
        "刘聪NLP",
        "具身智能之心",
    }
    assert len(tech_news.DEFAULT_X_ACCOUNTS) == len(
        {value.casefold() for value in tech_news.DEFAULT_X_ACCOUNTS}
    )
    assert {"OpenAI", "AnthropicAI", "nvidia", "Alibaba_Qwen"}.issubset(
        set(tech_news.DEFAULT_X_ACCOUNTS)
    )


def test_only_selected_wechat_or_official_company_domains_are_allowed():
    subscription = _subscription()
    assert tech_news._item_source_type(
        {
            "publisher": "量子位",
            "url": "https://mp.weixin.qq.com/s/official-article",
        },
        subscription,
    ) == "公众号"
    assert tech_news._item_source_type(
        {
            "publisher": "OpenAI",
            "url": "https://openai.com/index/official-release/",
        },
        subscription,
    ) == "企业官方"
    assert tech_news._item_source_type(
        {
            "publisher": "OpenAI",
            "url": "https://random-news.example/openai-rumor",
        },
        subscription,
    ) == ""
    assert tech_news._canonical_url(
        "https://openai.com/blog/placeholder_1"
    ) == ""


def test_only_whitelisted_direct_x_status_urls_are_allowed():
    subscription = _subscription()
    assert tech_news._canonical_url(
        "https://twitter.com/OpenAI/status/123456?utm_source=test"
    ) == "https://x.com/OpenAI/status/123456"
    assert tech_news._item_source_type(
        {
            "publisher": "OpenAI",
            "url": "https://x.com/OpenAI/status/123456?ref_src=twsrc",
        },
        subscription,
    ) == "官方 X"
    assert tech_news._item_source_type(
        {
            "publisher": "OpenAI",
            "url": "https://x.com/FakeOpenAI/status/123456",
        },
        subscription,
    ) == ""
    assert tech_news._canonical_url("https://x.com/OpenAI") == ""


def test_x_oembed_verifies_author_date_and_original_text(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "author_name": "OpenAI",
                "author_url": "https://x.com/OpenAI",
                "html": (
                    '<blockquote><p lang="en">We are releasing a new AI system '
                    "for developers today.</p>&mdash; OpenAI (@OpenAI) "
                    '<a href="https://x.com/OpenAI/status/123456">'
                    "August 10, 2026</a></blockquote>"
                ),
            }

    monkeypatch.setattr(tech_news.requests, "get", lambda *args, **kwargs: Response())
    verified = tech_news._verify_x_post(
        {
            "url": "https://x.com/OpenAI/status/123456",
            "published_date": "2026-08-09",
            "summary": "OpenAI 发布面向开发者的新系统。",
        },
        ["OpenAI"],
    )
    assert verified["publisher"] == "OpenAI"
    assert verified["published_date"] == "2026-08-10"
    assert verified["x_handle"] == "OpenAI"
    assert "new AI system" in verified["source_text"]
    assert verified["title"].startswith("@OpenAI：")


def test_x_oembed_rejects_mismatched_author(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "author_name": "Impostor",
                "author_url": "https://x.com/Impostor",
                "html": "<blockquote><p>This is a sufficiently long fake announcement.</p></blockquote>",
            }

    monkeypatch.setattr(tech_news.requests, "get", lambda *args, **kwargs: Response())
    assert tech_news._verify_x_post(
        {"url": "https://x.com/OpenAI/status/123456"}, ["OpenAI"]
    ) is None


def test_official_domain_still_requires_matching_page_title(monkeypatch):
    class Response:
        status_code = 200
        text = "<html><title>Unrelated corporate homepage</title></html>"

    monkeypatch.setattr(tech_news.requests, "get", lambda *args, **kwargs: Response())
    assert not tech_news._page_is_accessible_and_consistent(
        {
            "title": "OpenAI launches a new reasoning model",
            "publisher": "OpenAI",
            "url": "https://openai.com/index/made-up-path/",
        },
        "企业官方",
    )


def test_collect_news_rejects_unofficial_and_old_results(monkeypatch):
    now = datetime(2026, 8, 11, 21, 0, tzinfo=SHANGHAI)
    monkeypatch.setattr(
        tech_news,
        "call_glm",
        lambda *args, **kwargs: json.dumps(
            {
                "items": [
                    {
                        "title": "Official AI launch",
                        "publisher": "OpenAI",
                        "published_date": "2026-08-11",
                        "url": "https://openai.com/index/official-ai-launch/",
                        "summary": "OpenAI 官方发布新的 AI 产品能力。",
                        "why_it_matters": "影响开发者工作流。",
                        "entities": ["OpenAI"],
                    },
                    {
                        "title": "Rumor",
                        "publisher": "OpenAI",
                        "published_date": "2026-08-11",
                        "url": "https://rumor.example/story",
                        "summary": "未经官方确认。",
                        "why_it_matters": "",
                        "entities": ["OpenAI"],
                    },
                    {
                        "title": "Old item",
                        "publisher": "NVIDIA",
                        "published_date": "2026-07-20",
                        "url": "https://nvidia.com/old-item",
                        "summary": "旧内容。",
                        "why_it_matters": "",
                        "entities": ["NVIDIA"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
    )
    items = tech_news.collect_tech_news(
        _subscription(), now=now, verify_pages=False
    )
    assert [item["title"] for item in items] == ["Official AI launch"]
    assert items[0]["verified"] is True


def test_news_subscription_commands_and_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(tech_news, "DB_PATH", tmp_path / "news.db")
    response = tech_news.handle_news_subscription_command(
        "oc_test", "订阅公众号 量子位、机器之心、量子位"
    )
    assert "公众号订阅已更新" in response
    value = tech_news.get_news_subscription("oc_test")
    assert value["public_accounts"] == ["量子位", "机器之心"]
    response = tech_news.handle_news_subscription_command(
        "oc_test", "订阅X账号 @OpenAI、@AnthropicAI、@OpenAI"
    )
    assert "官方 X 账号订阅已更新" in response
    assert tech_news.get_news_subscription("oc_test")["x_accounts"] == [
        "OpenAI",
        "AnthropicAI",
    ]
    tech_news.handle_news_subscription_command(
        "oc_test", "资讯推送时间 21:00"
    )
    assert tech_news.due_news_subscriptions(
        datetime(2026, 8, 11, 20, 59, tzinfo=SHANGHAI)
    ) == []
    assert len(
        tech_news.due_news_subscriptions(
            datetime(2026, 8, 11, 21, 0, tzinfo=SHANGHAI)
        )
    ) == 1


def test_digest_contains_direct_links(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    monkeypatch.setattr("feishu_sender.get_token", lambda: "token")
    monkeypatch.setattr(
        tech_news.requests,
        "post",
        lambda *args, **kwargs: captured.update(kwargs) or Response(),
    )
    tech_news.send_tech_news_digest(
        "oc_test",
        [
            {
                "title": "Official AI launch",
                "publisher": "OpenAI",
                "published_date": "2026-08-11",
                "url": "https://openai.com/index/official-ai-launch/",
                "summary": "官方事实摘要。",
                "why_it_matters": "值得关注。",
                "entities": ["OpenAI"],
                "source_type": "企业官方",
            }
        ],
        archive_url="https://my.feishu.cn/docx/news-library",
        now=datetime(2026, 8, 11, 21, 0, tzinfo=SHANGHAI),
    )
    content = captured["json"]["content"]
    assert "https://openai.com/index/official-ai-launch/" in content
    assert "https://my.feishu.cn/docx/news-library" in content


def test_cross_source_duplicate_prefers_official_company_page():
    items = [
        {
            "title": "OpenAI releases GPT Next for developers",
            "summary": "OpenAI 发布 GPT Next，并向开发者开放新的 API 能力。",
            "publisher": "OpenAI",
            "entities": ["OpenAI", "GPT Next"],
            "source_type": "官方 X",
        },
        {
            "title": "Introducing GPT Next for developers",
            "summary": "OpenAI 发布 GPT Next，并向开发者开放新的 API 能力。",
            "publisher": "OpenAI",
            "entities": ["OpenAI", "GPT Next"],
            "source_type": "企业官方",
        },
    ]
    result = tech_news._deduplicate_events(items)
    assert len(result) == 1
    assert result[0]["source_type"] == "企业官方"
