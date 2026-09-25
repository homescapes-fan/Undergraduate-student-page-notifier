from playwright.sync_api import sync_playwright, TimeoutError
from datetime import datetime

URL = "https://sp.ritsumei.ac.jp/studentportal/s/student10"

with sync_playwright() as p:
    success = True
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        page.goto(URL)
        page.wait_for_url(URL+"**", timeout=25000)
    except TimeoutError:
        success = False

    if success:
        print(page.url)
        context.storage_state(path="auth.json")
    else:
        print("失敗")

    time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    url = page.url.split("?")[0]

    line = f"{time}, {success}, {url}"
    print(line)

    with open("log.csv", "a", encoding="utf-8") as f:
        f.write(line+"\n")

