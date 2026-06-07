"""Optionally refine relationType labels with an LLM.

Run this after build_relations.py. It keeps the co-occurrence graph and weights
intact, but revisits semantic labels for edges that are still only "共现".

Examples:
    python scripts/augment_relations_llm.py --dry-run --limit 20
    python scripts/augment_relations_llm.py --min-weight 3 --limit 200
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
CACHE = DATA / "llm_cache" / "relation_inference.jsonl"

COMMON = "共现"
UNKNOWN = "未知"
RELATION_ENUM = [
    COMMON,
    "君臣",
    "父子",
    "父女",
    "母子",
    "母女",
    "夫妻",
    "兄弟",
    "姐妹",
    "主仆",
    "师徒",
    "朋友",
    "同僚",
    "敌对",
    "亲属",
    UNKNOWN,
]
SCHEMA_VERSION = "relation-inference-v1"


RELATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "edgeKey": {"type": "string"},
                    "relationType": {"type": "string", "enum": RELATION_ENUM},
                    "confidence": {"type": "number"},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reason": {"type": "string"},
                },
                "required": ["edgeKey", "relationType", "confidence", "evidence", "reason"],
            },
        },
    },
    "required": ["decisions"],
}


SYSTEM_PROMPT = """你是京剧剧本角色关系标注员。

规则：
1. 只依据输入中的剧情、角色属性、同场台词和已有证据判断。
2. 如果只能证明两人同场出现，没有明确语义关系，relationType 必须保持“共现”。
3. 关系类型只能是枚举值之一：共现、君臣、父子、父女、母子、母女、夫妻、兄弟、姐妹、主仆、师徒、朋友、同僚、敌对、亲属、未知。
4. 只有证据清楚时才把“共现”升级为更具体关系；凭姓名或同场猜测不要高于 0.65。
5. evidence 最多 3 条，只能引用或概括输入中出现过的信息。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refine relationType labels with an LLM.")
    parser.add_argument("--dry-run", action="store_true", help="Plan requests but do not call the LLM or write data.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of edges to process; 0 means all candidates.")
    parser.add_argument("--play-id", default="", help="Only process one playId.")
    parser.add_argument("--batch-size", type=int, default=6, help="Edges per LLM request.")
    parser.add_argument("--min-weight", type=int, default=2, help="Only revisit 共现 edges with at least this scene co-occurrence weight.")
    parser.add_argument("--min-llm-confidence", type=float, default=0.55, help="Do not apply specific labels below this confidence.")
    parser.add_argument("--include-specific", action="store_true", help="Also revisit already-specific relation labels.")
    parser.add_argument("--force", action="store_true", help="Reprocess edges already marked as LLM-inferred.")
    parser.add_argument("--fill-only", action="store_true", help="Do not call the LLM; clean unknown relation metadata locally.")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_unknown_relation_metadata(relations: dict) -> int:
    fixed = 0
    for edge in relations.get("edges", []):
        if edge.get("relationType") in ("", UNKNOWN):
            edge["relationType"] = COMMON
            fixed += 1
        if edge.get("relationInferenceSource") == "llm_unknown":
            edge["relationInferenceSource"] = "llm_common"
            fixed += 1
        inf = edge.get("llmRelationInference")
        if isinstance(inf, dict) and inf.get("relationType") in ("", UNKNOWN):
            inf["relationType"] = COMMON
            fixed += 1
    return fixed


def load_play_jsons() -> dict[str, dict]:
    if not SRC.exists():
        print(f"  ! {SRC} not found; using derived data only", flush=True)
        return {}
    out = {}
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            d = load_json(p)
        except Exception as e:
            print(f"  ! failed to read {p}: {e}", flush=True)
            continue
        out[d["playId"]] = d
    return out


def edge_key(e: dict) -> str:
    return f"{e['playId']}|{e['source']}|{e['target']}"


def needs_llm(e: dict, args: argparse.Namespace) -> bool:
    if args.play_id and e.get("playId") != args.play_id:
        return False
    if e.get("relationInferenceSource") == "llm" and not args.force:
        return False
    if not args.include_specific and e.get("relationType") != COMMON:
        return False
    return int(e.get("weight", 0)) >= args.min_weight


