# Undergraduate-student-page-notifier

RITSUMEIKAN STUDENT PORTAL の学部生ページが更新されると、Discord に通知が来ます。

## 動作

タスク スケジューラが 30 分おきに `check.py` を起動し、次の順に処理する。

1. 保存しておいたログイン状態（`auth.json`）で学部生ページを開く
2. 13 カテゴリのページを順に開き、各資料の「タイトル」と「最終更新日時」を読み取る
3. 前回の内容（`state.json`）と比べ、違いがあれば Discord に送る
4. 結果を `log.csv` に 1 行追記する

パスワードは保存しない。ポータルのセッションが切れても、Microsoft の「サインインの状態を維持する」で自動的にログインし直す。実行のたびに新しい Cookie を `auth.json` に保存し直す。

### 通知

| 状況 | 通知 |
| --- | --- |
| 資料が追加・更新・削除された | 変化のあったカテゴリと資料（リンク付き） |
| ログインが切れた | 「`python login.py` でログインし直してください」 |
| 読み取れない状態が 2 回続いた | 「ページの作りが変わった可能性があります」 |
| 上の 2 つから元に戻った | 「再び読み取れるようになりました」 |

同じ通知は、状態が変わるまで繰り返さない。初回の実行では、その時点の内容を記録するだけで通知しない。

## 導入

Python 3.9 以上と Google Chrome が必要。

```bash
git clone https://github.com/homescapes-fan/Undergraduate-student-page-notifier.git
```

```bash
cd Undergraduate-student-page-notifier
```

```bash
python -m venv .venv
```

```bash
source .venv/Scripts/activate
```

```bash
pip install -r requirements.txt
```

ブラウザは PC に入っている Google Chrome を使う（`channel="chrome"`）。Playwright が用意する Chromium は署名がなく、Windows のスマート アプリ コントロールに起動を止められることがあるため。そのため `playwright install` は不要。

### `.env`

`.env.exsample` をコピーして `.env` を作り、Discord の Webhook URL を入れる。

| 変数 | 取得方法 |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | チャンネルの編集 → 連携サービス → ウェブフック → 新しいウェブフック →「ウェブフック URL をコピー」 |

URL を知っている人は誰でも投稿できるので、公開しないこと。

### ログイン

```bash
python login.py
```

1. 開いたブラウザで、パスワード → Authenticator の 2 桁 → 「サインインの状態を維持しますか？」で**はい**
2. ポータルが表示されたら、ターミナルで Enter

「サインインの状態を維持」の Cookie（`ESTSAUTHPERSISTENT`）があるときだけ `auth.json` に保存する。**`auth.json` はログイン状態そのものなので、絶対に公開しないこと。**

## 実行

### 手動

```bash
python check.py --dry-run
```

通知も保存もせず、Discord に送る予定の内容を表示するだけ。動作確認に使う。

```bash
python check.py
```

自動実行と同じ処理（通知と保存あり）。

### 自動

タスク スケジューラの「タスクの作成」で、以下を登録する。

| タブ | 項目 | 設定 |
| --- | --- | --- |
| 全般 | セキュリティ オプション | ユーザーがログオンしているときのみ実行する |
| トリガー | 詳細設定 | 繰り返し間隔 30 分、継続時間 無期限 |
| 操作 | プログラム/スクリプト | `<リポジトリ>\.venv\Scripts\pythonw.exe` |
| 操作 | 引数の追加 | `check.py` |
| 操作 | 開始（オプション） | `<リポジトリ>` |
| 条件 | 電源 | 「AC 電源で使用している場合のみ」のチェックを外す |
| 設定 | タスクを停止するまでの時間 | 1 時間 |

`pythonw.exe` は画面を出さない Python。実行のたびに黒い画面が出るのを防ぐ。PC がスリープしている間は動かない。

## 運用

### 「ログインが切れました」が届いたとき

`python login.py` でログインし直す。次の自動実行から元に戻る。

### 「読み取れない状態が続いています」が届いたとき

`error.log` にエラーの詳細が残っている。大学がページの作りを変えた場合は、`check.py` の `read_portal` と `read_category` を直す必要がある。

## 構成

| ファイル | 役割 |
| --- | --- |
| `check.py` | 本体。定期実行される |
| `login.py` | 手動ログインと `auth.json` の保存 |
| `auth.json` | ログイン状態（Git 管理外） |
| `state.json` | 前回読み取った内容（Git 管理外） |
| `log.csv` | 実行ごとの日時・到達の成否・最後の URL（Git 管理外） |
| `error.log` | エラーの詳細（Git 管理外） |

## ページの読み取り方

- 学部生ページのタイル（`a[href*="category"]`）から 13 カテゴリの URL を集める。同じタイルが PC・タブレット・スマホ用に 3 組あるので、`:visible` で表示中の 1 組だけにする
- 各カテゴリの表は `td[data-label="タイトル"]` と `td[data-label="最終更新日時"]` の `data-cell-value` から読む
- 資料は「表示」のリンク（`/studentportal/s/r-content/<ID>`）の ID で見分ける。タイトルが変わっても同じ資料として扱える
- 中身が 0 件のカテゴリは「コンテンツがありません。」と表示される
- 見出しの `(4)` の件数と読めた行数を比べ、そろわないときは読み取り失敗として扱う（読み込み途中の表を見て「削除」と誤って通知しないため）
