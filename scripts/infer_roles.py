"""Infer missing / low-confidence character roles with an LLM.

This replaces the previous RandomForest pass. Deterministic extraction still
comes from build_features.py; this script only enriches semantic fields when
evidence is missing or the existing inference is weak.

Environment:
    DEEPSEEK_API_KEY    required unless --dry-run is used
    DEEPSEEK_MODEL      optional, defaults to deepseek-chat
    DEEPSEEK_BASE_URL   optional, defaults to https://api.deepseek.com

Examples:
    python scripts/infer_roles.py --dry-run --limit 20
    python scripts/infer_roles.py --limit 100
    python scripts/infer_roles.py
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
CACHE = DATA / "llm_cache" / "role_inference.jsonl"

LABELS = ["生", "旦", "净", "丑"]
UNKNOWN = "未知"
ROLE_ENUM = LABELS
GENDER_ENUM = ["男", "女", UNKNOWN]
AGE_ENUM = ["少年", "青年", "青壮年", "中年", "老年", UNKNOWN]
SCHEMA_VERSION = "role-inference-v2"


ROLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "charId": {"type": "string"},
                    "roleMain": {"type": "string", "enum": ROLE_ENUM},
                    "roleSubtype": {"type": "string"},
                    "gender": {"type": "string", "enum": GENDER_ENUM},
                    "ageGroup": {"type": "string", "enum": AGE_ENUM},
                    "identity": {"type": "string"},
                    "personalityTags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reason": {"type": "string"},
                },
                "required": [
                    "charId",
                    "roleMain",
                    "roleSubtype",
                    "gender",
                    "ageGroup",
                    "identity",
                    "personalityTags",
                    "confidence",
                    "evidence",
                    "reason",
                ],
            },
        },
    },
    "required": ["decisions"],
}


SYSTEM_PROMPT = """你是一个京剧剧本数据标注员，任务是根据给定证据补全角色语义字段。

规则：
1. 只依据输入里的剧情、主要角色、台词证据、场次共现和称谓判断，不要凭空编造。
2. roleMain 必须从：生、旦、净、丑 中选择一个最可能值；不要输出“未知”，证据不足也要给低置信度的最佳判断。
3. roleSubtype 可写更具体的京剧行当，如老生、小生、武生、青衣、花旦、老旦、武旦、正净、武净、文丑、武丑；不确定时根据 roleMain 写通用子类。
4. gender 尽量从男、女中推断；ageGroup 尽量从少年、青年、青壮年、中年、老年中推断。实在没有线索时才写“未知”。
5. confidence 是 0 到 1 的小数。没有直接证据时不要高于 0.55；只是根据名字/同场角色猜测时不要高于 0.7。
6. evidence 只能摘录或概括输入中出现过的证据，每个角色最多给 3 条。
7. reason 用一句话解释判断依据。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer character roles with an LLM.")
    parser.add_argument("--dry-run", action="store_true", help="Plan requests but do not call the LLM or write data.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of candidate characters to process; 0 means all.")
    parser.add_argument("--play-id", default="", help="Only process one playId.")
    parser.add_argument("--batch-size", type=int, default=8, help="Characters per LLM request.")
    parser.add_argument("--confidence-threshold", type=float, default=0.7, help="Revisit non-main characters below this confidence.")
    parser.add_argument("--min-appearances", type=int, default=2, help="Skip minor characters below this appearance count unless they have evidence.")
    parser.add_argument("--min-llm-confidence", type=float, default=0.45, help="Do not apply non-unknown labels below this LLM confidence.")
    parser.add_argument("--include-main", action="store_true", help="Also revisit main characters when they are low confidence or unlabeled.")
    parser.add_argument("--force", action="store_true", help="Reprocess rows already marked as LLM-inferred.")
    parser.add_argument("--write-unknown", action="store_true", help="Deprecated; roleMain now uses best-effort labels instead of 未知.")
    parser.add_argument("--overwrite-identity", action="store_true", help="Allow LLM identity to override non-empty existing identity.")
    parser.add_argument("--fill-only", action="store_true", help="Do not call the LLM; only fill unresolved roleMain with local best-effort labels.")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_play_jsons() -> dict[str, dict]:
    if not SRC.exists():
        print(f"  ! {SRC} not found; using characters.json evidence only", flush=True)
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


