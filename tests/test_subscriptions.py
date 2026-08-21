import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import subscriptions  # noqa: E402


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_db_path = subscriptions.DB_PATH
        subscriptions.DB_PATH = Path(self.temp_dir.name) / "subscriptions.db"
        self.addCleanup(setattr, subscriptions, "DB_PATH", self.original_db_path)

    def test_subscription_commands(self):
        reply = subscriptions.handle_subscription_command(
            "oc_test",
            "订阅 世界模型、视频生成、人体动作",
        )
        self.assertIn("世界模型、视频生成、人体动作", reply)

        reply = subscriptions.handle_subscription_command(
            "oc_test",
            "推送时间 07:00、20:00",
        )
        self.assertIn("07:00、20:00", reply)

        reply = subscriptions.handle_subscription_command("oc_test", "工作日推送")
        self.assertIn("仅工作日", reply)

        reply = subscriptions.handle_subscription_command("oc_test", "暂停论文推送")
        self.assertIn("已暂停", reply)

        reply = subscriptions.handle_subscription_command("oc_test", "查看订阅")
        self.assertIn("状态：已暂停", reply)

    def test_default_subscription_includes_panorama_topics(self):
        subscription = subscriptions.get_subscription("oc_panorama")
        self.assertIn("数字人", subscription["topics"])
        self.assertIn("Motion Generation", subscription["topics"])
        self.assertIn("具身智能", subscription["topics"])
        self.assertIn("全景相机", subscription["topics"])
        self.assertIn("全景视频", subscription["topics"])
        self.assertIn("多模态", subscription["topics"])
        self.assertIn("多模态理解生成统一", subscription["topics"])
        self.assertIn("视觉 Agent（图像/视频/3D）", subscription["topics"])

    def test_due_subscription_respects_time_and_weekday(self):
        subscriptions.update_subscription(
            "oc_test",
            push_times=["07:00", "20:00"],
            weekdays_only=True,
            enabled=True,
        )
        monday = datetime(2026, 8, 3, 7, 0, tzinfo=subscriptions.SHANGHAI)
        monday_late = datetime(2026, 8, 3, 20, 1, tzinfo=subscriptions.SHANGHAI)
        monday_early = datetime(2026, 8, 3, 6, 59, tzinfo=subscriptions.SHANGHAI)
        saturday = datetime(2026, 8, 8, 20, 1, tzinfo=subscriptions.SHANGHAI)
        self.assertEqual(
            [item["due_push_time"] for item in subscriptions.due_subscriptions(monday)],
            ["07:00"],
        )
        self.assertEqual(len(subscriptions.due_subscriptions(monday_late)), 2)
        self.assertEqual(len(subscriptions.due_subscriptions(monday_early)), 0)
        self.assertEqual(len(subscriptions.due_subscriptions(saturday)), 0)

        subscriptions.mark_pushed("oc_test", "2026-08-03", "07:00")
        self.assertEqual(
            [item["due_push_time"] for item in subscriptions.due_subscriptions(monday_late)],
            ["20:00"],
        )
        subscriptions.mark_pushed("oc_test", "2026-08-03", "20:00")
        self.assertEqual(len(subscriptions.due_subscriptions(monday_late)), 0)

    def test_invalid_time_is_rejected(self):
        reply = subscriptions.handle_subscription_command(
            "oc_test",
            "推送时间 25:99",
        )
        self.assertIn("格式不正确", reply)

    def test_failed_daily_attempt_has_retry_backoff(self):
        subscriptions.update_subscription(
            "oc_retry",
            push_times=["08:00"],
            weekdays_only=False,
            enabled=True,
        )
        now = datetime(2026, 8, 3, 8, 5, tzinfo=subscriptions.SHANGHAI)
        subscriptions.mark_daily_attempt("oc_retry", "08:00", "2026-08-03")
        with subscriptions._connect() as conn:
            conn.execute(
                """
                UPDATE daily_subscription_attempts SET attempted_at=?
                WHERE chat_id=? AND run_date=? AND push_time=?
                """,
                (now.isoformat(), "oc_retry", "2026-08-03", "08:00"),
            )
        due = subscriptions.due_subscriptions(now)
        self.assertNotIn("oc_retry", {item["chat_id"] for item in due})

        later = now + timedelta(minutes=subscriptions.DAILY_RETRY_MINUTES + 1)
        due = subscriptions.due_subscriptions(later)
        self.assertIn("oc_retry", {item["chat_id"] for item in due})

    def test_weekly_roundup_runs_once_with_retry_backoff(self):
        subscriptions.update_subscription("oc_test", enabled=True)
        monday_early = datetime(2026, 8, 3, 8, 59, tzinfo=subscriptions.SHANGHAI)
        monday_due = datetime(2026, 8, 3, 9, 0, tzinfo=subscriptions.SHANGHAI)
        monday_retry = datetime(2026, 8, 3, 15, 1, tzinfo=subscriptions.SHANGHAI)
        self.assertEqual(
            subscriptions.due_weekly_subscriptions(monday_early),
            [],
        )
        due = subscriptions.due_weekly_subscriptions(monday_due)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["weekly_run_key"], "2026-08-03")

        subscriptions.mark_weekly_attempt("oc_test", "2026-08-03")
        self.assertEqual(
            subscriptions.due_weekly_subscriptions(monday_due),
            [],
        )
        subscriptions.mark_weekly_failed("oc_test", "2026-08-03", "temporary")
        # The test clock is detached from mark_weekly_attempt's real clock;
        # overwrite the attempt timestamp to assert the six-hour retry boundary.
        with subscriptions._connect() as conn:
            conn.execute(
                "UPDATE weekly_subscription_runs SET attempted_at=?",
                ("2026-08-03T09:00:00+08:00",),
            )
        self.assertEqual(
            len(subscriptions.due_weekly_subscriptions(monday_retry)),
            1,
        )
        subscriptions.mark_weekly_attempt("oc_test", "2026-08-03")
        subscriptions.mark_weekly_completed("oc_test", "2026-08-03")
        self.assertEqual(
            subscriptions.due_weekly_subscriptions(monday_retry),
            [],
        )

    def test_weekly_roundup_does_not_backfill_days_late(self):
        subscriptions.update_subscription("oc_test", enabled=True)
        thursday = datetime(2026, 8, 6, 11, 0, tzinfo=subscriptions.SHANGHAI)
        self.assertEqual(
            subscriptions.due_weekly_subscriptions(thursday),
            [],
        )


if __name__ == "__main__":
    unittest.main()
