import math
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import cache_manager
import creema_client
import genre_research
import mercari_client
import minne_client
from keywords import extract_top_keywords

st.set_page_config(
    page_title="ハンドメイド売れ筋調査",
    page_icon="🧵",
    layout="wide",
)

# ─── 認証 ────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        "<h2 style='text-align:center; margin-top:80px;'>🧵 ハンドメイド売れ筋調査</h2>",
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
    platforms = {
        "🛍️ メルカリ": ("mercari", "v3"),
        "🎨 Creema": ("creema", "v1"),
        "🌸 Minne": ("minne", "v1"),
    }
    for label, (platform, ver) in platforms.items():
        with st.expander(label, expanded=False):
            for cat in CATEGORIES:
                key = f"{platform}_{cat}_{ver}"
                ts = cache_manager.last_updated(key)
                if ts:
                    minutes_ago = int((time.time() - ts) / 60)
                    lbl = f"{minutes_ago}分前" if minutes_ago < 60 else f"{int(minutes_ago/60)}時間前"
                else:
                    lbl = "未取得"
                st.caption(f"{cat}: {lbl}")

    st.markdown("---")
    st.caption("⚠️ 個人調査用途のみ。商用利用不可。")


# ─── 共通ユーティリティ ───────────────────────────────────
def _cache_key(platform: str, cat: str, ver: str) -> str:
    return f"{platform}_{cat}_{ver}"


@st.cache_data(ttl=7200, show_spinner=False)
def load_category(platform: str, category: str, ver: str, _refresh_key: int) -> dict:
    key = _cache_key(platform, category, ver)
    cached = cache_manager.get(key)
    if cached is not None:
        return cached

    if platform == "mercari":
        data = mercari_client.fetch_category(category)
    elif platform == "creema":
        data = creema_client.fetch_category(category)
    else:
        data = minne_client.fetch_category(category)

    if data.get("items") or data.get("sold_items"):
        cache_manager.set(key, data)
    return data


def _load_all(platform: str, ver: str, refresh_key: int) -> tuple[list, list]:
    all_items, all_sold = [], []
    if not selected_categories:
        return all_items, all_sold
    progress = st.progress(0, text="データ取得中...")
    for i, cat in enumerate(selected_categories):
        progress.progress((i + 1) / len(selected_categories), text=f"{cat} 取得中...")
        data = load_category(platform, cat, ver, refresh_key)
        all_items.extend(data.get("items", []))
        all_sold.extend(data.get("sold_items", []))
    progress.empty()
    return all_items, all_sold


# ─── 分析 UI ─────────────────────────────────────────────
def render_summary_cards(df: pd.DataFrame, sold_df: pd.DataFrame) -> None:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("出品中 (取得数)", f"{len(df):,} 件")
    c2.metric("SOLD (取得数)", f"{len(sold_df):,} 件")
    if not df.empty:
        c3.metric("最低価格", f"¥{df['price'].min():,}")
        c4.metric("最高価格", f"¥{df['price'].max():,}")
        c5.metric("中央値", f"¥{int(df['price'].median()):,}")
        c6.metric("平均価格", f"¥{int(df['price'].mean()):,}")


def render_price_charts(df: pd.DataFrame) -> None:
    if df.empty:
        return
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("📊 カテゴリー別 価格分布")
        fig = px.box(
            df, x="category", y="price", color="category",
            points="outliers",
            labels={"category": "カテゴリー", "price": "価格 (円)"},
            template="plotly_white",
        )
        fig.update_layout(showlegend=False, height=380)
        fig.update_yaxes(tickformat=",.0f", tickprefix="¥")
        st.plotly_chart(fig, use_container_width=True)
    with col_right:
        st.subheader("📈 カテゴリー別 平均・中央値")
        agg = (
            df.groupby("category")["price"]
            .agg(平均=lambda x: int(x.mean()), 中央値=lambda x: int(x.median()))
            .reset_index()
            .sort_values("平均", ascending=True)
        )
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(y=agg["category"], x=agg["平均"], name="平均", orientation="h", marker_color="#FF4B4B"))
        fig2.add_trace(go.Bar(y=agg["category"], x=agg["中央値"], name="中央値", orientation="h", marker_color="#F0A500"))
        fig2.update_layout(barmode="group", height=380, template="plotly_white",
                           xaxis=dict(tickformat=",.0f", tickprefix="¥"))
        st.plotly_chart(fig2, use_container_width=True)


