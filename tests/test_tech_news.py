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
    assert "thsottiaux" in tech_news.DEFAULT_X_ACCOUNTS


def test_expanded_official_sources_cover_models_chips_and_robotics():
    assert {
        "DeepSeek",
        "Hugging Face",
        "Mistral AI",
        "AMD AI",
        "Groq",
        "Figure AI",
        "Physical Intelligence",
        "Unitree",
    }.issubset(set(tech_news.DEFAULT_COMPANIES))
    assert "deepseek.com" in tech_news.COMPANY_DOMAINS["DeepSeek"]
    assert "github.com" in tech_news.COMPANY_DOMAINS["DeepSeek"]
    assert "physicalintelligence.company" in tech_news.COMPANY_DOMAINS[
        "Physical Intelligence"
    ]
    assert "https://machinelearning.apple.com/rss.xml" in tech_news.OFFICIAL_NEWS_FEEDS[
        "Apple ML"
    ]
    assert "https://www.amazon.science/index.rss" in tech_news.OFFICIAL_NEWS_FEEDS[
        "Amazon/AWS AI"
    ]


def test_direct_official_feed_discovery(monkeypatch):
    class Response:
        content = b"""
        <rss><channel><item>
          <title>Official open model release</title>
          <link>https://huggingface.co/blog/official-open-model</link>
          <pubDate>Sat, 15 Aug 2026 08:00:00 GMT</pubDate>
          <description><![CDATA[The official release adds new model weights and tools.]]></description>
        </item></channel></rss>
        """

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        tech_news,
        "OFFICIAL_NEWS_FEEDS",
        {"Hugging Face": ["https://huggingface.co/blog/feed.xml"]},
    )
    monkeypatch.setattr(tech_news.requests, "get", lambda *args, **kwargs: Response())
    subscription = {
        "companies": ["Hugging Face"],
        "public_accounts": [],
        "x_accounts": [],
    }

    items = tech_news._discover_official_feed_items(subscription)

    assert len(items) == 1
    assert items[0]["published_date"] == "2026-08-15"
    assert items[0]["url"] == "https://huggingface.co/blog/official-open-model"
    assert tech_news._item_source_type(items[0], subscription) == "企业官方"


def test_direct_x_discovery_extracts_status_urls_through_proxy(monkeypatch):
    class Response:
        status_code = 200
        text = (
            '<a href="/thsottiaux/status/2088103609477238858">post</a>'
            '<a href="/thsottiaux/status/2088019704803897705">post</a>'
        )

    calls = []
    monkeypatch.setenv("X_PROXY_URL", "http://10.103.11.92:4780")
    monkeypatch.setattr(
        tech_news.requests,
        "get",
        lambda *args, **kwargs: calls.append(kwargs) or Response(),
    )
    subscription = _subscription()
    subscription["x_accounts"].append("thsottiaux")
    items = tech_news._discover_direct_x_items(subscription)
    assert [item["url"] for item in items] == [
        "https://x.com/thsottiaux/status/2088103609477238858",
        "https://x.com/thsottiaux/status/2088019704803897705",
    ]
    assert calls[0]["proxies"]["https"] == "http://10.103.11.92:4780"


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


