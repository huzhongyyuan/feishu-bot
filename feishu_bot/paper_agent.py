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
"summary_en":"",
"abstract_zh":"",
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
- summary 使用约220至340个中文字符的中文导读，覆盖问题、方法、关键结果和阅读价值，只能依据摘要
- summary_en 使用100至160个英文单词，与中文导读语义和结论强度一致
- abstract_zh 是输入英文摘要的完整忠实中文翻译，不删减、不添加结论
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
            "summary_en":"",
            "abstract_zh":"",
            "paper_url":paper.get("url"),
            "contributions":[]
        }