def render_sold_analysis(platform: str, ver: str) -> None:
    st.subheader("🏷️ カテゴリー別 SOLD数")
    sold_rows = []
    for cat in selected_categories:
        d = cache_manager.get(_cache_key(platform, cat, ver))
        if not d:
            continue
        sold_rows.append({
            "カテゴリー": cat,
            "出品中(取得)": len(d.get("items", [])),
            "SOLD数(取得)": len(d.get("sold_items", [])),
        })
    if not sold_rows:
        st.info("データがありません。データ更新ボタンを押してください。")
        return

    ss = pd.DataFrame(sold_rows).sort_values("SOLD数(取得)", ascending=True)
    sc1, sc2 = st.columns(2)
    with sc1:
        fig = go.Figure()
        fig.add_trace(go.Bar(y=ss["カテゴリー"], x=ss["SOLD数(取得)"], name="SOLD数", orientation="h", marker_color="#2ECC71"))
        fig.add_trace(go.Bar(y=ss["カテゴリー"], x=ss["出品中(取得)"], name="出品中", orientation="h", marker_color="#BDC3C7"))
        fig.update_layout(barmode="group", height=350, template="plotly_white",
                          title="SOLD数 vs 出品中数 (各最大200件取得)")
        st.plotly_chart(fig, use_container_width=True)
    with sc2:
        fig2 = go.Figure()
        for _, row in ss.iterrows():
            total = row["出品中(取得)"] + row["SOLD数(取得)"]
            sold_pct = row["SOLD数(取得)"] / total * 100 if total else 0
            on_pct = 100 - sold_pct
            fig2.add_trace(go.Bar(name="SOLD", x=[sold_pct], y=[row["カテゴリー"]], orientation="h",
                                  marker_color="#2ECC71", showlegend=_ == 0,
                                  text=f"{sold_pct:.0f}%", textposition="inside"))
            fig2.add_trace(go.Bar(name="出品中", x=[on_pct], y=[row["カテゴリー"]], orientation="h",
                                  marker_color="#BDC3C7", showlegend=_ == 0))
        fig2.update_layout(barmode="stack", height=350, template="plotly_white",
                           title="SOLD比率 (取得件数ベース)",
                           xaxis=dict(ticksuffix="%", range=[0, 100]))
        st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(ss.sort_values("SOLD数(取得)", ascending=False).reset_index(drop=True),
                 use_container_width=True)
    st.caption("※ 各カテゴリー最大200件ずつ取得したデータによる比較です。")


