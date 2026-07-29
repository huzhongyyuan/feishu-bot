import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_token():

    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": os.getenv("FEISHU_APP_ID"),
            "app_secret": os.getenv("FEISHU_APP_SECRET")
        }
    )

    return r.json()["tenant_access_token"]



def send_message(chat_id, text):

    token = get_token()

    try:
        data = json.loads(text)
    except:
        data = {
            "title":"论文推荐",
            "summary":text,
            "contributions":[],
            "score":"-"
        }


    contributions = "\n".join(
        [
            f"• {x}"
            for x in data.get("contributions", [])
        ]
    )


    content = f"""
📚 {data.get('title','')}

🏷 {data.get('venue','')}

⭐ 推荐指数：{data.get('score','')}

**核心贡献**

{contributions}


**一句话总结**

{data.get('summary','')}
"""


    card = {
        "config":{
            "wide_screen_mode":True
        },
        "header":{
            "template":"blue",
            "title":{
                "tag":"plain_text",
                "content":"📚 每日论文推荐"
            }
        },
        "elements":[
            {
                "tag":"div",
                "text":{
                    "tag":"lark_md",
                    "content":content
                }
            }
        ]
    }


    r=requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",

        headers={
            "Authorization":f"Bearer {token}",
            "Content-Type":"application/json"
        },

        json={
            "receive_id":chat_id,
            "msg_type":"interactive",
            "content":json.dumps(card,ensure_ascii=False)
        }
    )


    print("[飞书返回]",r.text,flush=True)
