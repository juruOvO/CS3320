"""Build an LLM-enhanced themes.json.

This script replaces the LDA-derived per-play theme labels with DeepSeek
multi-label semantic classification, then rebuilds the same aggregate structures
used by the frontend: sunburst, co-occurrence, genre distribution, combinations,
playProfiles, themes, and topicTopWords.

Run after build_features.py. If 京剧剧本_json/ is present, the LLM receives plot,
notes, and representative singing/reciting lines; otherwise it falls back to
plays.json summaries and existing theme hints.

Examples:
    python scripts/augment_themes_llm.py --dry-run --limit 20
    python scripts/augment_themes_llm.py --limit 100
    python scripts/augment_themes_llm.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from llm_client import DeepSeekJsonClient, JsonlCache, LLMConfig, clamp_float, stable_hash

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"
CACHE = DATA / "llm_cache" / "theme_inference.jsonl"
SCHEMA_VERSION = "theme-inference-v1"

THEME_TAXONOMY: dict[str, list[str]] = {
    "伦理纲常": ["忠君爱国", "孝亲伦理", "守节贞烈", "兄弟义气", "家国责任", "忠奸辨析"],
    "情感主题": ["爱情婚姻", "思乡离别", "骨肉团圆", "亲子冲突", "女性命运", "恩怨复仇"],
    "历史叙事": ["朝代兴亡", "征战疆场", "王位之争", "忠臣遇难", "军事智谋", "边塞出使"],
    "公案侠义": ["公案断狱", "平反冤屈", "江湖侠义", "惩恶扬善", "义士救难"],
    "神怪幻想": ["神仙下凡", "妖魔斗法", "因果报应", "梦境幻化", "宗教修行"],
    "民间风情": ["市井百态", "婚丧礼俗", "商旅行路", "科举功名", "家庭生计"],
    "戏码题材": ["三国题材", "杨家将题材", "水浒题材", "西游题材", "白蛇题材", "包公题材", "隋唐题材"],
    "其他": ["其他"],
}

ALLOWED_THEMES = sorted({theme for themes in THEME_TAXONOMY.values() for theme in themes})
THEME_TO_CATEGORY = {theme: cat for cat, themes in THEME_TAXONOMY.items() for theme in themes}

THEME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "playId": {"type": "string"},
                    "themes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "theme": {"type": "string", "enum": ALLOWED_THEMES},
                                "category": {"type": "string", "enum": list(THEME_TAXONOMY.keys())},
                                "weight": {"type": "number"},
                                "keywords": {"type": "array", "items": {"type": "string"}},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                                "reason": {"type": "string"},
                            },
                            "required": ["theme", "category", "weight", "keywords", "evidence", "reason"],
                        },
                    },
                    "summaryTheme": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["playId", "themes", "summaryTheme", "confidence"],
            },
        }
    },
    "required": ["decisions"],
}

SYSTEM_PROMPT = """你是京剧剧本文本主题标注员。请根据剧情简介、注释和代表性唱念白判断每部戏的核心主题。

