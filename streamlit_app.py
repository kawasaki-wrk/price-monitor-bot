import io
import json
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
PRODUCTS_FILE = BASE_DIR / "products.json"


st.set_page_config(page_title="価格監視ダッシュボード", layout="centered")
st.title("📊 商品価格 監視ダッシュボード")


def load_products() -> list[dict]:
    if not PRODUCTS_FILE.exists():
        return []
    with PRODUCTS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return list(data.get("products", []))


def save_products(products: list[dict]) -> None:
    payload = {"products": products}
    with PRODUCTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def load_state_table() -> pd.DataFrame:
    if not STATE_FILE.exists():
        return pd.DataFrame([])

    with STATE_FILE.open("r", encoding="utf-8") as file:
        state_data = json.load(file)

    table_data: list[dict[str, str]] = []
    for name, info in state_data.items():
        dt = datetime.fromtimestamp(info["updated_at"]).strftime("%Y/%m/%d %H:%M")
        table_data.append(
            {
                "商品名": name,
                "現在価格": f"¥{info['last_price']:,.0f}",
                "最終更新": dt,
                "商品URL": info["url"],
            }
        )

    return pd.DataFrame(table_data)


def run_bot_once() -> str:
    import main as bot_main

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        bot_main.main()
    return buffer.getvalue().strip()


tab_results, tab_settings = st.tabs(["結果", "設定"])

with tab_results:
    st.subheader("操作")
    st.caption("cron の自動巡回とは別に、手動で最新価格を取得します")

    if st.button("今すぐ更新", type="primary"):
        with st.spinner("価格を取得中..."):
            try:
                output = run_bot_once()
                if output:
                    st.success("更新完了")
                    st.code(output)
                else:
                    st.success("更新完了")
            except Exception as exc:
                st.error(f"更新に失敗しました: {exc}")

    st.divider()

    st.subheader("最新結果")
    df = load_state_table()
    if df.empty:
        st.warning("まだデータがありません。監視ボットを動かしてください。")
    else:
        st.dataframe(df)

with tab_settings:
    st.subheader("監視設定（products.json）")

    products = load_products()
    if not products:
        st.info("まだ監視対象がありません。下のフォームから追加してください。")

    names = [p.get("name", "") for p in products if p.get("name")]
    selected_name = st.selectbox(
        "編集/削除する商品（任意）",
        options=[""] + names,
        index=0,
        help="既存設定を編集する場合に選択します。新規追加だけなら空のままでOKです。",
    )

    selected_product: dict | None = None
    if selected_name:
        for p in products:
            if p.get("name") == selected_name:
                selected_product = p
                break

    with st.form("product_form"):
        st.caption("最低限『商品名・URL・セレクタ』を入力してください")

        name = st.text_input("商品名", value=(selected_product or {}).get("name", ""))
        url = st.text_input("商品URL", value=(selected_product or {}).get("url", ""))
        selector = st.text_input(
            "価格セレクタ（CSS）",
            value=(selected_product or {}).get("selector", ""),
            help="例: span[data-pricetopay-label]",
        )
        target_price = st.number_input(
            "目標価格（任意）",
            min_value=0,
            value=int((selected_product or {}).get("target_price") or 0),
            step=1,
        )

        submitted = st.form_submit_button(
            "保存（追加/更新）",
            type="primary",
        )

    if submitted:
        if not name.strip() or not url.strip() or not selector.strip():
            st.error("商品名・URL・セレクタは必須です")
        else:
            new_item = {
                "name": name.strip(),
                "url": url.strip(),
                "selector": selector.strip(),
                "wait_selector": selector.strip(),
                "attribute": None,
                "target_price": int(target_price) if target_price > 0 else None,
            }

            updated = False
            for i, p in enumerate(products):
                if p.get("name") == (selected_product or {}).get("name") and selected_name:
                    products[i] = new_item
                    updated = True
                    break
            if not updated:
                products.append(new_item)

            save_products(products)
            st.success("保存しました")
            st.rerun()

    if selected_name and selected_product:
        if st.button("削除", type="secondary"):
            products = [p for p in products if p.get("name") != selected_name]
            save_products(products)
            st.success("削除しました")
            st.rerun()
