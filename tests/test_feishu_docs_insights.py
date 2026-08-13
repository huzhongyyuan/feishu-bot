import feishu_docs
from feishu_docs import _append_deep_images, _core_insight_lines, _figure_insight_for


def test_core_insights_separate_facts_from_editor_interpretation():
    lines = _core_insight_lines(
        [
            {
                "finding": "模块 A 提升指标。",
                "why_it_matters": "收益来自针对性设计。",
                "transfer": "可先做小规模模块验证。",
                "source": "PDF p.6 / Table 1",
            }
        ]
    )
    assert "Insight 1" in lines[0]
    assert "编辑解读" in lines[0]
    assert "原文事实 · PDF p.6 / Table 1" in lines[0]


def test_figure_insight_matches_selected_figure_number():
    paper = {
        "figure_insights": [
            {"figure_number": 3, "what_it_shows": "关键结果"},
            {"figure_number": 5, "what_it_shows": "消融实验"},
        ]
    }
    assert _figure_insight_for(paper, 5)["what_it_shows"] == "消融实验"
    assert _figure_insight_for(paper, 2) == {}


def test_append_deep_image_keeps_caption_and_interpretation(monkeypatch):
    requests = []
    uploaded = []

    def fake_request(method, path, token, **kwargs):
        requests.append(kwargs.get("json", {}))
        children = kwargs.get("json", {}).get("children", [])
        if children and children[0].get("block_type") == 27:
            return {
                "data": {
                    "children": [{"block_type": 27, "block_id": "image-block"}]
                }
            }
        return {"data": {"children": []}}

    monkeypatch.setattr(feishu_docs, "_request", fake_request)
    monkeypatch.setattr(
        feishu_docs,
        "_upload_docx_image",
        lambda *args: uploaded.append(args),
    )
    monkeypatch.setattr(feishu_docs.time, "sleep", lambda *args: None)

    _append_deep_images(
        "token",
        "document",
        {
            "figure_insights": [
                {
                    "figure_number": 2,
                    "what_it_shows": "展示核心模块。",
                    "why_it_matters": "支持方法主张。",
                    "reading_tip": "关注两条信息流。",
                }
            ]
        },
        [
            {
                "path": "/tmp/figure.jpg",
                "figure_number": 2,
                "page_number": 4,
                "label": "网络 / 方法架构图 · Figure 2",
                "caption": "Figure 2. Full architecture caption.",
                "width": 720,
                "height": 360,
            }
        ],
    )

    assert uploaded and uploaded[0][2] == "image-block"
    serialized = str(requests)
    assert "Figure 2. Full architecture caption." in serialized
    assert "支持方法主张" in serialized
    assert "PDF p.4 / Figure 2" in serialized
