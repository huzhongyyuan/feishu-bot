from feishu_sender import send_message as send_feishu_message
from glm_client import call_glm
from paper_db import init_db, paper_exists, save_paper
from paper_ranker import filter_papers
from dotenv import load_dotenv
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from datetime import datetime


load_dotenv()


LIBRARY = "paper_library.json"


def load_library():

    if not os.path.exists(LIBRARY):
        return []

    with open(
        LIBRARY,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f).get("papers", [])



def save_library(papers):

    with open(
        LIBRARY,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "papers": papers
            },
            f,
            ensure_ascii=False,
            indent=2
        )





def get_hf_daily():

    url = "https://hf-mirror.com/api/daily_papers"

    try:
        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent":"Mozilla/5.0"
            }
        )

        r.raise_for_status()

        papers=[]

        for item in r.json()[:5]:

            paper=item.get("paper",{})

            papers.append({
                "title": paper.get("title",""),
                "summary": paper.get("summary",""),
                "paper_url":
                    "https://hf-mirror.com/papers/"
                    + paper.get("id",""),
                "source":"HF"
            })

        print(
            "HF获取成功:",
            len(papers),
            flush=True
        )

        return papers

    except Exception as e:

        print(
            "HF失败:",
            e,
            flush=True
        )

        return []



def get_arxiv_daily():

    import feedparser

    url = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.CV"
        "&start=0"
        "&max_results=5"
        "&sortBy=submittedDate"
    )

    try:

        feed = feedparser.parse(url)

        papers=[]

        for item in feed.entries:

            papers.append({
                "title": item.title,
                "summary": item.summary,
                "paper_url": item.link,
                "source":"arXiv"
            })


        print(
            "arxiv获取成功:",
            len(papers),
            flush=True
        )

        return papers

    except Exception as e:

        print(
            "arxiv失败:",
            e,
            flush=True
        )

        return []



def get_daily_papers():

    papers=[]

    # 暂时关闭HF，服务器访问不稳定
    # papers.extend(
    #     get_hf_daily()
    # )

    papers.extend(
        get_arxiv_daily()
    )


    seen=set()
    result=[]

    for p in papers:

        title=p.get("title","")

        if title and title not in seen:
            seen.add(title)
            result.append(p)


    print(
        "最终候选:",
        len(result),
        flush=True
    )

    return result[:10]


def remove_duplicate(papers):

    library = load_library()

    old_titles = {
        p["title"]
        for p in library
    }


    return [
        p
        for p in papers
        if p["title"] not in old_titles
    ]



def analyze_paper(paper):

    prompt=f"""
你是顶会论文推荐专家。

分析论文：

标题:
{paper['title']}

摘要:
{paper['summary']}


严格返回JSON:

{{
"title":"",
"venue":"",
"summary":"",
"contributions":[],
"score":0,
"paper_url":"",
"code_url":""
}}
"""


    result=call_glm(prompt)


    try:
        data=json.loads(result)

    except:

        data={
            "title":paper["title"],
            "summary":paper["summary"],
            "contributions":[],
            "score":0
        }


    data["paper_url"]=paper.get(
        "paper_url",
        ""
    )

    data["code_url"]=paper.get(
        "code_url",
        ""
    )

    return data



def daily_push():

    init_db()


    print("抓取论文...",flush=True)


    papers=get_daily_papers()


    print(
        "候选数量:",
        len(papers),
        flush=True
    )


    papers=[
        p for p in papers
        if not paper_exists(p.get('title',''))
    ]


    print(
        "去重后:",
        len(papers),
        flush=True
    )


    analyzed=[]


    # 并发GLM分析，最多10篇
    with ThreadPoolExecutor(max_workers=5) as executor:

        futures = [
            executor.submit(
                analyze_paper,
                paper
            )
            for paper in papers[:10]
        ]

        for future in as_completed(futures):

            try:
                result = future.result()
                analyzed.append(result)

            except Exception as e:
                print(
                    "论文分析失败:",
                    e,
                    flush=True
                )


    selected=filter_papers(
        analyzed
    )


    # 最多推荐4篇
    selected=selected[:4]


    library=load_library()


    for paper in selected:


        send_feishu_message(
            os.getenv("FEISHU_CHAT_ID"),
            json.dumps(
                paper,
                ensure_ascii=False
            )
        )


        paper["push_time"] = (
            datetime.now()
            .strftime("%Y-%m-%d")
        )

        library.append(
            paper
        )


    save_library(
        library
    )


    print(
        "今日推荐:",
        len(selected),
        flush=True
    )



if __name__=="__main__":
    daily_push()
