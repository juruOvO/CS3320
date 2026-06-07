"""LLM-enhance narrative structure while preserving numeric tension curves.

Run this after build_narratives.py. It keeps the existing tensionSeries and
performanceDistribution, then asks DeepSeek to assign semantic narrative
patterns, conflict types, and evidence-based turning point descriptions.

Examples:
    python scripts/augment_narratives_llm.py --dry-run --limit 20
    python scripts/augment_narratives_llm.py --limit 100
    python scripts/augment_narratives_llm.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from llm_client import DeepSeekJsonClient, JsonlCache, LLMConfig, clamp_float, stable_hash

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"
CACHE = DATA / "llm_cache" / "narrative_inference.jsonl"
SCHEMA_VERSION = "narrative-inference-v1"

NARRATIVE_PATTERNS = [
    "平稳铺陈型",
    "急起直下型",
    "渐进升级型",
    "中段高潮型",
    "尾重收束型",
    "反转突变型",
    "多峰起伏型",
    "折子片段型",
]

CONFLICT_TYPES = [
    "军事战争冲突",
    "忠奸政治冲突",
    "伦理亲情冲突",
    "爱情婚姻冲突",
    "公案冤屈冲突",
    "复仇报恩冲突",
    "神怪斗法冲突",
    "市井生活冲突",
    "身份命运冲突",
    "其他",
]

NARRATIVE_SCHEMA = {
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
                    "narrativePattern": {"type": "string", "enum": NARRATIVE_PATTERNS},
                    "conflictType": {"type": "string", "enum": CONFLICT_TYPES},
                    "structureSummary": {"type": "string"},
                    "climaxSceneNum": {"type": "integer"},
                    "turningPoints": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "sceneNum": {"type": "integer"},
                                "label": {"type": "string"},
                                "description": {"type": "string"},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                                "reason": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["sceneNum", "label", "description", "evidence", "reason", "confidence"],
                        },
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "playId",
                    "narrativePattern",
                    "conflictType",
                    "structureSummary",
                    "climaxSceneNum",
                    "turningPoints",
                    "confidence",
                ],
            },
        }
    },
    "required": ["decisions"],
}

SYSTEM_PROMPT = """你是京剧叙事结构分析员。请根据剧情简介、场次曲线和代表性场面判断叙事模式与转折点。

规则：
1. tension 曲线是统计信号，不要盲从；要结合剧情证据判断真正的转折、高潮与收束。
2. narrativePattern 必须从枚举中选一个；证据不足时优先选“折子片段型”或根据曲线选择最接近的模式，不要输出“未知”。
3. turningPoints 最多 3 个，sceneNum 必须来自输入场次；description 要能直接用于可视化 tooltip。
4. evidence 只能引用或概括输入中出现的信息。
5. 只输出 JSON Object。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enhance narratives.json with LLM semantic labels.")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates but do not call the LLM or write data.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum plays to process; 0 means all.")
    parser.add_argument("--play-id", default="", help="Only process one playId.")
    parser.add_argument("--batch-size", type=int, default=3, help="Plays per LLM request.")
    parser.add_argument("--min-confidence", type=float, default=0.35, help="Use fallback if play-level confidence is below this.")
    parser.add_argument("--keep-existing-on-error", action="store_true", help="Keep existing narrative labels when a batch fails.")
    parser.add_argument("--write-partial", action="store_true", help="Allow --limit/--play-id runs to overwrite narratives.json and plays.json instead of writing preview files.")
    parser.add_argument("--fill-only", action="store_true", help="Do not call the LLM; replace unknown narrative labels with local fallbacks.")
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


def group_by_play(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["playId"]].append(row)
    for values in out.values():
        values.sort(key=lambda x: x.get("sceneNum", 0))
    return out


def scene_line_samples(play_json: dict, scene_num: int, limit: int = 3) -> list[dict]:
    rows = []
    for ln in play_json.get("lines", []):
        if ln.get("sceneNum") != scene_num:
            continue
        content = ln.get("content", "").strip()
        if not content:
            continue
        rows.append({
            "character": ln.get("character", ""),
            "actionType": ln.get("actionType", ""),
            "content": content[:160],
        })
        if len(rows) >= limit:
            break
    return rows


