import json
from pathlib import Path
from automation_llm import call_automation_llm as call_glm


CONFIG = json.loads(
    Path(__file__).resolve().with_name("paper_config.json").read_text()
)


def parse_json_object(value):
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1], strict=False)
        raise


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
- 两条入选路径：大厂/头部实验室且具通用 AI 影响力，或与数字人、Motion Generation、具身智能、世界模型、视频、多模态及理解生成统一、图像/视频/3D 视觉 Agent 高度相关
- 大公司研究院、头部实验室、顶级高校/研究机构和顶会影响力
- 创新性
- 技术深度
- 实验可信度
- 对实验室项目价值

大厂通用 AI 论文不因超出当前重点方向而被过滤。质量相近时，明确优先大厂/头部机构、官方代码已开源且社区影响力更高的论文。
"""

    try:
        result = call_glm(prompt, timeout=180)
        return parse_json_object(result)
    except Exception as exc:
        print(f"论文评分失败: {exc}", flush=True)
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
