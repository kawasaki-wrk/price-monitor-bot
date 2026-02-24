# Price Monitor Bot

指定した商品の価格を定期チェックし、**値下がり**または**目標価格到達**時に Slack / Discord へ通知するボットです。

## 公開に関する注意

- `.env`（Webhook URL）は**絶対に公開しない**でください。漏洩した場合は Slack/Discord 側で Webhook を作り直して無効化してください。
- `products.json` / `state.json` はローカル実行用（実行時に更新/生成）です。リポジトリには含めない運用を推奨します（`.gitignore` で除外）。

## 利用規約・取得制限について

- 監視対象サイトの利用規約（スクレイピング/自動化/アクセス頻度など）に従って利用してください。
- Amazon 等のサイトでは Bot 判定や表示差分により、価格取得が失敗する場合があります（その場合はセレクタ調整や運用見直しが必要です）。

## 技術スタック

- Python 3
- Selenium
- BeautifulSoup
- Slack Incoming Webhook
- Discord Webhook

## 1. セットアップ

```bash
cd /home/kawasaki/project/price-monitor-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 設定ファイル作成

### 2-1. 通知先設定

```bash
cp .env.example .env
```

`.env` を編集:

- `SLACK_WEBHOOK_URL=`
- `DISCORD_WEBHOOK_URL=`

どちらか片方だけでも可。両方設定すると両方に送信します。

### 2-2. 監視対象設定

```bash
cp products.example.json products.json
```

`products.json` の `products` 配列に監視対象を追加します。

- `name`: 識別名
- `url`: 商品ページURL
- `selector`: 価格要素の CSS セレクタ
- `wait_selector`: 読み込み待機用セレクタ（通常は `selector` と同じで可）
- `attribute`: 価格が属性値にある場合のみ指定（通常は `null`）
- `target_price`: 目標価格（この価格以下になったタイミングでも通知）

## 3. 実行

```bash
python main.py
```

初回実行は価格の基準値を保存するだけで、通知は行いません。

## 通知条件

- 前回価格より安くなったとき
- `target_price` を初めて下回ったとき

状態は `state.json` に保存されます。

## ダッシュボード（GUI）

価格データ（`state.json`）を表で確認できます。

```bash
streamlit run streamlit_app.py
```

## よくあるトラブル

- Chrome / ChromeDriver が見つからない:
  - `.env` の `CHROME_BINARY` / `CHROMEDRIVER_PATH` を設定
- 価格が取れない:
  - `selector` を再確認（動的描画やログイン必須ページだと要調整）
- 通知が飛ばない:
  - Webhook URL の貼り間違い、チャンネル設定を確認
