from glm_client import call_glm
import json



def classify_intent(text):

    # ===== 最高优先级：论文推送 =====

    daily_keywords = [
        "推送论文",
        "推送今天论文",
        "今日论文",
        "论文日报",
        "推荐今天论文",
        "最新论文推荐"
    ]

    for k in daily_keywords:
        if k in text:
            return {
                "intent":"paper_daily",
                "is_paper_related":True,
                "confidence":1.0,
                "reason":"daily paper command"
            }


    weekly_keywords = [
        "总结本周论文",
        "论文周报",
        "本周论文",
        "最近论文总结"
    ]

    for k in weekly_keywords:
        if k in text:
            return {
                "intent":"paper_weekly",
                "is_paper_related":True,
                "confidence":1.0,
                "reason":"weekly paper command"
            }


    # ===== 第二优先级：论文分析 =====

    analysis_keywords = [
        "介绍",
        "分析",
        "讲一下",
        "这篇论文",
        "方法",
        "贡献",
        "创新点"
    ]


    if any(k in text for k in analysis_keywords):

        return {
            "intent":"paper_analysis",
            "is_paper_related":True,
            "confidence":1.0,
            "reason":"paper analysis"
        }


    # ===== 普通聊天交给LLM =====

    return {
        "intent":"chat",
        "is_paper_related":False,
        "confidence":1.0,
        "reason":"normal chat"
    }

