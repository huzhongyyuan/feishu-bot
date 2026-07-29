from playwright.sync_api import sync_playwright
import time


STATE_FILE = "yuanbao_state.json"


def ask_yuanbao(question):

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            storage_state=STATE_FILE
        )

        page = context.new_page()


        page.goto(
            "https://yuanbao.tencent.com/",
            wait_until="networkidle"
        )


        time.sleep(5)


        # 输入框
        box = page.locator(
            "textarea"
        )


        box.fill(question)

        page.keyboard.press("Enter")


        # 等待回答
        time.sleep(30)


        answer = page.locator(
            "body"
        ).inner_text()


        browser.close()


        return answer



if __name__ == "__main__":

    result = ask_yuanbao(
        "总结今天人工智能领域最重要的新闻"
    )

    print(result)