规则：
1. 每部戏选择 1 到 4 个主题，必须来自给定 taxonomy。
2. weight 是 0 到 1 的主题强度，第一主题最高；证据不足时选择“其他”并给低置信度。
3. evidence 只能引用或概括输入里出现的信息，每个主题最多 3 条。
4. 不要因为人物名字频繁出现就把人名当主题；要判断矛盾、伦理、情感和叙事功能。
5. 只输出 JSON Object。"""

LYRIC_HINTS = ("唱", "念", "引子", "点绛唇", "板", "腔", "调", "二黄", "西皮", "梆子")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild themes.json with LLM semantic labels.")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates but do not call the LLM or write data.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum plays to process; 0 means all.")
    parser.add_argument("--play-id", default="", help="Only process one playId.")
    parser.add_argument("--batch-size", type=int, default=5, help="Plays per LLM request.")
    parser.add_argument("--min-confidence", type=float, default=0.35, help="Drop theme decisions below this per-play confidence.")
    parser.add_argument("--keep-existing-on-error", action="store_true", help="Use existing themes.json records when an LLM batch fails.")
    parser.add_argument("--write-partial", action="store_true", help="Allow --limit/--play-id runs to overwrite themes.json instead of writing a preview file.")
    return parser.parse_args()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_play_jsons() -> dict[str, dict]:
    out = {}
    if not SRC.exists():
        return out
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            d = load_json(p)
        except Exception:
            continue
        out[d["playId"]] = d
    return out


def existing_theme_hints(themes_json: dict) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    for profile in themes_json.get("playProfiles", []) if themes_json else []:
        hints[profile["playId"]] = profile.get("topThemes", [])[:3]
    return hints


def line_samples(play_json: dict, limit: int = 8) -> list[dict]:
    rows = []
    for ln in play_json.get("lines", []):
        action = ln.get("actionType", "")
        content = ln.get("content", "").strip()
        if not content:
            continue
        if any(h in action for h in LYRIC_HINTS) or action in ("白", "念"):
            rows.append({
                "sceneNum": ln.get("sceneNum", 0),
                "character": ln.get("character", ""),
                "actionType": action,
                "content": content[:180],
            })
        if len(rows) >= limit:
            break
    return rows


def compact_play_context(play: dict, play_json: dict | None, hints: list[str]) -> dict:
    source = play_json or {}
    return {
        "playId": play["id"],
        "title": play.get("title", ""),
        "genre": play.get("genre", ""),
        "period": play.get("period", ""),
        "summary": (source.get("plot") or play.get("summary") or "")[:900],
        "notes": (source.get("notes") or "")[:350],
        "mainCharacters": [
            {"name": c.get("name", ""), "roleTypeRaw": c.get("roleTypeRaw", "")}
            for c in source.get("mainCharacters", [])[:20]
        ],
        "lineSamples": line_samples(source),
        "existingThemeHints": hints,
    }


def build_payload(batch: list[dict]) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taxonomy": THEME_TAXONOMY,
        "plays": batch,
    }


def response_for_batch(client: DeepSeekJsonClient, cache: JsonlCache, payload: dict) -> tuple[dict, bool]:
    key = stable_hash({"task": SCHEMA_VERSION, "model": client.config.model, "payload": payload})
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    user = "请为 plays 中每部戏标注主题，并严格返回 JSON。输入如下：\n" + json.dumps(payload, ensure_ascii=False)
    value = client.chat_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema_name="play_theme_inference",
        schema=THEME_SCHEMA,
    )
    cache.set(key, value, meta={"model": client.config.model})
    return value, False


def normalize_decisions(raw: dict, expected_ids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in raw.get("decisions", []):
        pid = d.get("playId")
        if pid not in expected_ids:
            continue
        conf = clamp_float(d.get("confidence"), 0.0)
        themes_out = []
        seen = set()
        for item in d.get("themes", []):
            theme = item.get("theme")
            if theme not in ALLOWED_THEMES or theme in seen:
                continue
            seen.add(theme)
            category = item.get("category")
            if category not in THEME_TAXONOMY:
                category = THEME_TO_CATEGORY.get(theme, "其他")
            themes_out.append({
                "theme": theme,
                "category": category,
                "weight": round(clamp_float(item.get("weight"), 0.0), 4),
                "keywords": [str(k)[:20] for k in item.get("keywords", [])[:6] if str(k).strip()],
                "evidence": [str(e)[:180] for e in item.get("evidence", [])[:3] if str(e).strip()],
                "reason": str(item.get("reason") or "")[:280],
            })
        themes_out.sort(key=lambda x: -x["weight"])
        if not themes_out:
            themes_out = [{
                "theme": "其他",
                "category": "其他",
                "weight": 0.2,
                "keywords": [],
                "evidence": [],
                "reason": "证据不足，保留为其他。",
            }]
            conf = min(conf, 0.3)
        out[pid] = {
            "playId": pid,
            "themes": themes_out[:4],
            "summaryTheme": str(d.get("summaryTheme") or themes_out[0]["theme"])[:120],
            "confidence": conf,
        }
    return out


def fallback_from_existing(play: dict, hints: list[str]) -> dict:
    themes = []
    for rank, theme in enumerate(hints[:3]):
        category = THEME_TO_CATEGORY.get(theme, "其他")
        themes.append({
            "theme": theme if theme in ALLOWED_THEMES else "其他",
            "category": category,
            "weight": round(max(0.15, 0.65 - 0.12 * rank), 4),
            "keywords": [],
            "evidence": [play.get("summary", "")[:120]] if play.get("summary") else [],
            "reason": "LLM 未生成结果时沿用既有统计主题作为回退。",
        })
    if not themes:
        themes = [{
            "theme": "其他",
            "category": "其他",
            "weight": 0.2,
            "keywords": [],
            "evidence": [],
            "reason": "无可用主题证据。",
        }]
    return {"playId": play["id"], "themes": themes, "summaryTheme": themes[0]["theme"], "confidence": 0.2}


def process_theme_batch(
    *,
    client: DeepSeekJsonClient,
    cache: JsonlCache,
    batch_contexts: list[dict],
    plays_by_id: dict[str, dict],
    hints: dict[str, list[str]],
    args: argparse.Namespace,
    decisions: dict[str, dict],
    stats: Counter,
    start_label: str,
) -> None:
    payload = build_payload(batch_contexts)
    stats["batches"] += 1
    try:
        raw, from_cache = response_for_batch(client, cache, payload)
        if from_cache:
            stats["cache_hits"] += 1
        parsed = normalize_decisions(raw, {c["playId"] for c in batch_contexts})
        for pid, d in parsed.items():
            if d["confidence"] >= args.min_confidence:
                decisions[pid] = d
                stats["decisions"] += 1
            else:
                decisions[pid] = fallback_from_existing(plays_by_id[pid], hints.get(pid, []))
                stats["fallbacks"] += 1
    except Exception as err:
        if len(batch_contexts) > 1:
            stats["split_retries"] += 1
            mid = max(1, len(batch_contexts) // 2)
            print(
                f"  ! theme batch failed start={start_label}; split {len(batch_contexts)} -> {mid}+{len(batch_contexts) - mid}: {err}",
                flush=True,
            )
            process_theme_batch(
                client=client,
                cache=cache,
                batch_contexts=batch_contexts[:mid],
                plays_by_id=plays_by_id,
                hints=hints,
                args=args,
                decisions=decisions,
                stats=stats,
                start_label=f"{start_label}.a",
            )
            process_theme_batch(
                client=client,
                cache=cache,
                batch_contexts=batch_contexts[mid:],
                plays_by_id=plays_by_id,
                hints=hints,
                args=args,
                decisions=decisions,
                stats=stats,
                start_label=f"{start_label}.b",
            )
            return

        stats["errors"] += 1
        pid = batch_contexts[0]["playId"]
        if args.keep_existing_on_error:
            decisions[pid] = fallback_from_existing(plays_by_id[pid], hints.get(pid, []))
            stats["fallbacks"] += 1
        print(f"  ! theme single failed play={pid} start={start_label}: {err}", flush=True)


def rebuild_themes_json(plays: list[dict], decisions: dict[str, dict]) -> dict:
    play_by_id = {p["id"]: p for p in plays}
    theme_count = Counter()
    genre_theme = Counter()
    cooccur = Counter()
    combos = Counter()
    category_theme_keywords: dict[tuple[str, str], Counter] = defaultdict(Counter)

    play_profiles = []
    themes_records = []
    llm_profiles = []

    for pid, d in decisions.items():
        play = play_by_id.get(pid, {"title": pid, "genre": "其他"})
        top_items = d["themes"][:3]
        top_names = [item["theme"] for item in top_items]
        play_profiles.append({"playId": pid, "title": play.get("title", pid), "topThemes": top_names})
        llm_profiles.append({
            "playId": pid,
            "title": play.get("title", pid),
            "themes": d["themes"],
            "summaryTheme": d.get("summaryTheme", ""),
            "confidence": d.get("confidence", 0),
            "source": "llm",
        })
        for item in d["themes"]:
            if item["weight"] < 0.05:
                continue
            theme = item["theme"]
            category = item["category"]
            themes_records.append({
                "playId": pid,
                "theme": theme,
                "weight": item["weight"],
                "category": category,
                "source": "llm",
                "evidence": item.get("evidence", []),
                "reason": item.get("reason", ""),
            })
            theme_count[theme] += 1
            genre_theme[(play.get("genre", "其他"), theme)] += 1
            keywords = item.get("keywords", []) or [theme]
            for kw in keywords:
                category_theme_keywords[(category, theme)][kw] += 1
        for a, b in combinations(sorted(set(top_names)), 2):
            cooccur[(a, b)] += 1
        combos[tuple(sorted(set(top_names)))] += 1

    sun_by_cat: dict[str, list[dict]] = defaultdict(list)
    for (category, theme), kw_counter in sorted(category_theme_keywords.items()):
        top_keywords = kw_counter.most_common(5)
        if not top_keywords:
            top_keywords = [(theme, theme_count[theme])]
        sun_by_cat[category].append({
            "name": theme,
            "children": [{"name": kw, "value": max(1, int(v))} for kw, v in top_keywords],
        })
    sunburst = {
        "name": "京剧主题",
        "children": [{"name": cat, "children": items} for cat, items in sun_by_cat.items()],
    }

    topic_top_words = []
    for i, ((category, theme), kw_counter) in enumerate(category_theme_keywords.items()):
        words = [w for w, _ in kw_counter.most_common(10)] or [theme]
        topic_top_words.append({
            "topicId": i,
            "name": theme,
            "category": category,
            "topWords": words,
            "topWeights": [float(v) for _, v in kw_counter.most_common(10)] or [float(theme_count[theme])],
            "source": "llm",
        })

    return {
        "sunburst": sunburst,
        "cooccurrenceNodes": [{"id": th, "value": cnt} for th, cnt in theme_count.most_common()],
        "cooccurrenceLinks": [{"source": a, "target": b, "value": v} for (a, b), v in cooccur.most_common(80)],
        "genreDistribution": [{"genre": g, "theme": th, "value": v} for (g, th), v in genre_theme.most_common()],
        "combinations": [{"combination": list(combo), "value": v} for combo, v in combos.most_common(30)],
        "playProfiles": sorted(play_profiles, key=lambda x: x["playId"]),
        "themes": themes_records,
        "topicTopWords": topic_top_words,
        "llmThemeProfiles": sorted(llm_profiles, key=lambda x: x["playId"]),
        "metadata": {"source": "llm", "schemaVersion": SCHEMA_VERSION},
    }


def write_report(stats: Counter, out: dict, config: LLMConfig, elapsed: float, *, write_file: bool) -> None:
    report = [
        "=== augment_themes_llm.py report ===",
        f"model:              {config.model}",
        f"plays requested:    {stats['requested']}",
        f"batches:            {stats['batches']}",
        f"cache hits:         {stats['cache_hits']}",
        f"decisions:          {stats['decisions']}",
        f"fallbacks:          {stats['fallbacks']}",
        f"kept existing:      {stats['kept_existing']}",
        f"errors:             {stats['errors']}",
        f"split retries:      {stats['split_retries']}",
        f"theme records:      {len(out.get('themes', [])) if out else 0}",
        f"elapsed seconds:    {elapsed:.1f}",
    ]
    text = "\n".join(report)
    if write_file:
        (DATA / "_themes_llm_report.txt").write_text(text, encoding="utf-8")
    print(text, flush=True)


def main() -> int:
    args = parse_args()
    t0 = time.time()
    plays_all = load_json(DATA / "plays.json", [])
    current_themes = load_json(DATA / "themes.json", {})
    play_jsons = load_play_jsons()
    hints = existing_theme_hints(current_themes)
    plays = list(plays_all)
    if args.play_id:
        plays = [p for p in plays if p["id"] == args.play_id]
    if args.limit > 0:
        plays = plays[:args.limit]

    print(f"Loaded plays={len(plays)} play_jsons={len(play_jsons)}", flush=True)
    contexts = [
        compact_play_context(p, play_jsons.get(p["id"]), hints.get(p["id"], []))
        for p in plays
    ]
    stats: Counter = Counter(requested=len(contexts))

    if args.dry_run:
        for item in contexts[:5]:
            print(f"  dry-run play: {item['playId']} {item['title']} hints={item['existingThemeHints']}")
        write_report(stats, {}, LLMConfig.from_env(), time.time() - t0, write_file=False)
        print("Dry run: no LLM calls and no files were changed.", flush=True)
        return 0

    client = DeepSeekJsonClient()
    cache = JsonlCache(CACHE)
    decisions: dict[str, dict] = {}
    plays_by_id = {p["id"]: p for p in plays}

    for start in range(0, len(contexts), args.batch_size):
        batch_contexts = contexts[start:start + args.batch_size]
        process_theme_batch(
            client=client,
            cache=cache,
            batch_contexts=batch_contexts,
            plays_by_id=plays_by_id,
            hints=hints,
            args=args,
            decisions=decisions,
            stats=stats,
            start_label=str(start),
        )
        if stats["batches"] % 10 == 0:
            print(f"  batches={stats['batches']} decisions={stats['decisions']} cache={stats['cache_hits']} errors={stats['errors']}", flush=True)

    processed_ids = {p["id"] for p in plays}
    for p in plays_all:
        if p["id"] not in decisions:
            decisions[p["id"]] = fallback_from_existing(p, hints.get(p["id"], []))
            if p["id"] in processed_ids:
                stats["fallbacks"] += 1
            else:
                stats["kept_existing"] += 1

    out = rebuild_themes_json(plays_all, decisions)
    partial_run = args.limit > 0 or bool(args.play_id)
    out_path = DATA / "themes.json"
    if partial_run and not args.write_partial:
        out_path = DATA / "themes_llm_preview.json"
    write_json(out_path, out)
    write_report(stats, out, client.config, time.time() - t0, write_file=True)
    print(f"Wrote: {out_path}", flush=True)
    if partial_run and not args.write_partial:
        print("Partial run: main themes.json was not overwritten. Use --write-partial to override.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
