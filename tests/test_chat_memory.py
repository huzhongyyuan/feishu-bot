import sys
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import chat_memory  # noqa: E402


def test_chat_memory_is_strictly_partitioned(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_memory, "DB_PATH", tmp_path / "memory.db")
    chat_memory.set_chat_profile("oc_digital", "数字人学习小组", "关注人体动作论文")
    chat_memory.set_chat_profile(
        "oc_news",
        "科技资讯群",
        "关注 AI 公司新闻",
        preferred_provider="yuanbao",
    )
    chat_memory.remember_chat_turn("oc_digital", "讨论 Motion", "关注动作生成")
    chat_memory.remember_chat_turn("oc_news", "OpenAI 新闻", "关注官方发布")

    digital = chat_memory.build_memory_prompt("oc_digital", "继续")
    news = chat_memory.build_memory_prompt("oc_news", "继续")
    assert "讨论 Motion" in digital
    assert "OpenAI 新闻" not in digital
    assert "OpenAI 新闻" in news
    assert "讨论 Motion" not in news
    assert chat_memory.preferred_chat_provider("oc_news") == "yuanbao"
    assert chat_memory.preferred_chat_provider("oc_digital") == "auto"


def test_chat_memory_retains_only_configured_recent_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_memory, "DB_PATH", tmp_path / "memory.db")
    for index in range(4):
        chat_memory.remember_chat_turn("oc_test", f"q{index}", f"a{index}")
    prompt = chat_memory.build_memory_prompt("oc_test", "next")
    assert "q0" in prompt
    monkeypatch.setenv("CHAT_MEMORY_CONTEXT_TURNS", "2")
    prompt = chat_memory.build_memory_prompt("oc_test", "next")
    assert "q0" not in prompt
    assert "q2" in prompt and "q3" in prompt
