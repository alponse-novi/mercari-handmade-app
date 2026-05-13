import time
import math
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import cache_manager
import mercari_client
from keywords import extract_top_keywords

st.set_page_config(
    page_title="メルカリ ハンドメイド売れ筋調査",
    page_icon="🧵",
    layout="wide",
)

# ─── 認証 ────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        "<h2 style='text-align:center; margin-top:80px;'>🧵 メルカリ ハンドメイド売れ筋調査</h2>",
        unsafe_allow_html=True,
    )
    col = st.columns([1, 1.2, 1])[1]
    with col:
        st.markdown("#### パスワードを入力してください")
        pw = st.text_input("パスワード", type="password", key="login_pass")
        if st.button("ログイン", use_container_width=True, type="primary"):
            if pw == st.secrets["auth"]["password"]:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("パスワードが違います")
    st.stop()

CATEGORIES = list(mercari_client.CATEGORIES.keys())
CACHE_KEY = lambda cat: f"{cat}_v3"

# ─── サイドバー ───────────────────────────────────────────
with st.sidebar:
    st.title("🧵 売れ筋調査")
    if st.button("ログアウト", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    st.markdown("---")

    selected_categories = st.multiselect(
        "カテゴリー選択",
        options=CATEGORIES,
        default=CATEGORIES,
    )

    st.markdown("---")
    force_refresh = st.button("🔄 データ更新", use_container_width=True)

    st.markdown("### 最終更新")
    for cat in CATEGORIES:
        ts = cache_manager.last_updated(CACHE_KEY(cat))
        if ts:
            minutes_ago = int((time.time() - ts) / 60)
            label = f"{minutes_ago}分前" if minutes_ago < 60 else f"{int(minutes_ago/60)}時間前"
        else:
            label = "未取得"
        st.caption(f"{cat}: {label}")

    st.markdown("---")
    st.caption("⚠️ 個人調査用途のみ。商用利用不可。")


# ─── データ取得 ───────────────────────────────────────────
@st.cache_data(ttl=7200, show_spinner=False)
def load_category(category: str, _refresh_key: int) -> dict:
    key = CACHE_KEY(category)
    cached = cache_manager.get(key)
    if cached is not None:
        return cached
    data = mercari_client.fetch_category(category)
    if data.get("items") or data.get("sold_items"):
        cache_manager.set(key, data)
    return data


if force_refresh:
    for cat in CATEGORIES:
        cache_manager.clear(CACHE_KEY(cat))
    st.cache_data.clear()

refresh_key = int(time.time() / 7200)

all_items: list[dict] = []
all_sold_items: list[dict] = []

if selected_categories:
    progress = st.progress(0, text="データ取得中...")
    for i, cat in enumerate(selected_categories):
        progress.progress((i + 1) / len(selected_categories), text=f"{cat} 取得中...")
        data = load_category(cat, refresh_key)
        all_items.extend(data.get("items", []))
        all_sold_items.extend(data.get("sold_items", []))
    progress.empty()

# ─── メインコンテンツ ──────────────────────────────────────
st.title("🧵 メルカリ ハンドメイド売れ筋調査")

if not all_items and not all_sold_items:
    st.warning("カテゴリーを選択してください。または、データ更新ボタンを押してください。")
    st.stop()

df = pd.DataFrame(all_items) if all_items else pd.DataFrame()
df = df[df["price"] > 0].copy() if not df.empty else df
sold_df_raw = pd.DataFrame(all_sold_items) if all_sold_items else pd.DataFrame()

# ─── サマリーカード ───────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("出品中 (取得数)", f"{len(df):,} 件")
c2.metric("SOLD (取得数)", f"{len(sold_df_raw):,} 件")
if not df.empty:
    c3.metric("最低価格", f"¥{df['price'].min():,}")
    c4.metric("最高価格", f"¥{df['price'].max():,}")
    c5.metric("中央値", f"¥{int(df['price'].median()):,}")
    c6.metric("平均価格", f"¥{int(df['price'].mean()):,}")

st.markdown("---")

# ─── 価格グラフ ───────────────────────────────────────────
if not df.empty:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📊 カテゴリー別 価格分布")
        fig_box = px.box(
            df, x="category", y="price", color="category",
            points="outliers",
            labels={"category": "カテゴリー", "price": "価格 (円)"},
            template="plotly_white",
        )
        fig_box.update_layout(showlegend=False, height=380)
        fig_box.update_yaxes(tickformat=",.0f", tickprefix="¥")
        st.plotly_chart(fig_box, use_container_width=True)

    with col_right:
        st.subheader("📈 カテゴリー別 平均・中央値")
        agg = (
            df.groupby("category")["price"]
            .agg(平均=lambda x: int(x.mean()), 中央値=lambda x: int(x.median()))
            .reset_index()
            .sort_values("平均", ascending=True)
        )
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            y=agg["category"], x=agg["平均"], name="平均",
            orientation="h", marker_color="#FF4B4B",
        ))
        fig_bar.add_trace(go.Bar(
            y=agg["category"], x=agg["中央値"], name="中央値",
            orientation="h", marker_color="#F0A500",
        ))
        fig_bar.update_layout(
            barmode="group", height=380, template="plotly_white",
            xaxis=dict(tickformat=",.0f", tickprefix="¥"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

# ─── SOLD数 分析 ──────────────────────────────────────────
st.subheader("🏷️ カテゴリー別 SOLD数")

sold_rows = []
for cat in selected_categories:
    d = cache_manager.get(CACHE_KEY(cat))
    if not d:
        continue
    on_sale_n = len(d.get("items", []))
    sold_n = len(d.get("sold_items", []))
    sold_rows.append({
        "カテゴリー": cat,
        "出品中(取得)": on_sale_n,
        "SOLD数(取得)": sold_n,
    })

if sold_rows:
    sold_summary = pd.DataFrame(sold_rows).sort_values("SOLD数(取得)", ascending=True)
    sc1, sc2 = st.columns(2)

    with sc1:
        fig_sold = go.Figure()
        fig_sold.add_trace(go.Bar(
            y=sold_summary["カテゴリー"], x=sold_summary["SOLD数(取得)"],
            name="SOLD数", orientation="h", marker_color="#2ECC71",
        ))
        fig_sold.add_trace(go.Bar(
            y=sold_summary["カテゴリー"], x=sold_summary["出品中(取得)"],
            name="出品中", orientation="h", marker_color="#BDC3C7",
        ))
        fig_sold.update_layout(
            barmode="group", height=350, template="plotly_white",
            title="SOLD数 vs 出品中数 (各最大200件取得)",
        )
        st.plotly_chart(fig_sold, use_container_width=True)

    with sc2:
        fig_ratio = go.Figure()
        for _, row in sold_summary.iterrows():
            total = row["出品中(取得)"] + row["SOLD数(取得)"]
            sold_pct = row["SOLD数(取得)"] / total * 100 if total else 0
            on_pct = 100 - sold_pct
            fig_ratio.add_trace(go.Bar(
                name="SOLD", x=[sold_pct], y=[row["カテゴリー"]],
                orientation="h", marker_color="#2ECC71",
                showlegend=_ == 0,
                text=f"{sold_pct:.0f}%", textposition="inside",
            ))
            fig_ratio.add_trace(go.Bar(
                name="出品中", x=[on_pct], y=[row["カテゴリー"]],
                orientation="h", marker_color="#BDC3C7",
                showlegend=_ == 0,
            ))
        fig_ratio.update_layout(
            barmode="stack", height=350, template="plotly_white",
            title="SOLD比率 (取得件数ベース)",
            xaxis=dict(ticksuffix="%", range=[0, 100]),
        )
        st.plotly_chart(fig_ratio, use_container_width=True)

    st.dataframe(
        sold_summary.sort_values("SOLD数(取得)", ascending=False).reset_index(drop=True),
        use_container_width=True,
    )
    st.caption("※ 各カテゴリー最大200件ずつ取得したデータによる比較です。")

st.markdown("---")

# ─── 頻出キーワード Top100 ────────────────────────────────
st.subheader("🔑 SOLD済みアイテム 頻出キーワード Top100")

if all_sold_items:
    sold_names = [item["name"] for item in all_sold_items if item.get("name")]

    with st.spinner("キーワード解析中..."):
        top_kw = extract_top_keywords(sold_names, top_n=100)

    if top_kw:
        kw_df = pd.DataFrame(top_kw, columns=["キーワード", "出現数"])

        kw_col1, kw_col2 = st.columns([2, 1])

        with kw_col1:
            top20 = kw_df.head(20)
            fig_kw = px.bar(
                top20, x="出現数", y="キーワード",
                orientation="h",
                color="出現数",
                color_continuous_scale=["#FFF3CD", "#FF4B4B"],
                template="plotly_white",
                title="頻出キーワード Top20",
            )
            fig_kw.update_layout(height=550, yaxis=dict(autorange="reversed"))
            fig_kw.update_coloraxes(showscale=False)
            st.plotly_chart(fig_kw, use_container_width=True)

        with kw_col2:
            st.markdown("**Top100 一覧**")
            st.dataframe(
                kw_df,
                use_container_width=True,
                height=540,
                column_config={
                    "出現数": st.column_config.ProgressColumn(
                        "出現数", min_value=0,
                        max_value=int(kw_df["出現数"].max()),
                        format="%d",
                    ),
                },
            )
    else:
        st.info("キーワードを抽出できませんでした。")
else:
    st.info("SOLDデータがありません。データ更新を実行してください。")

st.markdown("---")

# ─── 商品グリッド ─────────────────────────────────────────
if not df.empty:
    st.subheader("🛍️ 出品中 商品一覧（価格が安い順 上位12件）")

    top_items = df.sort_values("price").head(12).to_dict("records")
    cols_per_row = 4
    for row_i in range(math.ceil(len(top_items) / cols_per_row)):
        cols = st.columns(cols_per_row)
        for col_idx in range(cols_per_row):
            item_idx = row_i * cols_per_row + col_idx
            if item_idx >= len(top_items):
                break
            item = top_items[item_idx]
            with cols[col_idx]:
                if item.get("image_url"):
                    st.image(item["image_url"], use_container_width=True)
                else:
                    st.markdown("_(画像なし)_")
                st.markdown(
                    f"**¥{item['price']:,}**  \n"
                    f"[{item['name'][:24]}{'…' if len(item['name']) > 24 else ''}]({item['url']})  \n"
                    f"`{item['category']}`"
                )

    st.markdown("---")

# ─── 詳細テーブル ─────────────────────────────────────────
if not df.empty:
    st.subheader("📋 詳細テーブル（出品中）")

    display_df = df[["name", "category", "price", "url"]].copy()
    display_df.columns = ["商品名", "カテゴリー", "価格(円)", "URL"]
    display_df = display_df.sort_values("価格(円)").reset_index(drop=True)

    st.dataframe(
        display_df,
        use_container_width=True,
        column_config={
            "URL": st.column_config.LinkColumn("リンク", display_text="開く"),
            "価格(円)": st.column_config.NumberColumn("価格(円)", format="¥%d"),
        },
        height=400,
    )
