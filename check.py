"""学部生ページの更新を調べて、変化があれば Discord に通知する。

タスク スケジューラから 30 分おきに実行される。

    python check.py             通常の実行（通知と保存あり）
    python check.py --dry-run   通知も保存もせず、送る予定の内容を表示するだけ
"""
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# このファイルがあるフォルダを基準にする。どこから実行しても同じファイルを使うため
BASE = Path(__file__).parent
AUTH = BASE / "auth.json"
STATE = BASE / "state.json"
LOG = BASE / "log.csv"
ERROR_LOG = BASE / "error.log"

URL = "https://sp.ritsumei.ac.jp/studentportal/s/student10"
EMPTY_TEXT = "コンテンツがありません。"

# Discord は 1 回 2000 文字まで。余裕を持たせる
DISCORD_LIMIT = 1900
# 読み取りの失敗がこの回数続いたら通知する（1 回だけの一時的な失敗では騒がない）
ERROR_NOTIFY_AFTER = 2


class ReadError(Exception):
    """ページが想定どおりに読み取れなかったとき"""


# ---------------------------------------------------------------- 読み取り

def read_category(page, name, url):
    """カテゴリのページを開き、{資料の ID: {"title", "updated", "url"}} を返す"""
    page.goto(url)

    rows = page.locator("tr").filter(has=page.locator('td[data-label="タイトル"]')).filter(visible=True)
    empty = page.get_by_text(EMPTY_TEXT).filter(visible=True)

    # 表の行か「コンテンツがありません。」のどちらかが出るまで待つ
    rows.or_(empty).first.wait_for(timeout=20000)
    if rows.count() == 0:
        return {}

    # 見出しの「(4)」の件数と、読めた行数がそろうまで待つ（読み込み途中で数えないため）
    expected = None
    for _ in range(20):
        match = re.search(rf"{re.escape(name)}\s*\((\d+)\)", page.locator("body").inner_text())
        expected = int(match.group(1)) if match else None
        if expected is None or rows.count() == expected:
            break
        page.wait_for_timeout(500)
    if expected is not None and rows.count() != expected:
        raise ReadError(f"{name}: 見出しは {expected} 件なのに、表は {rows.count()} 行でした")

    items = {}
    for row in rows.all():
        title = row.locator('td[data-label="タイトル"]').get_attribute("data-cell-value")
        updated = row.locator('td[data-label="最終更新日時"]').get_attribute("data-cell-value")
        view = row.locator('a[href*="/r-content/"]')
        if view.count():
            href = view.first.get_attribute("href")
            item_id = href.rstrip("/").split("/")[-1]
            item_url = urljoin(page.url, href)
        else:
            # 「表示」のリンクがない行は、タイトルで見分ける
            item_id = title
            item_url = url
        items[item_id] = {"title": title, "updated": updated, "url": item_url}
    return items


def read_portal(page):
    """13 カテゴリすべてを読み、{"category01": {"name", "url", "items"}, ...} を返す"""
    links = page.locator('a[href*="category"]:visible')
    links.first.wait_for(timeout=20000)

    # ページを移動するとリンクが使えなくなるので、先に名前と URL をメモしておく
    categories = []
    for link in links.all():
        name = link.inner_text().strip().replace("\n", "")
        url = urljoin(page.url, link.get_attribute("href"))
        categories.append((name, url))

    result = {}
    for name, url in categories:
        key = url.rstrip("/").split("/")[-1]
        result[key] = {"name": name, "url": url, "items": read_category(page, name, url)}
    return result


# ---------------------------------------------------------------- 比較

def escape(text):
    """Discord の装飾記号（_ や * など）を、ただの文字として表示させる。
    リンクの文字の中では \\ がそのまま見えてしまうので、リンクの外でだけ使う"""
    return re.sub(r"([\\*_~`|\[\]>])", r"\\\1", text)


def link_label(text):
    """リンクの文字に使う。リンクの書き方を壊す [ ] だけを全角に置き換える"""
    return text.replace("[", "［").replace("]", "］")


def find_changes(old, new):
    """前回と今回を比べ、Discord に送る行のリストを返す。変化がなければ空"""
    lines = []
    for key in sorted(set(old) | set(new)):
        category = new.get(key) or old[key]
        before = old.get(key, {}).get("items", {})
        after = new.get(key, {}).get("items", {})

        changes = []
        for item_id, item in after.items():
            # 資料名はリンクの外に書き（_ などを正しく表示するため）、「追加」「更新」の文字をリンクにする
            title = escape(item["title"])
            url = item["url"]
            if item_id not in before:
                changes.append(f"・[追加](<{url}>)：{title}（{item['updated']}）")
            elif item != before[item_id]:
                prev = before[item_id]
                details = []
                if prev["updated"] != item["updated"]:
                    details.append(f"{prev['updated']} → {item['updated']}")
                if prev["title"] != item["title"]:
                    details.append(f"旧タイトル：{escape(prev['title'])}")
                changes.append(f"・[更新](<{url}>)：{title}（{'、'.join(details)}）")
        for item_id, item in before.items():
            if item_id not in after:
                changes.append(f"・削除：{escape(item['title'])}")

        if changes:
            lines.append("")
            lines.append(f"**[{link_label(category['name'])}](<{category['url']}>)**")
            lines.extend(changes)
    return lines