def line_samples_for_pair(play: dict, e: dict, max_scenes: int = 3) -> list[dict]:
    if not play:
        return []
    names = {e.get("sourceName"), e.get("targetName")}
    scene_set = set(e.get("scenes", [])[:max_scenes])
    out = []
    for sn in scene_set:
        rows = []
        for ln in play.get("lines", []):
            if ln.get("sceneNum") != sn or ln.get("character") not in names:
                continue
            content = ln.get("content", "").strip()
            if not content:
                continue
            rows.append({
                "character": ln.get("character", ""),
                "actionType": ln.get("actionType", ""),
                "content": content[:160],
            })
            if len(rows) >= 6:
                break
        if rows:
            out.append({"sceneNum": sn, "lines": rows})
    return out


def edge_context(e: dict, play: dict, chars_by_id: dict[str, dict]) -> dict:
    c1 = chars_by_id.get(e["source"], {})
    c2 = chars_by_id.get(e["target"], {})
    return {
        "edgeKey": edge_key(e),
        "currentRelationType": e.get("relationType", COMMON),
        "weight": e.get("weight", 0),
        "scenes": e.get("scenes", [])[:10],
        "source": compact_char(c1, e.get("sourceName", "")),
        "target": compact_char(c2, e.get("targetName", "")),
        "pairLineSamples": line_samples_for_pair(play, e),
    }


def compact_char(c: dict, fallback_name: str) -> dict:
    return {
        "id": c.get("id", ""),
        "name": c.get("name", fallback_name),
        "roleMain": c.get("roleMain", ""),
        "roleSubtype": c.get("roleSubtype", ""),
        "gender": c.get("gender", ""),
        "ageGroup": c.get("ageGroup", ""),
        "identity": c.get("identity", ""),
        "evidence": c.get("evidence", [])[:2],
        "llmEvidence": c.get("llmEvidence", [])[:2],
    }


def build_batch_payload(pid: str, batch: list[dict], play: dict, plays_by_id: dict[str, dict], chars_by_id: dict[str, dict]) -> dict:
    meta = plays_by_id.get(pid, {})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "play": {
            "playId": pid,
            "title": play.get("title") or meta.get("title", pid),
            "plot": (play.get("plot") or meta.get("summary") or "")[:900],
            "genre": meta.get("genre", ""),
            "period": meta.get("period", ""),
        },
        "edges": [edge_context(e, play, chars_by_id) for e in batch],
    }


def response_for_batch(client: DeepSeekJsonClient, cache: JsonlCache, payload: dict) -> tuple[dict, bool]:
    key = stable_hash({
        "task": SCHEMA_VERSION,
        "model": client.config.model,
        "payload": payload,
    })
    cached = cache.get(key)
    if cached is not None:
        return cached, True

    user = "请为 edges 中的每条关系边判断 relationType，并严格返回 JSON。输入如下：\n" + json.dumps(payload, ensure_ascii=False)
    value = client.chat_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema_name="relation_type_inference",
        schema=RELATION_SCHEMA,
    )
    cache.set(key, value, meta={"model": client.config.model, "playId": payload["play"]["playId"]})
    return value, False


def valid_decisions(raw: dict, expected: set[str]) -> list[dict]:
    out = []
    for d in raw.get("decisions", []):
        if not isinstance(d, dict):
            continue
        key = d.get("edgeKey")
        if key not in expected:
            continue
        relation = d.get("relationType") if d.get("relationType") in RELATION_ENUM else UNKNOWN
        evidence = d.get("evidence") if isinstance(d.get("evidence"), list) else []
        out.append({
            "edgeKey": key,
            "relationType": relation,
            "confidence": clamp_float(d.get("confidence")),
            "evidence": [str(e)[:180] for e in evidence[:3] if str(e).strip()],
            "reason": str(d.get("reason") or "")[:300],
        })
    return out


