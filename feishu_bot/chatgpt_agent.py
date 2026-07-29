from playwright.sync_api import sync_playwright
import time


STATE_FILE = "chatgpt_state.json"


def ask_chatgpt(question):

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            storage_state=STATE_FILE
        )

        page = context.new_page()

        page.goto(
            "https://chatgpt.com",
            wait_until="networkidle"
        )

        time.sleep(5)

        box = page.locator("textarea")

        box.fill(question)

        page.keyboard.press("Enter")

        time.sleep(30)

        result = page.locator(
            "body"
        ).inner_text()

        browser.close()

        return result


if __name__ == "__main__":
    print(
        ask_chatgpt(
            "总结今天AI领域最重要的新闻"
        )
    )
