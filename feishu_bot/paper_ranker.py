import json
from pathlib import Path
from main import call_glm


CONFIG = json.loads(
    Path("paper_config.json").read_text()
)


def rank_paper(paper):

    prompt = f"""
你是实验室论文筛选专家。

关注方向：
{CONFIG["domains"]}

请评分下面论文：

标题：
{paper.get("title")}

摘要：
{paper.get("summary")}

严格返回JSON：

{{
"score":0,
"reason":"",
"keep":true
}}

评分考虑：
- 与研究方向相关性
- 创新性
- 技术深度
- 实验可信度
- 对实验室项目价值
"""

    result = call_glm(prompt)

    try:
        return json.loads(result)
    except:
        return {
            "score":0,
            "keep":False,
            "reason":"解析失败"
        }


def filter_papers(papers):

    results=[]

    for p in papers:
        score = rank_paper(p)

        if (
            score.get("keep")
            and score.get("score",0)
            >= CONFIG["min_score"]
        ):
            p.update(score)
            results.append(p)

    results.sort(
        key=lambda x:x.get("score",0),
        reverse=True
    )

    return results[:CONFIG["daily_count"]]
