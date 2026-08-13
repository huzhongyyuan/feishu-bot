import re


def classify_intent(text: str) -> dict:
    normalized = re.sub(r"\s+", " ", text).strip()
    lower = normalized.casefold()

    daily_words = [
        "推送今天论文",
        "推送论文",
        "今日论文",
        "每日论文",
        "论文日报",
    ]

    if any(word in normalized for word in daily_words):
        return {
            "intent": "paper_daily",
            "is_paper_related": True,
            "need_search": True,
            "confidence": 1.0,
        }

    weekly_words = [
        "上周推荐的论文",
        "上周论文",
        "上周推荐论文",
        "本周论文总结",
        "总结本周论文",
        "论文周报",
        "论文月报",
    ]

    if any(word in normalized for word in weekly_words):
        return {
            "intent": "paper_weekly",
            "is_paper_related": True,
            "need_search": False,
            "confidence": 1.0,
        }

    # 在该机器人中，“推荐/调研/有哪些/相关工作”默认指论文。
    list_words = [
        "推荐一些",
        "推荐几篇",
        "推荐一篇",
        "有哪些",
        "相关论文",
        "相关工作",
        "文献推荐",
        "论文推荐",
        "调研",
        "研究现状",
        "研究进展",
        "最新进展",
        "技术路线",
        "survey",
        "related work",
        "literature review",
    ]

    if any(word in lower for word in list_words):
        return {
            "intent": "paper_list",
            "is_paper_related": True,
            "need_search": True,
            "confidence": 1.0,
        }

    if "arxiv.org/" in lower:
        return {
            "intent": "paper_analysis",
            "is_paper_related": True,
            "need_search": True,
            "confidence": 1.0,
        }

    paper_analysis_words = [
        "这篇论文",
        "论文贡献",
        "论文方法",
        "论文摘要",
        "论文链接",
        "论文代码",
    ]

    if any(word in normalized for word in paper_analysis_words):
        return {
            "intent": "paper_analysis",
            "is_paper_related": True,
            "need_search": True,
            "confidence": 1.0,
        }

    # “介绍 Uni3C”“分析 InfiniteDance”。
    has_english_name = bool(
        re.search(r"[A-Za-z][A-Za-z0-9_.+\-]{2,}", normalized)
    )
    has_analysis_action = any(
        word in normalized
        for word in [
            "介绍",
            "分析",
            "讲一下",
            "讲讲",
            "贡献",
            "创新点",
        ]
    )

    if has_english_name and has_analysis_action:
        return {
            "intent": "paper_analysis",
            "is_paper_related": True,
            "need_search": True,
            "confidence": 0.98,
        }

    return {
        "intent": "chat",
        "is_paper_related": False,
        "need_search": False,
        "confidence": 1.0,
    }
