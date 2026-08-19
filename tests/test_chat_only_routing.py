from unittest.mock import patch

import main


def test_configured_group_bypasses_paper_routing():
    with patch.dict(
        "os.environ",
        {"FEISHU_CHAT_ONLY_CHAT_IDS": "oc_chat,oc_other"},
        clear=False,
    ):
        assert main._is_chat_only_group("oc_chat") is True
        assert main._is_chat_only_group("oc_papers") is False


def test_empty_chat_only_config_matches_nothing():
    with patch.dict(
        "os.environ",
        {"FEISHU_CHAT_ONLY_CHAT_IDS": ""},
        clear=False,
    ):
        assert main._is_chat_only_group("oc_chat") is False
