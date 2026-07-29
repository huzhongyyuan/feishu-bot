import re
import urllib.parse

import feedparser


ARXIV_API = "https://export.arxiv.org/api/query"


def _build_queries(text: str) -> list[str]:
    lower = text.casefold()

    # 数字人小组机器人中，未指定模态的“流式生成”
    # 默认解释为流式人体动作生成。
    if "流式" in text:
        if any(word in lower for word in ["llm", "大模型", "文本", "token"]):
            return [
                "streaming large language model generation",
                "speculative decoding language model",
                "online language model inference",
            ]

        if any(word in text for word in ["语音", "音频", "手势"]):
            return [
                "streaming speech gesture generation",
                "real-time co-speech gesture generation",
                "online audio driven motion generation",
            ]

        if "视频" in text:
            return [
                "streaming video generation",
                "autoregressive real-time video generation",
                "online video diffusion generation",
            ]

        return [
            "streaming human motion generation",
            "online human motion synthesis",
            "real-time human motion generation",
            "autoregressive human motion generation",
            "long-term human motion generation",
        ]

    # 其他论文调研：清理中文指令后作为查询词。
    topic = text

    for word in [
        "请帮我",
        "帮我",
        "推荐一些",
        "推荐几篇",
        "有哪些",
        "相关论文",
        "相关工作",
        "论文推荐",
        "文献推荐",
        "论文",
        "文献",
        "调研",
    ]:
        topic = topic.replace(word, " ")

    topic = re.sub(r"\s+", " ", topic).strip(" ，。！？、")

    return [topic] if topic else [text]


def _parse_feed(feed) -> list[dict]:
    papers = []

    for entry in getattr(feed, "entries", []):
        title = re.sub(r"\s+", " ", entry.title).strip()
        abstract = re.sub(r"\s+", " ", entry.summary).strip()

        match = re.search(
            r"(\d{4}\.\d{4,5})(?:v\d+)?",
            entry.link,
        )

        arxiv_id = match.group(1) if match else ""
        paper_url = (
            f"https://arxiv.org/abs/{arxiv_id}"
            if arxiv_id
            else entry.link
        )

        papers.append(
            {
                "id": arxiv_id,
                "title": title,
                "authors": [
                    author.name
                    for author in getattr(entry, "authors", [])
                ],
                "abstract": abstract,
                "summary": abstract,
                "paper_url": paper_url,
                "url": paper_url,
                "source": "arXiv",
            }
        )

    return papers


def _search_one(query: str, limit: int = 10) -> list[dict]:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", query.casefold())
        if len(token) >= 3
    ]

    if not tokens:
        return []

    # 先要求主要关键词同时出现。
    and_query = " AND ".join(
        f"all:{token}"
        for token in tokens
    )

    params = urllib.parse.urlencode(
        {
            "search_query": and_query,
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )

    feed = feedparser.parse(
        f"{ARXIV_API}?{params}"
    )

    papers = _parse_feed(feed)

    if papers:
        return papers

    # AND 无结果时使用宽松 OR 检索。
    or_query = " OR ".join(
        f"all:{token}"
        for token in tokens
    )

    params = urllib.parse.urlencode(
        {
            "search_query": or_query,
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )

    return _parse_feed(
        feedparser.parse(f"{ARXIV_API}?{params}")
    )


def search_topic_papers(
    text: str,
    limit: int = 4,
) -> list[dict]:

    queries = _build_queries(text)

    candidates = []
    seen = set()

    for query_index, query in enumerate(queries):
        print(
            "[PAPER LIST] query:",
            query,
            flush=True,
        )

        papers = _search_one(query, limit=10)

        query_tokens = {
            token
            for token in re.findall(
                r"[a-z0-9]+",
                query.casefold(),
            )
            if len(token) >= 3
        }

        for rank, paper in enumerate(papers):
            key = (
                paper.get("id")
                or paper.get("paper_url")
                or paper.get("title", "").casefold()
            )

            if not key or key in seen:
                continue

            seen.add(key)

            searchable = (
                paper.get("title", "")
                + " "
                + paper.get("abstract", "")
            ).casefold()

            overlap = sum(
                token in searchable
                for token in query_tokens
            )

            # 标题命中权重更高。
            title_lower = paper.get("title", "").casefold()
            title_overlap = sum(
                token in title_lower
                for token in query_tokens
            )

            paper["_score"] = (
                title_overlap * 20
                + overlap * 5
                - query_index * 2
                - rank
            )

            candidates.append(paper)

    candidates.sort(
        key=lambda item: item.get("_score", 0),
        reverse=True,
    )

    selected = candidates[:limit]

    for paper in selected:
        paper.pop("_score", None)

    return selected
