from collections import Counter
from janome.tokenizer import Tokenizer

_tokenizer = None

STOPWORDS = {
    # メルカリ定型文
    "ハンドメイド", "ハンドメード", "手作り", "手づくり", "送料", "無料", "込み", "込",
    "匿名", "配送", "発送", "即日", "即購入", "新品", "未使用", "美品", "セット",
    "まとめ", "バラ", "出品", "専用", "取引", "商品", "確認", "様", "専",
    # janome が分割する「ハンドメイド」の破片
    "ハンド", "メイド",
    # 一般的すぎる語
    "作品", "もの", "こと", "など", "用", "型", "色", "柄", "サイズ", "大", "小",
    "個", "枚", "本", "点", "円", "以上", "以下", "について", "です", "ます",
    "ページ", "タグ", "説明", "注意", "お願い", "プロフ", "ご覧",
    # 記号・数字系
    "×", "・", "/", "＊", "*", "☆", "★", "♪", "♡", "♥",
    # カテゴリ検索に使ったワード (ノイズ)
    "レザー", "革", "レジン", "ポーチ", "バッグ", "鞄", "キーホルダー", "ペット",
    "犬", "猫",
}

# 対象品詞
TARGET_POS = {"名詞", "形容詞"}


def _get_tokenizer() -> Tokenizer:
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    return _tokenizer


def extract_top_keywords(names: list[str], top_n: int = 100) -> list[tuple[str, int]]:
    """SOLD済みアイテム名から頻出キーワードを抽出して上位 top_n を返す"""
    t = _get_tokenizer()
    counter: Counter = Counter()

    for name in names:
        for token in t.tokenize(name):
            surface = token.surface.strip()
            pos = token.part_of_speech.split(",")[0]
            if (
                pos in TARGET_POS
                and len(surface) >= 2
                and surface not in STOPWORDS
                and not surface.isdigit()
                and not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in surface)
            ):
                counter[surface] += 1

    return counter.most_common(top_n)
