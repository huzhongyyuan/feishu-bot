import requests
import feedparser
import os
import json
from dotenv import load_dotenv

load_dotenv()

ZAI_API_KEY=os.getenv("ZAI_API_KEY")


KEYWORDS=[
    "digital human",
    "motion generation",
    "world model",
    "video generation",
    "animation",
    "avatar",
    "human motion",
    "multimodal"
]


def collect_arxiv():

    url="https://export.arxiv.org/api/query?search_query=cat:cs.CV&start=0&max_results=20"

    feed=feedparser.parse(url)

    papers=[]

    for item in feed.entries:

        text=(
            item.title+
            item.summary
        ).lower()

        score=sum(
            1 for k in KEYWORDS
            if k in text
        )

        if score>0:

            papers.append({
                "title":item.title,
                "summary":item.summary,
                "url":item.link
            })

    return papers



def glm_score(paper):

    prompt=f"""
你是计算机视觉顶会专家。

分析论文:

标题:
{paper['title']}

摘要:
{paper['summary']}


请输出:

推荐评分(0-10)
创新性
技术价值
适合数字人/视频生成方向程度

JSON格式。
"""

    r=requests.post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={
            "Authorization":
            f"Bearer {ZAI_API_KEY}",
            "Content-Type":
            "application/json"
        },
        json={
            "model":"glm-5.2",
            "messages":[
                {
                    "role":"user",
                    "content":prompt
                }
            ]
        },
        timeout=60
    )

    return r.json()["choices"][0]["message"]["content"]



def daily_papers():

    papers=collect_arxiv()

    result=[]

    for p in papers[:5]:

        p["analysis"]=glm_score(p)

        result.append(p)

    return result
