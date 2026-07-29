from apscheduler.schedulers.blocking import BlockingScheduler
from paper_agent import daily_papers
from feishu_sender import send_message
import json


GROUP_FILE="data/groups.json"


def run_daily():

    print("开始日报")

    papers=daily_papers()

    with open(GROUP_FILE) as f:
        groups=json.load(f)["groups"]


    text="📚 今日论文推荐\n\n"

    for i,p in enumerate(papers):

        text+=f"""
{i+1}. {p['title']}

链接:
{p['url']}

分析:
{p['analysis']}

----------------
"""


    for g in groups:

        if g.get("enabled"):

            send_message(
                g["chat_id"],
                text
            )


scheduler=BlockingScheduler()


scheduler.add_job(
    run_daily,
    "cron",
    hour=8,
    minute=0
)


print("Scheduler started")

scheduler.start()
