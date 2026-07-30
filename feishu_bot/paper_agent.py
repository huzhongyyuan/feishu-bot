from glm_client import call_glm
import json


def analyze_paper(paper):

    prompt=f"""
你是计算机视觉论文专家。

论文：

标题:
{paper.get("title")}

作者:
{paper.get("authors")}

摘要:
{paper.get("summary")}

链接:
{paper.get("url")}


严格返回JSON:

{{
"title":"",
"venue":"",
"abstract":"",
"summary":"",
"contributions":[],
"score":0,
"paper_url":"",
"code_url":"",
"method":"",
"insight":""
}}

要求：
- paper_url必须填写
- 不确定code写空
- 不要Markdown
"""

    result=call_glm(prompt)

    try:
        return json.loads(result)

    except:
        return {
            "title":paper.get("title"),
             "abstract":paper.get("summary"),
            "summary":paper.get("summary"),
            "paper_url":paper.get("url"),
            "contributions":[]
        }
