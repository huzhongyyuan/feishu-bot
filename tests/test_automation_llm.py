import automation_llm
import chatgpt_agent
import codex_automation
import yuanbao_agent


def test_automation_llm_uses_yuanbao_raw_mode_by_default(monkeypatch):
    captured = {}
    monkeypatch.delenv("AUTOMATION_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(
        yuanbao_agent,
        "ask_yuanbao",
        lambda question, **kwargs: captured.update(
            {"question": question, **kwargs}
        )
        or '{"ok":true}',
    )

    result = automation_llm.call_automation_llm(
        "严格返回 JSON",
        timeout=240,
        web_search=True,
        search_prompt="只查官方来源",
    )

    assert result == '{"ok":true}'
    assert captured["raw"] is True
    assert captured["timeout"] == 240
    assert "只查官方来源" in captured["question"]


def test_automation_llm_can_explicitly_use_glm(monkeypatch):
    monkeypatch.setenv("AUTOMATION_LLM_PROVIDER", "glm")
    monkeypatch.setattr(
        automation_llm,
        "call_zai_glm",
        lambda prompt, **kwargs: "glm-result",
    )

    assert automation_llm.call_automation_llm("hello") == "glm-result"


def test_automation_llm_can_use_chatgpt_web(monkeypatch):
    captured = {}
    monkeypatch.setenv("AUTOMATION_LLM_PROVIDER", "chatgpt")
    monkeypatch.setattr(
        chatgpt_agent,
        "ask_chatgpt",
        lambda question, **kwargs: captured.update(
            {"question": question, **kwargs}
        )
        or '{"ok":true}',
    )

    result = automation_llm.call_automation_llm(
        "严格返回 JSON",
        timeout=240,
        web_search=True,
        search_prompt="只查官方仓库",
    )

    assert result == '{"ok":true}'
    assert captured["timeout"] == 240
    assert "必须联网检索" in captured["question"]
    assert "只查官方仓库" in captured["question"]


def test_automation_llm_can_use_server_codex(monkeypatch):
    captured = {}
    monkeypatch.setenv("AUTOMATION_LLM_PROVIDER", "codex")
    monkeypatch.setattr(
        codex_automation,
        "ask_codex",
        lambda question, **kwargs: captured.update(
            {"question": question, **kwargs}
        )
        or '{"ok":true}',
    )

    result = automation_llm.call_automation_llm(
        "严格返回 JSON",
        timeout=240,
        web_search=True,
        search_prompt="只查官方仓库",
    )

    assert result == '{"ok":true}'
    assert captured["timeout"] == 240
    assert "核验最新公开信息" in captured["question"]
    assert "只查官方仓库" in captured["question"]
