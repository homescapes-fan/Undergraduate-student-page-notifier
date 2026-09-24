from playwright.sync_api import sync_playwright

URL = "https://sp.ritsumei.ac.jp/studentportal/s/student10"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    page.goto(URL)
    input("ログインが終わったら Enter")
    cookies = context.cookies()

    found = False
    for cookie in cookies:
        if cookie["name"] == "ESTSAUTHPERSISTENT":
            found = True

    if found:
        context.storage_state(path="auth.json")
        print("保存しました")
    else :
        print("cookieが見つかりませんでした")
