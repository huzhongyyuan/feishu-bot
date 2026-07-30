from apscheduler.schedulers.blocking import BlockingScheduler

from daily_paper import daily_push


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        daily_push,
        "cron",
        hour=8,
        minute=0,
        id="daily_paper_push",
        replace_existing=True,
    )
    return scheduler


if __name__ == "__main__":
    print("Scheduler started: daily at 08:00 Asia/Shanghai", flush=True)
    build_scheduler().start()
