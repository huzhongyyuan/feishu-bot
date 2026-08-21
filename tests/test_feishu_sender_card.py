import json

import pytest

import feishu_sender
from feishu_sender import compact_card_text, mini_panel


def test_compact_card_text_normalizes_and_truncates():
    value = compact_card_text("  核心   方法  " + "长" * 20, limit=12)
    assert value.startswith("核心 方法")
    assert value.endswith("…")
    assert len(value) == 12


def test_mini_panel_is_visible_and_bordered():
    panel = mini_panel("💡 核心贡献", "1. 贡献")
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is True
    assert panel["border"]["corner_radius"] == "6px"
    assert panel["elements"][0]["text"]["content"] == "1. 贡献"


def test_teaser_and_architecture_are_visible_in_expected_positions(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(feishu_sender, "get_token", lambda: "token")
    monkeypatch.setattr(feishu_sender, "upload_image", lambda *args: "image-key")
    monkeypatch.setattr(feishu_sender.requests, "post", fake_post)
    monkeypatch.setattr(
        "paper_media.prepare_paper_images",
        lambda data: [
            {
                "path": "/tmp/teaser.jpg",
                "kind": "teaser",
                "label": "Figure 1",
                "caption": "Figure 1. Complete teaser caption.",
            },
            {
                "path": "/tmp/architecture.jpg",
                "kind": "architecture",
                "label": "Figure 2",
                "caption": "Figure 2. Overview of our network architecture.",
            },
        ],
    )

    feishu_sender.send_message(
        "oc_test",
        json.dumps(
            {
                "title": "Paper",
                "summary": "这是一段更完整的中文导读。",
                "keywords": ["Motion Generation", "Diffusion", "Long Sequence"],
                "one_line_insight": "分层时序建模的核心价值，是把长序列中的误差累积拆解到不同时间尺度。",
                "summary_en": "This is the paired English reading guide.",
                "abstract_zh": "这是英文摘要的完整中文翻译。",
                "abstract": "This is the official English abstract.",
                "venue": "SIGGRAPH Asia 2026",
                "contributions": ["中文贡献"],
                "main_method": "核心网络方法。",
                "authors": ["Author"],
                "paper_url": "https://arxiv.org/abs/2608.00001",
                "code_url": "https://github.com/org/paper",
                "code_host": "GitHub",
                "repo_stars": 100,
                "llm_open_source_verified": True,
                "open_source_verified": True,
                "large_team_verified": True,
                "team_evidence": "作者团队 6 人",
                "feishu_doc_url": "https://my.feishu.cn/docx/library",
                "research_question": {
                    "text": "如何提高长序列动作生成的稳定性？",
                    "source": "PDF p.1 / Abstract",
                },
                "background": [
                    {"text": "现有方法存在误差累积。", "source": "PDF p.2 / Sec. 1"}
                ],
                "method_result_map": [
                    {
                        "method": "分层时序建模",
                        "result": "在长序列基准上降低误差",
                        "source": "PDF p.6 / Table 1",
                    }
                ],
                "key_results": [
                    {"text": "关键指标提升 5%。", "source": "PDF p.6 / Table 1"}
                ],
                "writing_notes": [
                    {"text": "先定位失败模式，再逐层验证模块。", "source": "编辑解读 · PDF p.2–7"}
                ],
                "core_insights": [
                    {
                        "finding": "长序列收益主要来自分层建模。",
                        "why_it_matters": "它隔离了误差累积来源。",
                        "transfer": "适合先验证时间尺度拆分。",
                        "source": "PDF p.6 / Table 1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    card = json.loads(captured["json"]["content"])
    assert card["elements"][0]["tag"] == "div"
    assert (
        "🏷 [SIGGRAPH Asia 2026](https://arxiv.org/abs/2608.00001)"
        in card["elements"][0]["text"]["content"]
    )
    assert "开源代码" in card["elements"][1]["text"]["content"]
    assert "https://github.com/org/paper" in card["elements"][1]["text"]["content"]
    assert "Teaser" in card["elements"][2]["text"]["content"]
    assert card["elements"][3]["tag"] == "img"
    assert "Complete teaser caption" in card["elements"][4]["elements"][0]["content"]
    summary_index = next(
        index
        for index, element in enumerate(card["elements"])
        if element.get("tag") == "div"
        and "中文导读" in element.get("text", {}).get("content", "")
    )
    keywords_index = next(
        index
        for index, element in enumerate(card["elements"])
        if element.get("tag") == "div"
        and "Keywords" in element.get("text", {}).get("content", "")
    )
    insight_index = next(
        index
        for index, element in enumerate(card["elements"])
        if element.get("tag") == "div"
        and "一句话 Insight" in element.get("text", {}).get("content", "")
    )
    architecture_index = next(
        index
        for index, element in enumerate(card["elements"])
        if element.get("tag") == "div"
        and "网络 / 方法架构图" in element.get("text", {}).get("content", "")
    )
    assert keywords_index > 4
    assert keywords_index < insight_index < summary_index
    assert "Motion Generation · Diffusion · Long Sequence" in card["elements"][keywords_index]["text"]["content"]
    assert "长序列中的误差累积" in card["elements"][insight_index]["text"]["content"]
    assert architecture_index > summary_index
    assert card["elements"][architecture_index + 1]["tag"] == "img"
    deep_panel = next(
        element
        for element in card["elements"]
        if element.get("tag") == "collapsible_panel"
        and "深度拆解" in element.get("header", {}).get("title", {}).get("content", "")
    )
    assert deep_panel["expanded"] is False
    assert "研究问题" in str(deep_panel["elements"])
    assert "核心贡献" in str(deep_panel["elements"])
    assert "核心方法" in str(deep_panel["elements"])
    assert any("方法 ↔ 实验结果" in str(element) for element in deep_panel["elements"])
    actions = next(element for element in card["elements"] if element.get("tag") == "action")
    assert any(
        action["text"]["content"] == "📚 图文深度解析"
        for action in actions["actions"]
    )
    assert any("可带走的 Insight" in str(element) for element in deep_panel["elements"])
    detail_panel = next(
        element
        for element in card["elements"]
        if element.get("tag") == "collapsible_panel"
        and "双语摘要" in element.get("header", {}).get("title", {}).get("content", "")
    )
    detail_text = str(detail_panel["elements"])
    assert "English Guide" in detail_text
    assert "摘要 · 中文翻译" in detail_text
    assert "Abstract · English Original" in detail_text


def test_paper_card_is_not_sent_without_two_images(monkeypatch):
    monkeypatch.setattr(feishu_sender, "get_token", lambda: "token")
    monkeypatch.setattr("paper_media.prepare_paper_images", lambda data: [])
    posted = []
    monkeypatch.setattr(feishu_sender.requests, "post", lambda *args, **kwargs: posted.append(1))

    with pytest.raises(RuntimeError, match="已取消发送"):
        feishu_sender.send_message(
            "oc_test",
            json.dumps(
                {
                    "title": "Paper Without Images",
                    "paper_url": "https://arxiv.org/abs/2608.00001",
                    "code_url": "https://github.com/org/paper",
                    "llm_open_source_verified": True,
                    "open_source_verified": True,
                    "large_team_verified": True,
                }
            ),
        )
    assert posted == []


def test_unverified_open_source_paper_is_not_sent(monkeypatch):
    monkeypatch.setattr(feishu_sender, "get_token", lambda: "token")
    with pytest.raises(RuntimeError, match="核验"):
        feishu_sender.send_message(
            "oc_test",
            json.dumps(
                {
                    "title": "Unverified Paper",
                    "code_url": "https://github.com/random/reimplementation",
                }
            ),
        )


def test_manual_no_code_exception_is_clearly_labelled(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    captured = {}
    monkeypatch.setattr(feishu_sender, "get_token", lambda: "token")
    monkeypatch.setattr(feishu_sender, "upload_image", lambda *args: "image-key")
    monkeypatch.setattr(
        feishu_sender.requests,
        "post",
        lambda *args, **kwargs: captured.update(kwargs) or Response(),
    )
    monkeypatch.setattr(
        "paper_media.prepare_paper_images",
        lambda data: [
            {"path": "/tmp/teaser.jpg", "kind": "teaser", "label": "Figure 1", "caption": "Figure 1"},
            {"path": "/tmp/architecture.jpg", "kind": "architecture", "label": "Figure 2", "caption": "Figure 2"},
        ],
    )
    feishu_sender.send_message(
        "oc_test",
        json.dumps(
            {
                "title": "Closed-code Paper",
                "paper_url": "https://arxiv.org/abs/2607.15038",
                "venue": "arXiv",
                "manual_no_code_exception": True,
                "large_team_verified": True,
            }
        ),
    )
    card = json.loads(captured["json"]["content"])
    content = str(card)
    assert "官方代码尚未发布" in content
    assert "不引用第三方复现" in content
    assert "查看代码" not in content


def test_paper_button_identifies_arxiv_link():
    assert (
        feishu_sender.paper_link_label("https://arxiv.org/abs/2603.16666")
        == "📄 arXiv 链接"
    )
    assert (
        feishu_sender.paper_link_label("https://openaccess.thecvf.com/paper")
        == "📄 官方论文页"
    )
