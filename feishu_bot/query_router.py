from glm_client import call_glm
import json


def route_query(text):

    prompt = f"""
判断用户问题是否需要联网。

用户：
{text}

返回JSON:

{{
"need_search":true,
"type":"paper|latest|chat",
"query":""
}}

规则：

需要联网：
- 具体论文
- 最新论文
- 作者信息
- 论文链接
- code
- 项目主页
- 新模型

例如：
介绍Uni3C论文
true

不需要：
- Transformer原理
- RoPE原理
- 扩散模型基础

false
"""

    result = call_glm(prompt)

    try:
        return json.loads(result)

    except:
        return {
            "need_search":False,
            "type":"chat",
            "query":""
        }
