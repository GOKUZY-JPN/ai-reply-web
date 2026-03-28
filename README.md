# AI Reply MVP

ログインは人手で行い、その後に Web サイト上のメッセージを読み取って AI で返信を生成し、フォームへ入力して送信する MVP です。

今は通常の Google Chrome 上で使う半自動版も入っています。Tandem のように自動ブラウザを嫌うサイトでは、こちらの方が扱いやすいです。
スマホ向けには Web アプリ版も使えます。

## できること

- 初回セットアップ時にブラウザ上の要素をクリックしてセレクタを保存
- 保存したセレクタでメッセージ本文を取得
- OpenAI API で返信案を生成
- 返信欄へ入力して送信

## 前提

- Python 3.13 以上
- OpenAI API キー
- 初回は `playwright` のインストールが必要

## セットアップ

```bash
cd /Users/kosuketamai/Downloads/ai-reply-mvp
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
```

`.env` を編集して `OPENAI_API_KEY` を入れてください。

## 使い方

### 1. セレクタを登録する

```bash
python3 app.py setup
```

ブラウザが開いたら:

1. 自分でログインする
2. 返信したい画面を開く
3. ターミナルの案内に従って
   - 最新メッセージ
   - 返信入力欄
   - 送信ボタン
   の順にクリックする

### 2. 実行する

```bash
python3 app.py run
```

必要に応じて `--dry-run` を付けると送信せず、返信生成まで確認できます。

```bash
python3 app.py run --dry-run
```

## 補足

- 同じブラウザプロフィールを使うので、2回目以降はログイン状態を引き継げます
- サイトによってはセレクタを取り直した方が安定します
- 返信を自動送信したくない場合は `--dry-run` で文面だけ確認できます

## 通常 Chrome で使う半自動版

拡張機能は [chrome-extension](/Users/kosuketamai/Downloads/ai-reply-mvp/chrome-extension) にあります。

### インストール

1. Chrome で `chrome://extensions` を開く
2. 右上の「デベロッパーモード」を ON
3. 「パッケージ化されていない拡張機能を読み込む」
4. `/Users/kosuketamai/Downloads/ai-reply-mvp/chrome-extension` を選ぶ
5. 拡張機能の「詳細」から「拡張機能のオプション」を開く
6. OpenAI API Key を保存する
7. `Model` はまず `gpt-5-mini` を使う
8. `Reference Guide` に固定の返信方針を入れておくと、毎回その基準で返答できる
9. 相手ごとに `App Name` `Country` `Partner Name` `Sequence` を入れる
10. `Conversation Database For Current Partner` に、その相手との会話全文を貼って保存できる

### 使い方

1. Tandem を通常の Chrome で開く
2. 返信欄を一度クリックする
3. 拡張機能を開いて `返信欄を記憶`
4. 相手のメッセージ本文をマウスで選択する
5. 拡張機能を開いて `選択文を取得`
6. `返信を生成`
7. 生成された返信と日本語訳を確認する
8. `入力欄に入れる`
9. 内容を見て、自分で送信する

### この方式のポイント

- ログインや閲覧は普段の Chrome をそのまま使う
- 自動送信ではなく、最後の確認は自分でできる
- サイト構造の変化に少し強い
- GPT-5 系モデルでは `temperature` を自動で送らないようにしてあります
- 返信文とその日本語訳を同時に確認できます
- 相手は `app__country__name__number` 形式で識別され、同名相手でも分けて管理できます
- 相手ごとの会話DBを参照し、返信生成のたびに新しい相手文と生成返信も追記します

## Web アプリ版

Web アプリ本体は [webapp.py](/Users/kosuketamai/Downloads/ai-reply-mvp/webapp.py) です。

### ローカル起動

```bash
cd /Users/kosuketamai/Downloads/ai-reply-mvp
python3 webapp.py
```

その後、ブラウザで `http://127.0.0.1:5050` を開きます。

### GitHub → Railway で公開する

API キーをブラウザ側に置かず、Railway のサーバー環境変数にだけ保存したい場合はこの形が安全です。

1. このフォルダを GitHub に push する
2. Railway で `Deploy from GitHub repo` を選ぶ
3. この repo を接続する
4. Railway の Variables に以下を設定する

```text
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
OPENAI_VISION_MODEL=gpt-4.1-mini
OPENAI_TEMPERATURE=0.7
FLASK_SECRET_KEY=十分長いランダム文字列
DATABASE_URL=Railway が発行した Postgres URL
DATABASE_PATH=/data/reply_site.db
```

5. 必要なら Railway 側の Start Command を `gunicorn webapp:app --bind 0.0.0.0:$PORT` にする
6. ドメインを発行して、スマホからそのURLにアクセスする

### セキュリティ

- API キーは GitHub に入れない
- `.env` はローカル専用にする
- 本番では Railway の Variables にだけ保存する

### データ永続化

Railway でプロフィールDBが消える場合は、コンテナ内のローカルファイルを使っているのが原因です。いちばん簡単なのは **Railway Volume + SQLite のまま永続化** です。

1. Railway で Volume を追加する
2. たとえば `/data` にマウントする
3. Variables に以下を入れる

```text
DATABASE_PATH=/data/reply_site.db
```

これで SQLite ファイルが Volume 上に保存され、再デプロイ後も残ります。

Google Sheets よりこの方法の方が簡単です。構成もほぼ変えず、今の Web アプリのまま使えます。

### さらに確実に残したいなら Railway Postgres

今のアプリは `DATABASE_URL` がある場合、自動で Postgres を使います。Railway で Postgres を追加して、その接続URLを `DATABASE_URL` として渡せば、再デプロイでもプロフィールDBと会話DBは消えません。

おすすめ優先順位:

1. **Railway Postgres**
2. Railway Volume + SQLite
3. Google Sheets

### スクショからプロフィール取り込み

Web アプリ版では、相手プロフィールのスクショをアップロードして

- App Name
- Country
- Partner Name
- Sequence
- プロフィールメモ

を抽出し、保存前にフォームへ自動入力できます。
