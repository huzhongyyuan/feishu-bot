import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_token():

    r=requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id":
            os.getenv("FEISHU_APP_ID"),

            "app_secret":
            os.getenv("FEISHU_APP_SECRET")
        }
    )

    return r.json()["tenant_access_token"]



def send_message(chat_id,text):

    token=get_token()

    requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",

        headers={
            "Authorization":
            f"Bearer {token}",
            "Content-Type":
            "application/json"
        },

        json={
            "receive_id":chat_id,
            "msg_type":"text",
            "content":
            json.dumps({
                "text":text
            })
        }
    )
