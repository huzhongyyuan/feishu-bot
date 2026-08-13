from daily_paper import daily_push
from paper_archive import archive_unstored_papers
from subscriptions import (
    due_subscriptions,
    due_weekly_subscriptions,
    ensure_default_subscription,
    mark_pushed,
    mark_weekly_attempt,
    mark_weekly_completed,
    mark_weekly_failed,
)
from tech_news import dispatch_due_tech_news, ensure_default_news_subscription


def dispatch_due_subscriptions() -> None:
    ensure_default_subscription()
    ensure_default_news_subscription()
    for subscription in due_subscriptions():
        chat_id = subscription["chat_id"]
        try:
            daily_push(chat_id=chat_id, topics=subscription["topics"])
        except Exception as exc:
            print(
                f"每日论文推送失败，将稍后重试: {exc}",
                flush=True,
            )
        else:
            mark_pushed(chat_id, push_time=subscription["due_push_time"])
    for subscription in due_weekly_subscriptions():
        chat_id = subscription["chat_id"]
        run_key = subscription["weekly_run_key"]
        mark_weekly_attempt(chat_id, run_key)
        try:
            from weekly_paper import weekly_push

            count = weekly_push(chat_id=chat_id, topics=subscription["topics"])
        except Exception as exc:
            mark_weekly_failed(chat_id, run_key, str(exc))
            print(
                f"每周四类论文推送失败，{6} 小时后重试: {exc}",
                flush=True,
            )
        else:
            mark_weekly_completed(chat_id, run_key)
            print(f"每周四类论文推送完成: {count} 篇", flush=True)
    try:
        archive_unstored_papers()
    except Exception as exc:
        print(f"飞书论文库后台补档失败，将稍后重试: {exc}", flush=True)
    try:
        count = dispatch_due_tech_news()
        if count:
            print(f"AI 科技晚报发送完成: {count} 条", flush=True)
    except Exception as exc:
        print(f"AI 科技晚报调度失败，将稍后重试: {exc}", flush=True)


if __name__ == "__main__":
    dispatch_due_subscriptions()