def scene_context(play_json: dict, curve: list[dict], max_scenes: int = 12) -> list[dict]:
    scenes_by_num = {sc.get("sceneNum"): sc for sc in play_json.get("scenes", [])}
    if len(curve) <= max_scenes:
        chosen = curve
    else:
        # Preserve endpoints and most intense scenes.
        ranked = sorted(curve, key=lambda x: x.get("tension", 0), reverse=True)[: max_scenes - 2]
        keep_nums = {curve[0].get("sceneNum"), curve[-1].get("sceneNum")}
        keep_nums.update(row.get("sceneNum") for row in ranked)
        chosen = [row for row in curve if row.get("sceneNum") in keep_nums]
    out = []
    for row in chosen:
        sn = row.get("sceneNum", 0)
        sc = scenes_by_num.get(sn, {})
        out.append({
            "sceneNum": sn,
            "sceneTitle": sc.get("sceneTitle", ""),
            "stage": row.get("stage", ""),
            "form": row.get("form", ""),
            "tension": row.get("tension", 0),
            "action": row.get("action", 0),
            "emotion": row.get("emotion", 0),
            "characters": sc.get("characters", [])[:12],
            "numLines": sc.get("numLines", 0),
            "lineSamples": scene_line_samples(play_json, sn),
        })
    return out


def compact_context(play: dict, play_json: dict | None, curve: list[dict], cluster: dict, turning: list[dict]) -> dict:
    source = play_json or {}
    return {
        "playId": play["id"],
        "title": play.get("title", ""),
        "genre": play.get("genre", ""),
        "period": play.get("period", ""),
        "summary": (source.get("plot") or play.get("summary") or "")[:900],
        "existingPattern": cluster.get("pattern") or play.get("narrativePattern", ""),
        "curve": [
            {
                "sceneNum": row.get("sceneNum", 0),
                "stage": row.get("stage", ""),
                "form": row.get("form", ""),
                "tension": row.get("tension", 0),
                "action": row.get("action", 0),
                "emotion": row.get("emotion", 0),
            }
            for row in curve
        ],
        "existingTurningPoints": turning[:3],
        "sceneContexts": scene_context(source, curve),
    }


def build_payload(batch: list[dict]) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "narrativePatterns": NARRATIVE_PATTERNS,
        "conflictTypes": CONFLICT_TYPES,
        "plays": batch,
    }


def response_for_batch(client: DeepSeekJsonClient, cache: JsonlCache, payload: dict) -> tuple[dict, bool]:
    key = stable_hash({"task": SCHEMA_VERSION, "model": client.config.model, "payload": payload})
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    user = "请为 plays 中每部戏判断叙事结构，并严格返回 JSON。输入如下：\n" + json.dumps(payload, ensure_ascii=False)
    value = client.chat_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema_name="play_narrative_inference",
        schema=NARRATIVE_SCHEMA,
    )
    cache.set(key, value, meta={"model": client.config.model})
    return value, False


def valid_scene_nums(curve: list[dict]) -> set[int]:
    return {int(row.get("sceneNum", 0)) for row in curve if int(row.get("sceneNum", 0)) > 0}