def apply_decision(e: dict, d: dict, min_conf: float) -> str:
    relation = d["relationType"] if d["relationType"] not in (UNKNOWN, "") else COMMON
    conf = d["confidence"]
    e["llmRelationInference"] = {
        "relationType": relation,
        "confidence": conf,
        "reason": d["reason"],
    }
    e["llmRelationEvidence"] = d["evidence"]
    e["llmRelationReason"] = d["reason"]

    if relation == COMMON:
        e["relationInferenceSource"] = "llm_common"
        e["relationConfidence"] = round(conf, 4)
        return "common"
    if conf >= min_conf:
        e["relationType"] = relation
        e["relationInferenceSource"] = "llm"
        e["relationConfidence"] = round(conf, 4)
        return "specific"
    return "low_confidence"


def process_relation_batch(
    *,
    client: DeepSeekJsonClient,
    cache: JsonlCache,
    batch: list[dict],
    pid: str,
    play: dict,
    plays_by_id: dict[str, dict],
    chars_by_id: dict[str, dict],
    edge_by_key: dict[str, dict],
    min_conf: float,
    stats: Counter,
    start_label: str,
) -> None:
    payload = build_batch_payload(pid, batch, play, plays_by_id, chars_by_id)
    stats["batches"] += 1
    try:
        raw, from_cache = response_for_batch(client, cache, payload)
        if from_cache:
            stats["cache_hits"] += 1
        decisions = valid_decisions(raw, {edge_key(e) for e in batch})
        for d in decisions:
            status = apply_decision(edge_by_key[d["edgeKey"]], d, min_conf)
            stats[status] += 1
        stats["low_confidence"] += max(len(batch) - len(decisions), 0)
    except Exception as err:
        if len(batch) > 1:
            stats["split_retries"] += 1
            mid = max(1, len(batch) // 2)
            print(
                f"  ! LLM relation batch failed play={pid} start={start_label}; split {len(batch)} -> {mid}+{len(batch) - mid}: {err}",
                flush=True,
            )
            process_relation_batch(
                client=client,
                cache=cache,
                batch=batch[:mid],
                pid=pid,
                play=play,
                plays_by_id=plays_by_id,
                chars_by_id=chars_by_id,
                edge_by_key=edge_by_key,
                min_conf=min_conf,
                stats=stats,
                start_label=f"{start_label}.a",
            )
            process_relation_batch(
                client=client,
                cache=cache,
                batch=batch[mid:],
                pid=pid,
                play=play,
                plays_by_id=plays_by_id,
                chars_by_id=chars_by_id,
                edge_by_key=edge_by_key,
                min_conf=min_conf,
                stats=stats,
                start_label=f"{start_label}.b",
            )
            return

        stats["errors"] += 1
        edge = batch[0]
        edge["relationInferenceSource"] = edge.get("relationInferenceSource") or "rule"
        print(f"  ! LLM relation single failed play={pid} edge={edge_key(edge)} start={start_label}: {err}", flush=True)


def scene_bucket(scene_num: int, total_scenes: int) -> str:
    if total_scenes <= 1:
        return "起"
    ratio = scene_num / total_scenes
    if ratio <= 0.25:
        return "起"
    if ratio <= 0.5:
        return "承"
    if ratio <= 0.75:
        return "转"
    return "合"


def rebuild_aggregates(relations: dict, plays: list[dict], play_jsons: dict[str, dict]) -> None:
    edges = relations.get("edges", [])
    rel_total = Counter()
    for e in edges:
        rel_total[e.get("relationType", COMMON)] += e.get("weight", 0)
    relations["adjacency"] = [
        {"source": "_global", "target": rt, "value": w}
        for rt, w in rel_total.most_common()
    ]

    play_scene_count = {p["id"]: p.get("sceneCount", 0) for p in plays}
    for pid, play in play_jsons.items():
        play_scene_count[pid] = max((sc.get("sceneNum", 0) for sc in play.get("scenes", [])), default=play_scene_count.get(pid, 0))

    trend = Counter()
    for e in edges:
        total = play_scene_count.get(e["playId"], 0)
        for sn in e.get("scenes", []):
            trend[(scene_bucket(sn, total), e.get("relationType", COMMON))] += 1
    relations["relationTrend"] = [
        {"scene": scene, "relationType": rt, "value": value}
        for (scene, rt), value in trend.most_common()
    ]


def write_report(relations: dict, stats: Counter, config: LLMConfig, elapsed: float, *, write_file: bool = True) -> None:
    rel_dist = Counter(e.get("relationType", COMMON) for e in relations.get("edges", []))
    source_dist = Counter(e.get("relationInferenceSource") or "rule" for e in relations.get("edges", []))
    report = [
        "=== augment_relations_llm.py report ===",
        f"model:              {config.model}",
        f"edges:              {len(relations.get('edges', []))}",
        f"candidates:         {stats['candidates']}",
        f"requested:          {stats['requested']}",
        f"batches:            {stats['batches']}",
        f"cache hits:         {stats['cache_hits']}",
        f"specific labels:    {stats['specific']}",
        f"kept common:        {stats['common']}",
        f"unknown:            {stats['unknown']}",
        f"low confidence:     {stats['low_confidence']}",
        f"errors:             {stats['errors']}",
        f"split retries:      {stats['split_retries']}",
        f"metadata fixed:     {stats['metadata_fixed']}",
        f"elapsed seconds:    {elapsed:.1f}",
        "",
        "--- relationType distribution ---",
    ]
    for k, v in rel_dist.most_common():
        report.append(f"  {k:<8} {v}")
    report.append("\n--- inference source distribution ---")
    for k, v in source_dist.most_common():
        report.append(f"  {k:<12} {v}")
    if write_file:
        (DATA / "_relations_llm_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report), flush=True)


def main() -> int:
    args = parse_args()
    t0 = time.time()
    print("Loading relations, characters, and plays ...", flush=True)
    relations = load_json(DATA / "relations.json")
    chars = load_json(DATA / "characters.json")
    plays = load_json(DATA / "plays.json")
    play_jsons = load_play_jsons()
    plays_by_id = {p["id"]: p for p in plays}
    chars_by_id = {c["id"]: c for c in chars}

    if args.fill_only:
        stats: Counter = Counter()
        stats["metadata_fixed"] = clean_unknown_relation_metadata(relations)
        rebuild_aggregates(relations, plays, play_jsons)
        write_json(DATA / "relations.json", relations)
        write_report(relations, stats, LLMConfig.from_env(), time.time() - t0)
        print(f"Fill-only mode wrote: {DATA / 'relations.json'}", flush=True)
        return 0

    candidates = [e for e in relations.get("edges", []) if needs_llm(e, args)]
    if args.limit > 0:
        candidates = candidates[:args.limit]
    stats: Counter = Counter(candidates=len(candidates), requested=len(candidates))
    print(f"  LLM relation candidates: {len(candidates)}", flush=True)

    if args.dry_run:
        for e in candidates[:10]:
            print(f"  dry-run edge: {edge_key(e)} {e.get('sourceName')} - {e.get('targetName')} weight={e.get('weight')} rel={e.get('relationType')}")
        config = LLMConfig.from_env()
        write_report(relations, stats, config, time.time() - t0, write_file=False)
        print("Dry run: no LLM calls and no files were changed.", flush=True)
        return 0

    client = DeepSeekJsonClient()
    cache = JsonlCache(CACHE)
    edge_by_key = {edge_key(e): e for e in relations.get("edges", [])}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in candidates:
        grouped[e["playId"]].append(e)

    for play_i, (pid, group) in enumerate(grouped.items(), 1):
        play = play_jsons.get(pid) or plays_by_id.get(pid, {"id": pid, "title": pid})
        for start in range(0, len(group), args.batch_size):
            batch = group[start:start + args.batch_size]
            process_relation_batch(
                client=client,
                cache=cache,
                batch=batch,
                pid=pid,
                play=play,
                plays_by_id=plays_by_id,
                chars_by_id=chars_by_id,
                edge_by_key=edge_by_key,
                min_conf=args.min_llm_confidence,
                stats=stats,
                start_label=str(start),
            )
            if stats["batches"] % 10 == 0:
                print(
                    f"  batches={stats['batches']} specific={stats['specific']} "
                    f"cache={stats['cache_hits']} errors={stats['errors']}",
                    flush=True,
                )
        print(f"[{play_i}/{len(grouped)}] play={pid} done", flush=True)

    rebuild_aggregates(relations, plays, play_jsons)
    write_json(DATA / "relations.json", relations)
    write_report(relations, stats, client.config, time.time() - t0)
    print(f"Wrote: {DATA / 'relations.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