def split_messages(lines):
    """Discord の文字数制限に収まるように、行の区切りで分ける"""
    messages = [""]
    for line in lines:
        if len(messages[-1]) + len(line) + 1 > DISCORD_LIMIT:
            messages.append("")
        messages[-1] += line + "\n"
    return [m for m in messages if m.strip()]


# ---------------------------------------------------------------- 通知・保存

def send(text, dry_run):
    if dry_run:
        print("----- Discord に送る予定の内容 -----")
        print(text)
        return
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError(".env に DISCORD_WEBHOOK_URL がありません")
    response = requests.post(
        webhook,
        json={"content": text, "allowed_mentions": {"parse": []}},
        timeout=15,
    )
    response.raise_for_status()


def load_state():
    if STATE.exists():
        with STATE.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    # 書き込み途中で止まってもファイルが壊れないように、別名で書いてから置き換える
    temp = STATE.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    temp.replace(STATE)


def write_log(success, url):
    time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time}, {success}, {url.split('?')[0]}\n")


def write_error_log():
    time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with ERROR_LOG.open("a", encoding="utf-8") as f:
        f.write(f"===== {time} =====\n{traceback.format_exc()}\n")


# ---------------------------------------------------------------- 全体の流れ

def main():
    dry_run = "--dry-run" in sys.argv
    load_dotenv(BASE / ".env")
    state = load_state()

    with sync_playwright() as p:
        # Playwright の Chromium は署名がなく、Windows のスマート アプリ コントロールに
        # 止められることがあるので、PC に入っている Google Chrome を使う
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(storage_state=str(AUTH))
        page = context.new_page()

        # 1. 学部生ページまでたどり着けるか（ログインが生きているか）
        # 時間切れのほか、ネットにつながっていないときのエラーも「たどり着けなかった」とする
        reached = True
        try:
            page.goto(URL)
            page.wait_for_url(URL + "**", timeout=25000)
        except PlaywrightError:
            reached = False
        final_url = page.url
        print("到達:", reached, final_url.split("?")[0])
        if not dry_run:
            write_log(reached, final_url)

        # 2. たどり着けたら、新しい Cookie を保存してから中身を読む
        new = None
        if reached:
            if not dry_run:
                context.storage_state(path=str(AUTH))
            try:
                new = read_portal(page)
            except Exception:
                write_error_log()
                print(traceback.format_exc())
        browser.close()

    # 3. 状態を決める
    if new is not None:
        status = "ok"
    elif not reached and "login.microsoftonline.com" in final_url:
        status = "login"
    else:
        status = "error"
    fail_count = 0 if status == "ok" else state.get("fail_count", 0) + 1

    # 4. 状態が変わったときだけ知らせる（30 分ごとに同じ通知を繰り返さない）
    previous = state.get("status", "ok")
    notice = None
    if status == "login" and previous != "login":
        notice = "⚠️ ポータルのログインが切れました。PC で `python login.py` を実行して、ログインし直してください。"
    elif status == "error" and previous == "ok" and fail_count >= ERROR_NOTIFY_AFTER:
        notice = "⚠️ 学部生ページを読み取れない状態が続いています。ページの作りが変わった可能性があります。詳しくは `error.log` を見てください。"
    elif status == "ok" and previous != "ok":
        notice = "✅ 学部生ページを再び読み取れるようになりました。"
    if notice:
        send(notice, dry_run)

    # 5. 中身を比べて、変化があれば知らせる
    if new is not None:
        old = state.get("categories")
        if old is None:
            count = sum(len(c["items"]) for c in new.values())
            print(f"初回のため、今の内容（{len(new)} カテゴリ、{count} 件）を記録するだけにします")
        else:
            lines = find_changes(old, new)
            if lines:
                lines.insert(0, "学部生ページが更新されました**")
                for message in split_messages(lines):
                    send(message, dry_run)
            else:
                print("変化はありませんでした")
        state["categories"] = new

    # 6. 状態を保存する。通知に失敗したときはここまで来ないので、次回また通知される
    # （エラーが続いている間は、エラーの通知を出すまで "ok" のまま数え続ける）
    if status == "error" and notice is None and previous == "ok":
        state["status"] = "ok"
    else:
        state["status"] = status
    state["fail_count"] = fail_count
    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # pythonw.exe で動いているときはエラーが画面に出ないので、ファイルに残す
        write_error_log()
        raise