def normalize_decisions(raw: dict, expected: dict[str, set[int]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in raw.get("decisions", []):
        pid = d.get("playId")
        if pid not in expected:
            continue
        pattern = d.get("narrativePattern") if d.get("narrativePattern") in NARRATIVE_PATTERNS else "折子片段型"
        conflict = d.get("conflictType") if d.get("conflictType") in CONFLICT_TYPES else "其他"
        points = []
        for tp in d.get("turningPoints", [])[:3]:
            try:
                sn = int(tp.get("sceneNum", 0))
            except (TypeError, ValueError):
                continue
            if sn not in expected[pid]:
                continue
            points.append({
                "sceneNum": sn,
                "label": str(tp.get("label") or "转折")[:30],
                "description": str(tp.get("description") or "")[:220],
                "evidence": [str(e)[:180] for e in tp.get("evidence", [])[:3] if str(e).strip()],
                "reason": str(tp.get("reason") or "")[:260],
                "confidence": clamp_float(tp.get("confidence"), 0.0),
            })
        out[pid] = {
            "playId": pid,
            "narrativePattern": pattern,
            "conflictType": conflict,
            "structureSummary": str(d.get("structureSummary") or "")[:360],
            "climaxSceneNum": int(d.get("climaxSceneNum") or 0),
            "turningPoints": points,
            "confidence": clamp_float(d.get("confidence"), 0.0),
        }
    return out


def fallback_decision(play: dict, cluster: dict, turning: list[dict]) -> dict:
    pattern = cluster.get("pattern") or play.get("narrativePattern") or "未知"
    if pattern not in NARRATIVE_PATTERNS:
        # Map old curve-shape labels to semantic labels.
        pattern_map = {
            "平稳型": "平稳铺陈型",
            "急起型": "急起直下型",
            "高潮型": "中段高潮型",
            "尾重型": "尾重收束型",
            "渐进型": "渐进升级型",
            "起伏型": "多峰起伏型",
        }
        pattern = pattern_map.get(pattern, "折子片段型")
    points = []
    for tp in turning[:3]:
        points.append({
            "sceneNum": int(tp.get("sceneNum", 0)),
            "label": tp.get("label", "转折"),
            "description": tp.get("description", ""),
            "evidence": [],
            "reason": "LLM 未生成结果时沿用统计曲线转折点。",
            "confidence": 0.2,
        })
    return {
        "playId": play["id"],
        "narrativePattern": pattern,
        "conflictType": "其他",
        "structureSummary": "沿用统计曲线叙事模式。",
        "climaxSceneNum": points[0]["sceneNum"] if points else 0,
        "turningPoints": points,
        "confidence": 0.2,
    }


def process_narrative_batch(
    *,
    client: DeepSeekJsonClient,
    cache: JsonlCache,
    batch: list[dict],
    curve_by_play: dict[str, list[dict]],
    plays_by_id: dict[str, dict],
    cluster_by_play: dict[str, dict],
    turning_by_play: dict[str, list[dict]],
    args: argparse.Namespace,
    decisions: dict[str, dict],
    stats: Counter,
    start_label: str,
) -> None:
    payload = build_payload(batch)
    stats["batches"] += 1
    try:
        raw, from_cache = response_for_batch(client, cache, payload)
        if from_cache:
            stats["cache_hits"] += 1
        expected = {item["playId"]: valid_scene_nums(curve_by_play[item["playId"]]) for item in batch}
        parsed = normalize_decisions(raw, expected)
        for pid, d in parsed.items():
            if d["confidence"] >= args.min_confidence:
                decisions[pid] = d
                stats["decisions"] += 1
            else:
                decisions[pid] = fallback_decision(plays_by_id[pid], cluster_by_play.get(pid, {}), turning_by_play.get(pid, []))
                stats["fallbacks"] += 1
    except Exception as err:
        if len(batch) > 1:
            stats["split_retries"] += 1
            mid = max(1, len(batch) // 2)
            print(
                f"  ! narrative batch failed start={start_label}; split {len(batch)} -> {mid}+{len(batch) - mid}: {err}",
                flush=True,
            )
            process_narrative_batch(
                client=client,
                cache=cache,
                batch=batch[:mid],
                curve_by_play=curve_by_play,
                plays_by_id=plays_by_id,
                cluster_by_play=cluster_by_play,
                turning_by_play=turning_by_play,
                args=args,
                decisions=decisions,
                stats=stats,
                start_label=f"{start_label}.a",
            )
            process_narrative_batch(
                client=client,
                cache=cache,
                batch=batch[mid:],
                curve_by_play=curve_by_play,
                plays_by_id=plays_by_id,
                cluster_by_play=cluster_by_play,
                turning_by_play=turning_by_play,
                args=args,
                decisions=decisions,
                stats=stats,
                start_label=f"{start_label}.b",
            )
            return

        stats["errors"] += 1
        pid = batch[0]["playId"]
        if args.keep_existing_on_error:
            decisions[pid] = fallback_decision(plays_by_id[pid], cluster_by_play.get(pid, {}), turning_by_play.get(pid, []))
            stats["fallbacks"] += 1
        print(f"  ! narrative single failed play={pid} start={start_label}: {err}", flush=True)


def rebuild_outputs(narratives: dict, plays: list[dict], decisions: dict[str, dict]) -> tuple[dict, list[dict]]:
    clusters_by_id = {pc["playId"]: pc for pc in narratives.get("patternClusters", [])}
    curve_by_play = group_by_play(narratives.get("tensionSeries", []))
    old_turning_by_play = group_by_play(narratives.get("turningPoints", []))
    new_clusters = []
    new_turning = []
    llm_profiles = []

    for play in plays:
        pid = play["id"]
        old_cluster = clusters_by_id.get(pid, {"playId": pid, "title": play.get("title", pid), "genre": play.get("genre", ""), "x": 0, "y": 0})
        d = decisions.get(pid)
        if not d:
            new_clusters.append(old_cluster)
            new_turning.extend(old_turning_by_play.get(pid, []))
            continue
        cluster = dict(old_cluster)
        cluster["pattern"] = d["narrativePattern"]
        cluster["conflictType"] = d["conflictType"]
        cluster["structureSummary"] = d["structureSummary"]
        cluster["narrativeConfidence"] = d["confidence"]
        cluster["narrativeSource"] = "llm"
        new_clusters.append(cluster)

        play["narrativePattern"] = d["narrativePattern"]
        play["conflictType"] = d["conflictType"]

        curve_lookup = {row.get("sceneNum"): row for row in curve_by_play.get(pid, [])}
        points = d["turningPoints"] or old_turning_by_play.get(pid, [])
        for rank, tp in enumerate(points, 1):
            scene_num = int(tp.get("sceneNum", 0))
            curve_row = curve_lookup.get(scene_num, {})
            new_turning.append({
                "playId": pid,
                "scene": f"第{scene_num}场",
                "sceneNum": scene_num,
                "label": tp.get("label") or ("高潮" if rank == 1 else "转折"),
                "tension": curve_row.get("tension", 0),
                "description": tp.get("description") or tp.get("reason", ""),
                "evidence": tp.get("evidence", []),
                "reason": tp.get("reason", ""),
                "confidence": tp.get("confidence", 0),
                "source": tp.get("source", "llm"),
            })
        llm_profiles.append({
            "playId": pid,
            "title": play.get("title", pid),
            "narrativePattern": d["narrativePattern"],
            "conflictType": d["conflictType"],
            "structureSummary": d["structureSummary"],
            "climaxSceneNum": d["climaxSceneNum"],
            "turningPoints": d["turningPoints"],
            "confidence": d["confidence"],
            "source": "llm",
        })

    out = dict(narratives)
    out["patternClusters"] = sorted(new_clusters, key=lambda x: x["playId"])
    out["turningPoints"] = sorted(new_turning, key=lambda x: (x["playId"], x.get("sceneNum", 0)))
    out["llmNarrativeProfiles"] = sorted(llm_profiles, key=lambda x: x["playId"])
    out["metadata"] = {"source": "rule_curve_plus_llm", "schemaVersion": SCHEMA_VERSION}
    return out, plays


def write_report(stats: Counter, out: dict, config: LLMConfig, elapsed: float, *, write_file: bool) -> None:
    pattern_dist = Counter(pc.get("pattern", "") for pc in out.get("patternClusters", [])) if out else Counter()
    report = [
        "=== augment_narratives_llm.py report ===",
        f"model:              {config.model}",
        f"plays requested:    {stats['requested']}",
        f"batches:            {stats['batches']}",
        f"cache hits:         {stats['cache_hits']}",
        f"decisions:          {stats['decisions']}",
        f"fallbacks:          {stats['fallbacks']}",
        f"kept existing:      {stats['kept_existing']}",
        f"errors:             {stats['errors']}",
        f"split retries:      {stats['split_retries']}",
        f"local fixes:        {stats['local_fixes']}",
        f"turning points:     {len(out.get('turningPoints', [])) if out else 0}",
        f"elapsed seconds:    {elapsed:.1f}",
        "",
        "--- pattern distribution ---",
    ]
    for k, v in pattern_dist.most_common():
        report.append(f"  {k:<10} {v}")
    text = "\n".join(report)
    if write_file:
        (DATA / "_narratives_llm_report.txt").write_text(text, encoding="utf-8")
    print(text, flush=True)


def main() -> int:
    args = parse_args()
    t0 = time.time()
    narratives = load_json(DATA / "narratives.json", {})
    plays_all = load_json(DATA / "plays.json", [])
    play_jsons = load_play_jsons()
    curve_by_play = group_by_play(narratives.get("tensionSeries", []))
    cluster_by_play = {pc["playId"]: pc for pc in narratives.get("patternClusters", [])}
    turning_by_play = group_by_play(narratives.get("turningPoints", []))

    candidate_plays = [p for p in plays_all if p["id"] in curve_by_play]
    plays = list(candidate_plays)
    if args.play_id:
        plays = [p for p in plays if p["id"] == args.play_id]
    if args.limit > 0:
        plays = plays[:args.limit]

    contexts = [
        compact_context(
            play,
            play_jsons.get(play["id"]),
            curve_by_play.get(play["id"], []),
            cluster_by_play.get(play["id"], {}),
            turning_by_play.get(play["id"], []),
        )
        for play in plays
    ]
    stats: Counter = Counter(requested=len(contexts))
    print(f"Loaded plays={len(plays)} play_jsons={len(play_jsons)}", flush=True)

    if args.fill_only:
        play_by_id = {p["id"]: p for p in plays_all}
        unknown_ids = {
            pc.get("playId")
            for pc in narratives.get("patternClusters", [])
            if pc.get("pattern") == "未知" or pc.get("conflictType") == "未知"
        }
        unknown_ids.update(
            p["id"]
            for p in plays_all
            if p.get("narrativePattern") == "未知" or p.get("conflictType") == "未知"
        )
        decisions = {}
        for pid in sorted(x for x in unknown_ids if x in play_by_id):
            decisions[pid] = fallback_decision(play_by_id[pid], cluster_by_play.get(pid, {}), turning_by_play.get(pid, []))
        stats["local_fixes"] = len(decisions)
        out, updated_all = rebuild_outputs(narratives, plays_all, decisions)
        write_json(DATA / "narratives.json", out)
        write_json(DATA / "plays.json", updated_all)
        write_report(stats, out, LLMConfig.from_env(), time.time() - t0, write_file=True)
        print(f"Fill-only mode wrote: {DATA / 'narratives.json'} and {DATA / 'plays.json'}", flush=True)
        return 0

    if args.dry_run:
        for item in contexts[:5]:
            print(f"  dry-run play: {item['playId']} {item['title']} curveScenes={len(item['curve'])} existing={item['existingPattern']}")
        write_report(stats, {}, LLMConfig.from_env(), time.time() - t0, write_file=False)
        print("Dry run: no LLM calls and no files were changed.", flush=True)
        return 0

    client = DeepSeekJsonClient()
    cache = JsonlCache(CACHE)
    decisions: dict[str, dict] = {}
    plays_by_id = {p["id"]: p for p in plays}

    for start in range(0, len(contexts), args.batch_size):
        batch = contexts[start:start + args.batch_size]
        process_narrative_batch(
            client=client,
            cache=cache,
            batch=batch,
            curve_by_play=curve_by_play,
            plays_by_id=plays_by_id,
            cluster_by_play=cluster_by_play,
            turning_by_play=turning_by_play,
            args=args,
            decisions=decisions,
            stats=stats,
            start_label=str(start),
        )
        if stats["batches"] % 10 == 0:
            print(f"  batches={stats['batches']} decisions={stats['decisions']} cache={stats['cache_hits']} errors={stats['errors']}", flush=True)

    processed_ids = {p["id"] for p in plays}
    for play in candidate_plays:
        if play["id"] not in decisions:
            decisions[play["id"]] = fallback_decision(play, cluster_by_play.get(play["id"], {}), turning_by_play.get(play["id"], []))
            if play["id"] in processed_ids:
                stats["fallbacks"] += 1
            else:
                stats["kept_existing"] += 1

    out, updated_all = rebuild_outputs(narratives, plays_all, decisions)
    updated_by_id = {p["id"]: p for p in updated_all}
    plays_out = [updated_by_id.get(p["id"], p) for p in plays_all]
    partial_run = args.limit > 0 or bool(args.play_id)
    narratives_path = DATA / "narratives.json"
    plays_path = DATA / "plays.json"
    if partial_run and not args.write_partial:
        narratives_path = DATA / "narratives_llm_preview.json"
        plays_path = DATA / "plays_llm_preview.json"
    write_json(narratives_path, out)
    write_json(plays_path, plays_out)
    write_report(stats, out, client.config, time.time() - t0, write_file=True)
    print(f"Wrote: {narratives_path} and {plays_path}", flush=True)
    if partial_run and not args.write_partial:
        print("Partial run: main narratives.json and plays.json were not overwritten. Use --write-partial to override.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