def test_collect_news_can_expand_lookback_for_recent_fallback(monkeypatch):
    now = datetime(2026, 8, 11, 21, 0, tzinfo=SHANGHAI)
    monkeypatch.setattr(
        tech_news,
        "call_glm",
        lambda *args, **kwargs: json.dumps(
            {
                "items": [
                    {
                        "title": "Recent verified release",
                        "publisher": "OpenAI",
                        "published_date": "2026-07-20",
                        "url": "https://openai.com/index/recent-verified-release/",
                        "summary": "OpenAI 官方近期发布新的 AI 能力。",
                        "why_it_matters": "值得关注。",
                        "entities": ["OpenAI"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    items = tech_news.collect_tech_news(
        _subscription(), now=now, verify_pages=False, lookback_days=30
    )
    assert [item["title"] for item in items] == ["Recent verified release"]


def test_delivery_dedupes_same_event_even_when_url_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(tech_news, "DB_PATH", tmp_path / "news.db")
    now = datetime(2026, 8, 11, 21, 0, tzinfo=SHANGHAI)
    original = {
        "title": "OpenAI releases GPT Next for developers",
        "summary": "OpenAI 发布 GPT Next，并向开发者开放新的 API 能力。",
        "publisher": "OpenAI",
        "entities": ["OpenAI", "GPT Next"],
        "url": "https://openai.com/index/gpt-next/",
    }
    tech_news._mark_news_run("oc_test", [original], now)
    delivered = tech_news._delivered_items("oc_test")
    repost = {
        **original,
        "title": "Introducing GPT Next for developers",
        "url": "https://x.com/OpenAI/status/123456",
    }
    assert tech_news._is_previously_delivered(repost, delivered) is True


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


def test_default_news_group_can_differ_from_paper_group(tmp_path, monkeypatch):
    monkeypatch.setattr(tech_news, "DB_PATH", tmp_path / "news.db")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_papers")
    monkeypatch.setenv("FEISHU_NEWS_CHAT_ID", "oc_news")
    tech_news.ensure_default_news_subscription()
    assert tech_news.get_news_subscription("oc_news", create=False) is not None
    assert tech_news.get_news_subscription("oc_papers", create=False) is None


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
                "category": "模型与研究",
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
    card = json.loads(content)
    assert card["header"]["title"]["content"] == "🌙 AI 科技情报 · 晚报"
    assert card["header"]["template"] == "indigo"
    assert "今晚速览" in content
    assert "模型与研究" in content
    assert "01 ·" in content
    assert "###" not in content
    assert "`1 条`" not in content
    assert "`1 类主题`" not in content


def test_digest_hides_image_alt_summary_and_renumbers_by_display_order(monkeypatch):
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
                "title": "Product update",
                "publisher": "Google AI/Gemini",
                "published_date": "2026-08-19",
                "url": "https://blog.google/product-update",
                "summary": 'an illustrated image with icons and phrasing like "Ask Google"',
                "why_it_matters": "",
                "category": "产品与 Agent",
                "entities": ["Google"],
                "source_type": "企业官方",
            },
            {
                "title": "Research update",
                "publisher": "Apple ML",
                "published_date": "2026-08-18",
                "url": "https://machinelearning.apple.com/research-update",
                "summary": "官方事实摘要。",
                "why_it_matters": "对模型研究具有参考价值。",
                "category": "模型与研究",
                "entities": ["Apple"],
                "source_type": "企业官方",
            },
        ],
        now=datetime(2026, 8, 20, 21, 0, tzinfo=SHANGHAI),
    )
    content = captured["json"]["content"]
    assert "01 · [Research update]" in content
    assert "02 · [Product update]" in content
    assert "an illustrated image" not in content
    assert "请点击标题查看官方原文" in content


def test_news_category_prefers_embodied_robotics_over_generic_model_words():
    assert tech_news._news_category(
        {
            "title": "New embodied robot model",
            "summary": "A humanoid robot learns a new control policy.",
            "entities": [],
        }
    ) == "机器人与具身"


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


def test_localize_news_summaries_translates_english_copy(monkeypatch):
    monkeypatch.setattr(
        tech_news,
        "call_glm",
        lambda *args, **kwargs: json.dumps(
            {
                "items": [
                    {
                        "id": 0,
                        "summary": "Google 发布了搜索学习功能更新，用户可以围绕已核验原文中介绍的工具完成学习任务。",
                        "why_it_matters": "该更新展示了 AI 搜索在学习场景中的产品化进展。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    items = tech_news._localize_news_summaries(
        [
            {
                "title": "5 new ways to level up your learning with Search",
                "publisher": "Google AI/Gemini",
                "summary": "Five new AI-powered learning features are now available in Search.",
                "why_it_matters": "",
            }
        ]
    )
    assert items[0]["summary"].startswith("Google 发布")
    assert "AI 搜索" in items[0]["why_it_matters"]