def confidence_of(c: dict) -> float:
    return clamp_float(c.get("confidence", 0.0))


def is_header_labeled(c: dict) -> bool:
    return bool(c.get("isMainCharacter")) and c.get("roleMain") in LABELS and confidence_of(c) >= 0.95


def ensure_source_metadata(chars: list[dict]) -> None:
    for c in chars:
        if c.get("roleInferenceSource"):
            continue
        if c.get("isMainCharacter") and (c.get("roleTypeRaw") or c.get("roleMain") in LABELS):
            c["roleInferenceSource"] = "header"
        elif (not c.get("isMainCharacter")) and c.get("roleMain") in LABELS:
            # Existing repos may already contain RandomForest-era predictions.
            c["roleInferenceSource"] = "legacy"


def needs_llm(c: dict, args: argparse.Namespace) -> bool:
    if c.get("roleInferenceSource") == "llm" and not args.force:
        return False
    if args.play_id and c.get("playId") != args.play_id:
        return False
    if is_header_labeled(c) and not args.include_main:
        return False
    if c.get("appearanceCount", 0) < args.min_appearances and not c.get("evidence"):
        return False

    role_main = c.get("roleMain") or ""
    if role_main not in LABELS:
        return True
    return (not c.get("isMainCharacter")) and confidence_of(c) < args.confidence_threshold


def own_lines_for(name: str, play: dict, limit: int = 6) -> list[dict]:
    lines = [
        ln for ln in play.get("lines", [])
        if ln.get("character") == name and ln.get("content", "").strip()
    ]
    lines.sort(key=lambda ln: len(ln.get("content", "")), reverse=True)
    out = []
    seen = set()
    for ln in lines:
        content = ln.get("content", "").strip()
        if content in seen:
            continue
        seen.add(content)
        out.append({
            "sceneNum": ln.get("sceneNum", 0),
            "actionType": ln.get("actionType", ""),
            "content": content[:180],
        })
        if len(out) >= limit:
            break
    return out


def action_summary(name: str, play: dict) -> list[dict]:
    ct = Counter(
        ln.get("actionType", "")
        for ln in play.get("lines", [])
        if ln.get("character") == name
    )
    return [{"actionType": k, "count": v} for k, v in ct.most_common(8) if k]


def scene_context(name: str, play: dict, char_by_name: dict[str, dict], limit: int = 5) -> list[dict]:
    out = []
    for sc in play.get("scenes", []):
        members = sc.get("characters", [])
        if name not in members:
            continue
        coactors = []
        for other in members:
            if other == name:
                continue
            oc = char_by_name.get(other, {})
            coactors.append({
                "name": other,
                "roleMain": oc.get("roleMain", ""),
                "roleSubtype": oc.get("roleSubtype", ""),
                "identity": oc.get("identity", ""),
            })
        out.append({
            "sceneNum": sc.get("sceneNum", 0),
            "sceneTitle": sc.get("sceneTitle", ""),
            "coactors": coactors[:12],
        })
        if len(out) >= limit:
            break
    return out


def compact_main_characters(play: dict) -> list[dict]:
    return [
        {
            "name": c.get("name", ""),
            "roleTypeRaw": c.get("roleTypeRaw", ""),
        }
        for c in play.get("mainCharacters", [])[:30]
    ]


def build_candidate_context(c: dict, play: dict, char_by_name: dict[str, dict]) -> dict:
    name = c["name"]
    return {
        "charId": c["id"],
        "name": name,
        "current": {
            "roleMain": c.get("roleMain", ""),
            "roleSubtype": c.get("roleSubtype", ""),
            "roleTypeRaw": c.get("roleTypeRaw", ""),
            "gender": c.get("gender", ""),
            "ageGroup": c.get("ageGroup", ""),
            "identity": c.get("identity", ""),
            "confidence": c.get("confidence", 0),
            "isMainCharacter": c.get("isMainCharacter", False),
        },
        "stats": {
            "appearanceCount": c.get("appearanceCount", 0),
            "actionScore": c.get("actionScore", 0),
            "emotionScore": c.get("emotionScore", 0),
        },
        "existingEvidence": c.get("evidence", [])[:3],
        "actionSummary": action_summary(name, play),
        "lineSamples": own_lines_for(name, play),
        "sceneContext": scene_context(name, play, char_by_name),
    }


