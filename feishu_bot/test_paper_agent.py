import os
import re
import feedparser
from dotenv import load_dotenv
from zai import ZhipuAiClient


load_dotenv()


def fetch_arxiv(url):

    match = re.findall(
        r'abs/([\d.]+)',
        url
    )

    if not match:
        raise ValueError(
            "不是有效 arxiv URL"
        )

    paper_id = match[0]

    print("arxiv id:", paper_id)

    feed_url = (
        "https://export.arxiv.org/api/query"
        f"?id_list={paper_id}"
    )

    feed = feedparser.parse(
        feed_url
    )

    if not feed.entries:
        raise Exception(
            "arxiv 查询失败"
        )

    entry = feed.entries[0]

    return {
        "id": paper_id,
        "title": entry.title.strip(),
        "authors": [
            a.name
            for a in entry.authors
        ],
        "abstract": entry.summary.strip(),
        "link": url
    }



def summarize_paper(paper):

    api_key = os.environ.get(
        "ZAI_API_KEY"
    )

    if not api_key:
        raise Exception(
            "没有找到 ZAI_API_KEY"
        )


    client = ZhipuAiClient(
        api_key=api_key
    )


    prompt = f"""
你是一名计算机视觉领域顶级研究员。

请深度分析下面论文：

论文标题：
{paper['title']}

作者：
{paper['authors']}

论文链接：
{paper['link']}

摘要：
{paper['abstract']}


请按照以下结构输出：

# 1. 研究背景

说明研究问题、
已有方法不足。


# 2. 核心方法

详细解释：

- 整体框架
- 输入输出
- 模型结构
- 关键模块


# 3. 技术创新

总结3-5个主要贡献。


# 4. 实验分析

说明：

- 数据集
- Baseline
- 指标
- 主要结果


# 5. 局限性

分析不足。


# 6. 对数字人/视频生成方向启发

重点分析：

- Human Motion
- Camera Control
- Video Generation
- 未来研究机会


要求：

面向计算机视觉博士研究者，
保持技术细节。
"""


    response = client.chat.completions.create(
        model="glm-4.5",
        messages=[
            {
                "role":"user",
                "content":prompt
            }
        ]
    )


    return (
        response
        .choices[0]
        .message
        .content
    )



if __name__ == "__main__":

    url = (
        "https://arxiv.org/abs/2504.14899"
    )


    print("="*50)
    print("获取论文信息")
    print("="*50)


    paper = fetch_arxiv(url)


    print("\nTitle:")
    print(
        paper["title"]
    )


    print("\nAuthors:")
    print(
        paper["authors"]
    )


    print("\n" + "="*50)
    print("GLM分析中...")
    print("="*50)


    result = summarize_paper(
        paper
    )


    print("\n" + "="*50)
    print("论文分析结果")
    print("="*50)


    print(result)
