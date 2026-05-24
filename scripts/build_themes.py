"""LDA-based theme analysis across 1063 plays.

Pipeline:
1. Build a per-play document = plot + notes + 唱词 + 念白 (no stage dirs).
2. jieba tokenize, drop stop words and theatrical noise tokens.
3. CountVectorizer + LatentDirichletAllocation (n_topics=12).
4. Map each topic to a Chinese label by matching its top words against a
   curated theme keyword table; topics with no match keep a generic name.
5. Build sunburst (大类 → 主题 → 高频词), play profiles, co-occurrence net,
   genre × theme distribution and frequent combinations.

Output: data/themes.json (+ data/_themes_report.txt).
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import jieba
import numpy as np
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"

# ===========================================================
# Stop words & noise tokens
# ===========================================================
STOPWORDS = set("""
的 了 是 在 和 与 又 也 都 就 不 没 还 又 上 下 把 给 你 我 他 她 它 我们 你们 他们
请 来 去 这 那 此 那个 这个 之 而 但 但是 并 或 或者 因为 所以 由于 一 二 三 四 五 六 七 八 九 十
个 件 只 块 张 条 句 一个 两个 几个 各位 自己 别人 大家 怎么 什么 怎样 为什么 哪里 谁 哪 何 何处
得 着 过 来 去 起 出 进 入 至 到 由 自 用 把 让 被 与 跟 同 向 朝 往 从 因 为 凭 据 因为
有 无 没 没有 多 少 大 小 长 短 高 低 老 小 哈哈 哎呀 哎哟 嗳呀 罢了 罢 啊 哦 噢 嗯 哼
然 何 矣 焉 也 兮 哉 乎 之 乎 也 矣 焉 兮 哉 者 所
说 说道 说得 道 言 曰 云 谓
请 听 请问 试问 还是 也是 还是 必须 须当
本 此 该 这等 此等 那等
正是 原是 既是 便是 现在 那时 此时 如今 当下 来日 此地
""".split())

# Theatrical / staging noise tokens
THEATRICAL_NOISE = set("""
唱 念 白 同白 内白 夹白 念白 引子 念词 唱腔 西皮 二黄 板式 摇板 散板 快板 流水板 二六板
原板 慢板 导板 平板 慢慢 急急 慢慢的 出 入 上场 下场 出场 退下 退场
诸位 列位 列公 各位 大家 众人 大众
舞台 灯光 锣鼓 锣 鼓 鼓师 板鼓 检场 龙套 跑龙套 旦 生 净 丑 角色
公子 大人 老爷 太太 夫人 千岁 万岁
点绛唇 扑灯蛾 急急风 西皮原板 西皮慢板 二黄原板 二黄慢板
""".split())

# Single-character function words to drop
SINGLES_TO_KEEP = set("仙 神 妖 鬼 战 杀 兵 君 忠 孝 义 节 情 爱 恨 喜 怒 哀 乐 死 生 老 死".split())

CHINESE_TOKEN_RE = re.compile(r"^[一-鿿]+$")


def is_useful_token(t: str) -> bool:
    if not t or len(t) > 6:
        return False
    if not CHINESE_TOKEN_RE.match(t):
        return False
    if t in STOPWORDS or t in THEATRICAL_NOISE:
        return False
    if len(t) == 1 and t not in SINGLES_TO_KEEP:
        return False
    return True


# ===========================================================
# Build documents
# ===========================================================
LYRIC_OR_RECITE = {"唱", "念", "引子", "点绛唇"}


def is_singing_action(action_type: str) -> bool:
    return action_type in LYRIC_OR_RECITE or any(
        s in action_type for s in ("板", "腔", "调", "梆子", "导板", "二六", "原板",
                                    "慢板", "快板", "流水板", "散板", "摇板", "平板", "吹腔")
    )


def build_doc(play: dict) -> str:
    parts = []
    if play.get("plot"):
        parts.append(play["plot"])
    if play.get("notes"):
        parts.append(play["notes"])
    for ln in play.get("lines", []):
        a = ln.get("actionType", "")
        if is_singing_action(a):
            parts.append(ln.get("content", ""))
        elif a == "念":
            parts.append(ln.get("content", ""))
    return " ".join(parts)


# ===========================================================
# Topic naming via keyword table
# ===========================================================
THEME_TABLE = [
    # (theme_name, big_category, keywords) — keywords match as substring in top words
    ("忠君爱国", "伦理纲常", ["忠", "君臣", "社稷", "天下", "汉室", "皇恩", "为国", "报国", "尽忠"]),
    ("孝亲伦理", "伦理纲常", ["孝", "母亲", "孝子", "孝顺", "母子", "家门"]),
    ("守节贞烈", "伦理纲常", ["节", "贞", "烈", "贞洁", "守节", "节妇", "殉节"]),
    ("兄弟义气", "伦理纲常", ["结义", "义气", "桃园", "金兰", "贤弟", "贤兄"]),
    ("爱情婚姻", "情感主题", ["爱情", "夫妻", "婚姻", "佳人", "才子", "良缘", "私订", "钟情", "鸳鸯"]),
    ("思乡愁绪", "情感主题", ["故乡", "思乡", "离别", "归来", "回乡", "家乡", "他乡"]),
    ("征战疆场", "历史叙事", ["征战", "出征", "兵马", "战场", "敌兵", "杀敌", "破阵", "围困", "厮杀"]),
    ("朝代兴亡", "历史叙事", ["江山", "兴亡", "亡国", "朝廷", "皇朝", "汉朝", "宋朝", "唐朝"]),
    ("王位之争", "历史叙事", ["篡位", "夺位", "皇位", "称王", "称帝", "登基", "禅让"]),
    ("公案断狱", "公案侠义", ["公案", "断案", "审案", "包公", "包拯", "知府", "县官", "御史", "冤情"]),
    ("平反冤屈", "公案侠义", ["鸣冤", "诉冤", "翻案", "雪冤", "申冤"]),
    ("江湖侠义", "公案侠义", ["江湖", "侠义", "镖", "绿林", "草莽", "山寨", "义士"]),
    ("神仙下凡", "神怪幻想", ["下凡", "仙界", "玉皇", "天宫", "蟠桃", "嫦娥", "凡间"]),
    ("妖魔斗法", "神怪幻想", ["妖魔", "斗法", "降妖", "降魔", "斩妖", "妖怪", "鬼魂"]),
    ("市井百态", "民间风情", ["市井", "酒肆", "店家", "贩夫", "百姓", "民间", "小贩"]),
    ("骨肉团圆", "情感主题", ["团圆", "团聚", "重逢", "认亲", "认母", "认父"]),
    # 戏码题材 (LDA topics often cluster around famous repertoires)
    ("三国题材", "历史叙事", ["三国", "诸葛", "孔明", "刘备", "曹操", "关羽", "孙权", "周瑜", "东吴", "蜀汉"]),
    ("杨家将", "历史叙事", ["杨家", "杨延", "杨令", "杨业", "孟良", "焦赞", "佘太君", "穆桂英", "杨宗保"]),
    ("水浒题材", "公案侠义", ["梁山", "宋江", "李逵", "林冲", "武松", "鲁智深", "晁盖"]),
    ("白蛇传", "神怪幻想", ["白蛇", "许仙", "法海", "青蛇", "雷峰"]),
    ("玉堂春", "情感主题", ["玉堂春", "苏三", "王金龙", "鸨儿"]),
    ("薛家将", "历史叙事", ["薛平贵", "王宝钏", "寒窑", "薛仁贵", "西凉"]),
    ("赵氏孤儿", "伦理纲常", ["屠岸贾", "公孙杵臼", "程婴", "赵氏"]),
    ("西游题材", "神怪幻想", ["孙悟空", "唐僧", "猪八戒", "沙僧", "西天"]),
    ("瓦岗群英", "公案侠义", ["秦琼", "罗成", "程咬金", "瓦岗"]),
]


def name_topic(top_words: list[str], topic_idx: int) -> tuple[str, str]:
    """Return (theme_label, big_category) for a topic based on its top words."""
    scores: dict[str, tuple[int, str]] = {}
    for name, cat, kws in THEME_TABLE:
        score = sum(1 for w in top_words for k in kws if k in w)
        if score > 0:
            scores[name] = (score, cat)
    if not scores:
        return (f"主题{topic_idx + 1}", "其他")
    best = max(scores.items(), key=lambda x: x[1][0])
    return (best[0], best[1][1])


# ===========================================================
# Main
# ===========================================================
def main():
    print("Loading plays ...", flush=True)
    plays = json.loads((DATA / "plays.json").read_text(encoding="utf-8"))
    play_meta = {p["id"]: p for p in plays}

    play_jsons: dict[str, dict] = {}
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        play_jsons[d["playId"]] = d
    print(f"  {len(play_jsons)} plays", flush=True)

    # ===========================================================
    # Collect proper nouns (character names) to drop from LDA corpus
    # — otherwise LDA clusters around recurring character names instead of
    # genuine thematic tokens.
    # ===========================================================
    proper_nouns: set[str] = set()
    for pid, pdata in play_jsons.items():
        for c in pdata.get("mainCharacters", []):
            n = c.get("name", "").strip()
            if 2 <= len(n) <= 5:
                proper_nouns.add(n)
            # also add prefix (e.g. "诸葛亮" → "诸葛", to catch jieba's segmenting)
            if len(n) >= 2:
                proper_nouns.add(n[:2])
    # Plus a curated list of historical figures often referenced indirectly
    proper_nouns.update("""
        诸葛 孔明 刘备 曹操 孙权 周瑜 关羽 张飞 赵云 黄忠 马超 司马 周仓 鲁肃 黄盖
        刘禅 后主 先主 阿斗 庞统 姜维 魏延 王平 马谡 陆逊 吕蒙 鲁肃 孟获
        薛平 平贵 宝钏 仁贵 丁山 樊梨花 樊江
        杨延 延辉 延昭 杨业 令公 老令 七郎 六郎 八郎 孟良 焦赞 余太 太君 穆桂 桂英 杨宗 宗保 杨家 杨令
        宋江 李逵 林冲 武松 鲁达 鲁智深 智深 晁盖 公明 吴用 卢俊 俊义
        孙悟 悟空 唐僧 八戒 沙僧 沙和
        许仙 法海 白蛇 青蛇 小青
        玉堂 苏三 王金龙 金龙
        屠岸 屠岸贾 程婴 杵臼 公孙
        包公 包拯 展昭 王朝 马汉 张龙 赵虎
        岳飞 岳云 牛皋 兀术 金兀 高宠
        秦琼 罗成 程咬 咬金 单雄 雄信 尉迟 敬德 李世 世民 李渊 唐王
        刘邦 韩信 项羽 萧何 范增 张良
        玄宗 唐皇 杨妃 贵妃 李隆 安禄
        武则 则天 武后
        宋徽 宋钦 宋高 高宗
        汉武 汉文 汉景
        西施 范蠡 勾践 夫差
        貂蝉 吕布 董卓
        屈原 楚怀 楚王
        李广 卫青 霍去
        包龙
    """.split())
    print(f"  proper noun stoplist size: {len(proper_nouns)}", flush=True)

    # ===========================================================
    # Tokenize
    # ===========================================================
    print("Tokenizing with jieba ...", flush=True)
    jieba.setLogLevel(60)  # suppress
    t0 = time.time()
    pids: list[str] = []
    tokenized: list[str] = []
    for i, (pid, pdata) in enumerate(play_jsons.items(), 1):
        if pdata.get("parseError"):
            continue
        doc = build_doc(pdata)
        if not doc.strip():
            continue
        toks = [t for t in jieba.cut(doc)
                if is_useful_token(t) and t not in proper_nouns]
        if len(toks) < 30:
            continue
        pids.append(pid)
        tokenized.append(" ".join(toks))
        if i % 200 == 0:
            print(f"  [{i}/{len(play_jsons)}] tokenized={len(pids)}  elapsed={time.time()-t0:.1f}s", flush=True)
    print(f"  {len(pids)} usable plays after tokenization", flush=True)

    # ===========================================================
    # LDA
    # ===========================================================
    print("Fitting CountVectorizer + LDA ...", flush=True)
    n_topics = 12
    vec = CountVectorizer(max_features=3000, min_df=5, max_df=0.7)
    X = vec.fit_transform(tokenized)
    vocab = vec.get_feature_names_out()
    print(f"  vocabulary: {len(vocab)}  doc-term matrix: {X.shape}", flush=True)

    lda = LatentDirichletAllocation(
        n_components=n_topics,
        max_iter=30,
        learning_method="online",
        random_state=42,
        n_jobs=1,
    )
    doc_topic = lda.fit_transform(X)
    topic_word = lda.components_
    print(f"  doc_topic: {doc_topic.shape}  topic_word: {topic_word.shape}", flush=True)

    # Top words per topic
    top_n = 15
    topic_top_words: list[list[str]] = []
    topic_top_weights: list[list[float]] = []
    for ti in range(n_topics):
        top_idx = topic_word[ti].argsort()[-top_n:][::-1]
        words = [vocab[i] for i in top_idx]
        weights = [float(topic_word[ti, i]) for i in top_idx]
        topic_top_words.append(words)
        topic_top_weights.append(weights)

    # Name topics — disambiguate duplicates by appending "·N"
    topic_names: list[str] = []
    topic_cats: list[str] = []
    name_seen: dict[str, int] = {}
    for ti in range(n_topics):
        base_name, cat = name_topic(topic_top_words[ti], ti)
        seen = name_seen.get(base_name, 0)
        if seen == 0:
            final_name = base_name
        else:
            final_name = f"{base_name}·{seen + 1}"
        name_seen[base_name] = seen + 1
        topic_names.append(final_name)
        topic_cats.append(cat)

    print("\nTopics:")
    for ti, (name, cat, words) in enumerate(zip(topic_names, topic_cats, topic_top_words)):
        print(f"  T{ti:2d}  [{cat}] {name:<10}  {' '.join(words[:10])}")

    # ===========================================================
    # Per-play top themes
    # ===========================================================
    K = 3  # top-K themes per play
    play_profiles: list[dict] = []
    play_top_themes: dict[str, list[str]] = {}
    cooccur: Counter = Counter()
    combos: Counter = Counter()
    genre_theme: Counter = Counter()
    theme_count: Counter = Counter()

    for doc_i, pid in enumerate(pids):
        meta = play_meta.get(pid, {})
        title = meta.get("title", pid)
        genre = meta.get("genre", "其他")
        top_idx = doc_topic[doc_i].argsort()[-K:][::-1]
        themes = [topic_names[t] for t in top_idx]
        play_profiles.append({"playId": pid, "title": title, "topThemes": themes})
        play_top_themes[pid] = themes
        for th in themes:
            theme_count[th] += 1
            genre_theme[(genre, th)] += 1
        for a, b in combinations(sorted(set(themes)), 2):
            cooccur[(a, b)] += 1
        combos[tuple(sorted(set(themes)))] += 1

    # ===========================================================
    # Sunburst structure: 大类 → 主题 → top 5 keywords
    # ===========================================================
    sun_children: dict[str, list[dict]] = defaultdict(list)
    for ti, (name, cat) in enumerate(zip(topic_names, topic_cats)):
        sun_children[cat].append({
            "name": name,
            "children": [
                {"name": w, "value": int(round(w_weight * 1000))}
                for w, w_weight in zip(topic_top_words[ti][:5], topic_top_weights[ti][:5])
            ],
        })
    sunburst = {
        "name": "京剧主题",
        "children": [{"name": cat, "children": items} for cat, items in sun_children.items()],
    }

    # ===========================================================
    # Cooccurrence net (top 50 edges)
    # ===========================================================
    cooccur_links = [
        {"source": a, "target": b, "value": v}
        for (a, b), v in cooccur.most_common(50)
    ]
    cooccur_nodes = [{"id": th, "value": cnt} for th, cnt in theme_count.most_common()]

    # ===========================================================
    # Genre distribution
    # ===========================================================
    genre_distribution = [
        {"genre": g, "theme": th, "value": v}
        for (g, th), v in genre_theme.most_common()
    ]

    # ===========================================================
    # Combinations (top 20 distinct triples)
    # ===========================================================
    combinations_out = [
        {"combination": list(combo), "value": v}
        for combo, v in combos.most_common(20)
    ]

    # Themes record list (for /api/themes etc.)
    themes_records = []
    for doc_i, pid in enumerate(pids):
        for t_idx in range(n_topics):
            weight = float(doc_topic[doc_i, t_idx])
            if weight < 0.05:
                continue
            themes_records.append({
                "playId": pid,
                "theme": topic_names[t_idx],
                "weight": round(weight, 4),
            })

    out = {
        "sunburst": sunburst,
        "cooccurrenceNodes": cooccur_nodes,
        "cooccurrenceLinks": cooccur_links,
        "genreDistribution": genre_distribution,
        "combinations": combinations_out,
        "playProfiles": play_profiles,
        # extras for backend use:
        "themes": themes_records,
        "topicTopWords": [
            {"topicId": ti, "name": topic_names[ti], "category": topic_cats[ti],
             "topWords": topic_top_words[ti], "topWeights": topic_top_weights[ti]}
            for ti in range(n_topics)
        ],
    }
    (DATA / "themes.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Report
    report = [
        "=== build_themes.py 报告 ===",
        f"plays in: {len(plays)}  usable docs: {len(pids)}",
        f"vocab:    {len(vocab)}   doc-term: {X.shape}",
        f"topics:   {n_topics}",
        "",
        "--- Topic naming ---",
    ]
    for ti, (name, cat, words) in enumerate(zip(topic_names, topic_cats, topic_top_words)):
        report.append(f"  T{ti:2d} [{cat}] {name:<10}  {' '.join(words[:8])}")
    report.append("\n--- theme play-count (top 12) ---")
    for k, v in theme_count.most_common(12):
        report.append(f"  {k:<10}  {v}")
    report.append("\n--- genre × theme (top 15) ---")
    for d in genre_distribution[:15]:
        report.append(f"  {d['genre']:<6}  {d['theme']:<10}  {d['value']}")
    (DATA / "_themes_report.txt").write_text("\n".join(report), encoding="utf-8")
    print()
    print("\n".join(report))
    print(f"\nWrote: {DATA/'themes.json'}")


if __name__ == "__main__":
    sys.exit(main())
