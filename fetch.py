from playwright.sync_api import sync_playwright, TimeoutError
from datetime import datetime
from urllib.parse import urljoin

URL = "https://sp.ritsumei.ac.jp/studentportal/s/student10"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    context = browser.new_context(storage_state="auth.json")
    page = context.new_page()

    page.goto(URL)
    page.wait_for_url(URL+"**", timeout=25000)

    links = page.locator('a[href*="category"]:visible')
    links.first.wait_for()
    categories = []

    for link in links.all():
        name = link.inner_text().strip().replace("\n", "")
        href = link.get_attribute("href")
        category_url = urljoin("https://sp.ritsumei.ac.jp/studentportal/s/student10", f"{href}")
        print(name, href)
        categories.append({"name" : name, "url" : category_url})

    print(categories)
    page.goto(categories[1]["url"])
    input("enter押せ")

