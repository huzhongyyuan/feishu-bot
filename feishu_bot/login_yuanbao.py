from playwright.sync_api import sync_playwright


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    context = browser.new_context()

    page = context.new_page()

    page.goto(
        "https://yuanbao.tencent.com/"
    )

    input(
        "完成元宝登录后按回车"
    )

    context.storage_state(
        path="yuanbao_state.json"
    )

    browser.close()