def build_batch_payload(play_id: str, batch: list[dict], play: dict, chars_by_play: list[dict]) -> dict:
    char_by_name = {c["name"]: c for c in chars_by_play}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "play": {
            "playId": play_id,
            "title": play.get("title", ""),
            "plot": (play.get("plot") or play.get("summary") or "")[:900],
            "notes": (play.get("notes") or "")[:500],
            "mainCharacters": compact_main_characters(play),
        },
        "knownCharacters": [
            {
                "name": c.get("name", ""),
                "roleMain": c.get("roleMain", ""),
                "roleSubtype": c.get("roleSubtype", ""),
                "identity": c.get("identity", ""),
            }
            for c in chars_by_play
            if c.get("roleMain") in LABELS and confidence_of(c) >= 0.8
        ][:40],
        "candidates": [build_candidate_context(c, play, char_by_name) for c in batch],
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

    user = "请为 candidates 中的每个角色补全字段，并严格返回 JSON。输入如下：\n" + json.dumps(payload, ensure_ascii=False)
    value = client.chat_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema_name="character_role_inference",
        schema=ROLE_SCHEMA,
    )
    cache.set(key, value, meta={"model": client.config.model, "playId": payload["play"]["playId"]})
    return value, False


def process_role_batch(
    *,
    client: DeepSeekJsonClient,
    cache: JsonlCache,
    batch: list[dict],
    pid: str,
    play: dict,
    chars_by_play: list[dict],
    char_by_id: dict[str, dict],
    args: argparse.Namespace,
    stats: Counter,
    start_label: str,
) -> None:
    payload = build_batch_payload(pid, batch, play, chars_by_play)
    stats["batches"] += 1
    try:
        raw, from_cache = response_for_batch(client, cache, payload)
        if from_cache:
            stats["cache_hits"] += 1
        decisions = valid_decisions(raw, {c["id"] for c in batch})
        for d in decisions:
            status = apply_decision(char_by_id[d["charId"]], d, args)
            stats[status] += 1
        missing = len(batch) - len(decisions)
        stats["skipped"] += max(missing, 0)
    except Exception as e:
        if len(batch) > 1:
            stats["split_retries"] += 1
            mid = max(1, len(batch) // 2)
            print(
                f"  ! LLM batch failed play={pid} start={start_label}; split {len(batch)} -> {mid}+{len(batch) - mid}: {e}",
                flush=True,
            )
            process_role_batch(
                client=client,
                cache=cache,
                batch=batch[:mid],
                pid=pid,
                play=play,
                chars_by_play=chars_by_play,
                char_by_id=char_by_id,
                args=args,
                stats=stats,
                start_label=f"{start_label}.a",
            )
            process_role_batch(
                client=client,
                cache=cache,
                batch=batch[mid:],
                pid=pid,
                play=play,
                chars_by_play=chars_by_play,
                char_by_id=char_by_id,
                args=args,
                stats=stats,
                start_label=f"{start_label}.b",
            )
            return

        stats["errors"] += 1
        print(f"  ! LLM single failed play={pid} char={batch[0].get('name')} start={start_label}: {e}", flush=True)


def valid_decisions(raw: dict, expected_ids: set[str]) -> list[dict]:
    out = []
    for d in raw.get("decisions", []):
        if not isinstance(d, dict):
            continue
        cid = d.get("charId")
        if cid not in expected_ids:
            continue
        role_main = d.get("roleMain") if d.get("roleMain") in ROLE_ENUM else UNKNOWN
        gender = d.get("gender") if d.get("gender") in GENDER_ENUM else UNKNOWN
        age = d.get("ageGroup") if d.get("ageGroup") in AGE_ENUM else UNKNOWN
        tags = d.get("personalityTags") if isinstance(d.get("personalityTags"), list) else []
        evidence = d.get("evidence") if isinstance(d.get("evidence"), list) else []
        out.append({
            "charId": cid,
            "roleMain": role_main,
            "roleSubtype": str(d.get("roleSubtype") or UNKNOWN),
            "gender": gender,
            "ageGroup": age,
            "identity": str(d.get("identity") or UNKNOWN),
            "personalityTags": [str(t) for t in tags[:5] if str(t).strip()],
            "confidence": clamp_float(d.get("confidence")),
            "evidence": [str(e)[:180] for e in evidence[:3] if str(e).strip()],
            "reason": str(d.get("reason") or "")[:300],
        })
    return out


def fallback_subtype(role_main: str, c: dict) -> str:
    name = c.get("name", "")
    age = c.get("ageGroup", "")
    action_score = float(c.get("actionScore") or 0)
    if role_main == "生":
        if age == "老年" or "老" in name:
            return "老生"
        if age == "少年" or "童" in name or "儿" in name:
            return "娃娃生"
        if action_score > 0.18:
            return "武生"
        if age in ("青年", "青壮年"):
            return "小生"
        return "生"
    if role_main == "旦":
        if age == "老年" or "老" in name:
            return "老旦"
        if action_score > 0.18:
            return "武旦"
        if any(tok in name for tok in ("夫人", "娘娘", "皇后", "母")):
            return "青衣"
        if any(tok in name for tok in ("丫鬟", "小姐", "公主", "姑娘")):
            return "花旦"
        return "旦"
    if role_main == "净":
        return "武净" if action_score > 0.18 else "净"
    if role_main == "丑":
        return "武丑" if action_score > 0.18 else "文丑"
    return UNKNOWN


def best_effort_role_main(c: dict, decision: dict | None = None) -> str:
    name = c.get("name", "")
    gender = (decision or {}).get("gender") or c.get("gender", "")
    identity = (decision or {}).get("identity") or c.get("identity", "")
    action_score = float(c.get("actionScore") or 0)

    female_tokens = ("夫人", "小姐", "公主", "皇后", "娘娘", "娘", "母", "妃", "姬", "氏", "嫂", "姐", "妹", "女", "丫鬟", "婢", "婆")
    child_tokens = ("童", "儿", "娃", "孩")
    clown_tokens = ("家院", "院子", "门子", "报子", "旗牌", "衙役", "皂隶", "公差", "店家", "酒保", "小二", "艄公", "禁卒", "更夫", "丑", "龙套")
    painted_tokens = ("曹操", "张飞", "李逵", "项羽", "董卓", "孟获", "周仓", "典韦", "许褚", "尉迟", "黑", "虎", "霸王", "番王", "大王")

    if any(tok in name for tok in female_tokens) or gender == "女":
        return "旦"
    if any(tok in name for tok in clown_tokens) or identity in ("仆人", "市井人物"):
        return "丑"
    if any(tok in name for tok in painted_tokens) or identity in ("妖魔", "强盗"):
        return "净"
    if action_score > 0.22 and any(tok in name for tok in ("将", "帅", "王", "贼", "神", "妖", "魔")):
        return "净"
    if any(tok in name for tok in child_tokens):
        return "生"
    return "生"


def apply_best_effort_role(c: dict, decision: dict | None, source: str) -> str:
    role_main = best_effort_role_main(c, decision)
    subtype = fallback_subtype(role_main, c)
    conf = clamp_float((decision or {}).get("confidence"), 0.35)
    if conf <= 0:
        conf = 0.35
    c["roleMain"] = role_main
    c["roleSubtype"] = subtype
    c["roleClean"] = subtype
    c["confidence"] = round(min(conf, 0.44), 4)
    c["roleInferenceSource"] = source
    if decision:
        c["llmRoleInference"] = {
            "roleMain": decision.get("roleMain", UNKNOWN),
            "roleSubtype": decision.get("roleSubtype", UNKNOWN),
            "gender": decision.get("gender", UNKNOWN),
            "ageGroup": decision.get("ageGroup", UNKNOWN),
            "identity": decision.get("identity", UNKNOWN),
            "confidence": decision.get("confidence", conf),
            "reason": decision.get("reason", ""),
        }
        c["llmEvidence"] = decision.get("evidence", [])
        c["llmReason"] = decision.get("reason", "")
    else:
        c.setdefault("llmRoleInference", {
            "roleMain": role_main,
            "roleSubtype": subtype,
            "gender": c.get("gender", UNKNOWN),
            "ageGroup": c.get("ageGroup", UNKNOWN),
            "identity": c.get("identity", UNKNOWN),
            "confidence": c["confidence"],
            "reason": "LLM 未返回可用结果，使用本地低置信度兜底推断。",
        })
        c.setdefault("llmEvidence", c.get("evidence", [])[:3])
        c.setdefault("llmReason", "LLM 未返回可用结果，使用本地低置信度兜底推断。")
    return "best_effort"


def apply_decision(c: dict, d: dict, args: argparse.Namespace) -> str:
    role_main = d["roleMain"]
    conf = d["confidence"]
    applied = "skipped"

    c["llmRoleInference"] = {
        "roleMain": role_main,
        "roleSubtype": d["roleSubtype"],
        "gender": d["gender"],
        "ageGroup": d["ageGroup"],
        "identity": d["identity"],
        "confidence": conf,
        "reason": d["reason"],
    }
    c["llmEvidence"] = d["evidence"]
    c["llmReason"] = d["reason"]

    if role_main in LABELS:
        c["roleMain"] = role_main
        subtype = d["roleSubtype"]
        if not subtype or subtype == UNKNOWN:
            subtype = fallback_subtype(role_main, c)
        c["roleSubtype"] = subtype
        c["roleClean"] = subtype
        c["confidence"] = round(conf, 4)
        c["roleInferenceSource"] = "llm" if conf >= args.min_llm_confidence else "llm_low_confidence"
        applied = "label" if conf >= args.min_llm_confidence else "low_confidence_label"
    else:
        applied = apply_best_effort_role(c, d, "llm_best_effort")

    if d["gender"] != UNKNOWN:
        c["gender"] = d["gender"]
    if d["ageGroup"] != UNKNOWN:
        c["ageGroup"] = d["ageGroup"]
    if d["identity"] != UNKNOWN and (
        args.overwrite_identity or c.get("identity") in ("", UNKNOWN, "其他")
    ):
        c["identity"] = d["identity"]
    if d["personalityTags"]:
        c["personalityTags"] = d["personalityTags"]

    return applied


def apply_stored_unknowns(chars: list[dict], args: argparse.Namespace) -> int:
    """Turn prior LLM unknown decisions into best-effort labels without API calls."""
    applied = 0
    for c in chars:
        if c.get("roleMain") in LABELS:
            continue
        stored = c.get("llmRoleInference")
        if not isinstance(stored, dict):
            continue
        if stored.get("roleMain") != UNKNOWN and stored.get("roleMain") not in ("", None):
            continue
        apply_best_effort_role(c, stored, "llm_best_effort")
        applied += 1
    return applied


def fill_remaining_roles(chars: list[dict]) -> int:
    filled = 0
    for c in chars:
        if c.get("roleMain") in LABELS:
            continue
        apply_best_effort_role(c, None, "heuristic_best_effort")
        filled += 1
    return filled


def backfill_gender_age(chars: list[dict]) -> tuple[int, int]:
    try:
        from build_features import infer_age, infer_gender
    except Exception as e:
        print(f"  ! cannot import build_features fallback rules: {e}", flush=True)
        return 0, 0

    gender_filled = 0
    age_filled = 0
    for c in chars:
        if c.get("gender") in ("", UNKNOWN):
            g = infer_gender(c["name"], c.get("roleMain", ""), c.get("roleSubtype", ""))
            if g and g != UNKNOWN:
                c["gender"] = g
                gender_filled += 1
        if c.get("ageGroup") in ("", UNKNOWN):
            a = infer_age(c["name"], c.get("roleMain", ""), c.get("roleSubtype", ""))
            if a and a != UNKNOWN:
                c["ageGroup"] = a
                age_filled += 1
    return gender_filled, age_filled


def confidence_bucket(conf: float) -> str:
    if conf >= 0.9:
        return ">=0.9"
    if conf >= 0.7:
        return "0.7-0.9"
    if conf >= 0.45:
        return "0.45-0.7"
    return "<0.45"


def write_report(chars: list[dict], stats: Counter, config: LLMConfig, elapsed: float, *, write_file: bool = True) -> None:
    role_dist = Counter(c.get("roleMain") or "<empty>" for c in chars)
    source_dist = Counter(c.get("roleInferenceSource") or ("header" if is_header_labeled(c) else "rule") for c in chars)
    conf_dist = Counter(confidence_bucket(confidence_of(c)) for c in chars)
    report = [
        "=== infer_roles.py LLM report ===",
        f"model:              {config.model}",
        f"characters:         {len(chars)}",
        f"candidates:         {stats['candidates']}",
        f"requested:          {stats['requested']}",
        f"batches:            {stats['batches']}",
        f"cache hits:         {stats['cache_hits']}",
        f"applied labels:     {stats['label']}",
        f"low-conf labels:    {stats['low_confidence_label']}",
        f"best-effort labels: {stats['best_effort']}",
        f"final fallbacks:    {stats['final_fallbacks']}",
        f"wrote unknown:      {stats['unknown']}",
        f"skipped decisions:  {stats['skipped']}",
        f"errors:             {stats['errors']}",
        f"split retries:      {stats['split_retries']}",
        f"stored unknown fix: {stats['stored_unknowns']}",
        f"gender backfilled:  {stats['gender_backfilled']}",
        f"age backfilled:     {stats['age_backfilled']}",
        f"elapsed seconds:    {elapsed:.1f}",
        "",
        "--- roleMain distribution ---",
    ]
    for k, v in role_dist.most_common():
        report.append(f"  {k:<8} {v}")
    report.append("\n--- inference source distribution ---")
    for k, v in source_dist.most_common():
        report.append(f"  {k:<12} {v}")
    report.append("\n--- confidence buckets ---")
    for k, v in conf_dist.most_common():
        report.append(f"  {k:<8} {v}")
    if write_file:
        (DATA / "_infer_roles_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report), flush=True)


def main() -> int:
    args = parse_args()
    t0 = time.time()
    print("Loading characters and plays ...", flush=True)
    chars = load_json(DATA / "characters.json")
    plays = load_json(DATA / "plays.json")
    play_meta = {p["id"]: p for p in plays}
    play_jsons = load_play_jsons()
    ensure_source_metadata(chars)
    stored_unknowns = apply_stored_unknowns(chars, args)
    print(f"  plays={len(plays)} play_jsons={len(play_jsons)} characters={len(chars)}", flush=True)

    candidates = [c for c in chars if needs_llm(c, args)]
    if args.limit > 0:
        candidates = candidates[:args.limit]
    stats: Counter = Counter(candidates=len(candidates), requested=len(candidates), stored_unknowns=stored_unknowns)
    print(f"  LLM candidates: {len(candidates)}", flush=True)

    if args.fill_only:
        stats["final_fallbacks"] = fill_remaining_roles(chars)
        gender_filled, age_filled = backfill_gender_age(chars)
        stats["gender_backfilled"] = gender_filled
        stats["age_backfilled"] = age_filled
        write_json(DATA / "characters.json", chars)
        write_report(chars, stats, LLMConfig.from_env(), time.time() - t0)
        print(f"Fill-only mode wrote: {DATA / 'characters.json'}", flush=True)
        return 0

    if args.dry_run:
        for c in candidates[:10]:
            print(f"  dry-run candidate: {c['playId']} {c['name']} role={c.get('roleMain', '')} conf={c.get('confidence', 0)}")
        config = LLMConfig.from_env()
        write_report(chars, stats, config, time.time() - t0, write_file=False)
        print("Dry run: no LLM calls and no files were changed.", flush=True)
        return 0

    client = DeepSeekJsonClient()
    cache = JsonlCache(CACHE)

    chars_by_play: dict[str, list[dict]] = defaultdict(list)
    for c in chars:
        chars_by_play[c["playId"]].append(c)
    char_by_id = {c["id"]: c for c in chars}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        grouped[c["playId"]].append(c)

    for play_i, (pid, group) in enumerate(grouped.items(), 1):
        play = play_jsons.get(pid) or play_meta.get(pid, {"id": pid, "title": pid})
        for start in range(0, len(group), args.batch_size):
            batch = group[start:start + args.batch_size]
            process_role_batch(
                client=client,
                cache=cache,
                batch=batch,
                pid=pid,
                play=play,
                chars_by_play=chars_by_play.get(pid, []),
                char_by_id=char_by_id,
                args=args,
                stats=stats,
                start_label=str(start),
            )
            if stats["batches"] % 10 == 0:
                print(
                    f"  batches={stats['batches']} applied={stats['label']} "
                    f"cache={stats['cache_hits']} errors={stats['errors']}",
                    flush=True,
                )
        print(f"[{play_i}/{len(grouped)}] play={pid} done", flush=True)

    stats["final_fallbacks"] = fill_remaining_roles(chars)
    gender_filled, age_filled = backfill_gender_age(chars)
    stats["gender_backfilled"] = gender_filled
    stats["age_backfilled"] = age_filled

    write_json(DATA / "characters.json", chars)
    write_report(chars, stats, client.config, time.time() - t0)
    print(f"Wrote: {DATA / 'characters.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