def render_keyword_analysis(all_sold_items: list, platform: str) -> None:
    st.subheader("🔑 SOLD済みアイテム 頻出キーワード Top100")

    if platform in ("creema", "minne") and not all_sold_items:
        st.info(
            f"{'Creema' if platform == 'creema' else 'Minne'} ではSOLD済みデータの取得ができないため、"
            "キーワード分析はスキップします。"
        )
        return

    if not all_sold_items:
        st.info("SOLDデータがありません。データ更新を実行してください。")
        return

    sold_names = [item["name"] for item in all_sold_items if item.get("name")]
    with st.spinner("キーワード解析中..."):
        top_kw = extract_top_keywords(sold_names, top_n=100)

    if not top_kw:
        st.info("キーワードを抽出できませんでした。")
        return

    kw_df = pd.DataFrame(top_kw, columns=["キーワード", "出現数"])
    kw_col1, kw_col2 = st.columns([2, 1])
    with kw_col1:
        fig = px.bar(kw_df.head(20), x="出現数", y="キーワード", orientation="h",
                     color="出現数", color_continuous_scale=["#FFF3CD", "#FF4B4B"],
                     template="plotly_white", title="頻出キーワード Top20")
        fig.update_layout(height=550, yaxis=dict(autorange="reversed"))
        fig.update_coloraxes(showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with kw_col2:
        st.markdown("**Top100 一覧**")
        st.dataframe(kw_df, use_container_width=True, height=540,
                     column_config={"出現数": st.column_config.ProgressColumn(
                         "出現数", min_value=0, max_value=int(kw_df["出現数"].max()), format="%d")})


def render_item_grid(df: pd.DataFrame) -> None:
    if df.empty:
        return
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


def render_detail_table(df: pd.DataFrame) -> None:
    if df.empty:
        return
    st.subheader("📋 詳細テーブル（出品中）")
    display_df = df[["name", "category", "price", "url"]].copy()
    display_df.columns = ["商品名", "カテゴリー", "価格(円)", "URL"]
    display_df = display_df.sort_values("価格(円)").reset_index(drop=True)
    st.dataframe(
        display_df, use_container_width=True,
        column_config={
            "URL": st.column_config.LinkColumn("リンク", display_text="開く"),
            "価格(円)": st.column_config.NumberColumn("価格(円)", format="¥%d"),
        },
        height=400,
    )


def render_platform_tab(platform: str, ver: str, refresh_key: int, title: str) -> None:
    st.title(title)
    if not selected_categories:
        st.warning("カテゴリーを選択してください。")
        return

    all_items, all_sold_items = _load_all(platform, ver, refresh_key)

    if not all_items and not all_sold_items:
        st.warning("データ取得に失敗しました。データ更新ボタンを押してください。")
        return

    df = pd.DataFrame(all_items) if all_items else pd.DataFrame()
    df = df[df["price"] > 0].copy() if not df.empty else df
    sold_df_raw = pd.DataFrame(all_sold_items) if all_sold_items else pd.DataFrame()

    render_summary_cards(df, sold_df_raw)
    st.markdown("---")
    render_price_charts(df)
    st.markdown("---")
    render_sold_analysis(platform, ver)
    st.markdown("---")
    render_keyword_analysis(all_sold_items, platform)
    st.markdown("---")
    render_item_grid(df)
    st.markdown("---")
    render_detail_table(df)


# ─── キャッシュリフレッシュ ──────────────────────────────
if force_refresh:
    for cat in CATEGORIES:
        for platform, ver in [("mercari", "v3"), ("creema", "v1"), ("minne", "v1")]:
            cache_manager.clear(_cache_key(platform, cat, ver))
    st.cache_data.clear()

refresh_key = int(time.time() / 7200)

# ─── ジャンル調査タブ ─────────────────────────────────────
def render_genre_tab() -> None:
    st.title("📊 ハンドメイド ジャンル市場調査")
    st.caption("メルカリのデータをもとに、各ジャンルの出品数・SOLD数・SOLD率をランキング表示します（各最大50件取得）。")

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        do_refresh = st.button("🔍 データ取得・更新", use_container_width=True, type="primary")
    with col_info:
        ts = genre_research.last_updated()
        if ts:
            minutes_ago = int((time.time() - ts) / 60)
            lbl = f"{minutes_ago}分前" if minutes_ago < 60 else f"{int(minutes_ago/60)}時間前"
            st.caption(f"最終更新: {lbl}　（キャッシュ有効期限: 12時間）")
        else:
            st.caption("未取得　→「データ取得・更新」を押してください")

    stats = None
    if do_refresh:
        prog = st.progress(0, text="ジャンルデータ取得中...")
        def _cb(pct, genre):
            prog.progress(pct, text=f"{genre} 取得中... ({int(pct * 100)}%)")
        stats = genre_research.fetch_genre_stats(force=True, progress_callback=_cb)
        prog.empty()
    else:
        stats = genre_research.get_cached()

    if stats is None:
        st.info("「データ取得・更新」ボタンを押すと分析を開始します。39ジャンル分のデータ取得に1〜2分かかります。")
        return

    rows = []
    for g, d in stats.items():
        on_sale = d.get("on_sale", 0)
        sold = d.get("sold", 0)
        total = on_sale + sold
        sold_rate = round(sold / total * 100, 1) if total > 0 else 0.0
        rows.append({"ジャンル": g, "出品数(取得)": on_sale, "SOLD数(取得)": sold, "SOLD率(%)": sold_rate})
    df = pd.DataFrame(rows)

    # ─── ランキングチャート
    rank_tab1, rank_tab2, rank_tab3 = st.tabs(["🟢 SOLD数ランキング", "🔴 出品数ランキング", "🟡 SOLD率ランキング"])

    with rank_tab1:
        top = df.sort_values("SOLD数(取得)", ascending=True)
        fig = go.Figure(go.Bar(
            x=top["SOLD数(取得)"], y=top["ジャンル"], orientation="h", marker_color="#2ECC71",
        ))
        fig.update_layout(height=700, template="plotly_white", title="SOLD数ランキング（全ジャンル）")
        st.plotly_chart(fig, use_container_width=True)

    with rank_tab2:
        top = df.sort_values("出品数(取得)", ascending=True)
        fig = go.Figure(go.Bar(
            x=top["出品数(取得)"], y=top["ジャンル"], orientation="h", marker_color="#FF4B4B",
        ))
        fig.update_layout(height=700, template="plotly_white", title="出品数ランキング（全ジャンル）")
        st.plotly_chart(fig, use_container_width=True)

    with rank_tab3:
        top = df.sort_values("SOLD率(%)", ascending=True)
        fig = go.Figure(go.Bar(
            x=top["SOLD率(%)"], y=top["ジャンル"], orientation="h", marker_color="#F0A500",
            text=top["SOLD率(%)"].astype(str) + "%", textposition="outside",
        ))
        fig.update_layout(height=700, template="plotly_white", title="SOLD率ランキング（全ジャンル）",
                          xaxis=dict(ticksuffix="%", range=[0, 100]))
        st.plotly_chart(fig, use_container_width=True)

    # ─── チャンスジャンル
    st.markdown("---")
    st.subheader("💡 チャンスジャンル")
    st.caption("SOLD率が中央値以上 かつ 出品数が中央値以下 = 需要あり・競合少なめ")
    med_rate = df["SOLD率(%)"].median()
    med_sale = df["出品数(取得)"].median()
    opp = df[(df["SOLD率(%)"] >= med_rate) & (df["出品数(取得)"] <= med_sale)].sort_values("SOLD率(%)", ascending=False).reset_index(drop=True)
    if opp.empty:
        st.info("条件に合うジャンルが見つかりませんでした。")
    else:
        st.dataframe(
            opp, use_container_width=True,
            column_config={
                "SOLD率(%)": st.column_config.ProgressColumn("SOLD率(%)", min_value=0, max_value=100, format="%.1f%%"),
            },
        )

    # ─── 全ジャンル詳細テーブル
    st.markdown("---")
    st.subheader("📋 全ジャンル詳細")
    st.dataframe(
        df.sort_values("SOLD率(%)", ascending=False).reset_index(drop=True),
        use_container_width=True,
        column_config={
            "SOLD率(%)": st.column_config.ProgressColumn("SOLD率(%)", min_value=0, max_value=100, format="%.1f%%"),
        },
    )
    st.caption("※ 各ジャンル最大50件取得のデータです。実際の市場規模とは異なります。")


# ─── タブ ────────────────────────────────────────────────
tab_m, tab_c, tab_minne, tab_genre = st.tabs(["🛍️ メルカリ", "🎨 Creema", "🌸 Minne", "📊 ジャンル調査"])

with tab_m:
    render_platform_tab("mercari", "v3", refresh_key, "🧵 メルカリ ハンドメイド売れ筋調査")

with tab_c:
    render_platform_tab("creema", "v1", refresh_key, "🎨 Creema ハンドメイド売れ筋調査")

with tab_minne:
    render_platform_tab("minne", "v1", refresh_key, "🌸 Minne ハンドメイド売れ筋調査")

with tab_genre:
    render_genre_tab()
