from playwright.sync_api import sync_playwright


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    context = browser.new_context()

    page = context.new_page()

    page.goto(
        "https://chatgpt.com"
    )

    input(
        "请完成登录，然后回车保存"
    )

    context.storage_state(
        path="chatgpt_state.json"
    )

    browser.close()
