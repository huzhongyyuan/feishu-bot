from intent_router import classify_intent


def test_food_recommendation_is_regular_chat():
    result = classify_intent(
        "深圳前海湾附近 深圳壹方城附近 推荐一些美食 不长胖且好吃的"
    )
    assert result["intent"] == "chat"


def test_travel_and_shopping_recommendations_are_regular_chat():
    assert classify_intent("哥本哈根有哪些好玩的")["intent"] == "chat"
    assert classify_intent("马尔默推荐一些购物的地方")["intent"] == "chat"


def test_explicit_paper_recommendations_still_use_paper_flow():
    assert classify_intent("推荐几篇 motion generation 论文")["intent"] == "paper_list"
    assert classify_intent("SIGGRAPH 2026 有哪些值得看的 paper")["intent"] == "paper_list"
    assert classify_intent("世界模型相关论文")["intent"] == "paper_list"
