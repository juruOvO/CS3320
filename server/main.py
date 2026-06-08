"""FastAPI backend serving the 8 endpoints defined in BACKEND_API_REQUIREMENTS.md.

Loads all derived data from ../data/*.json at startup, holds it in memory, and
applies the 7 global filter params per request.

Run:  uvicorn server.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"

# ===========================================================
# Load everything at startup
# ===========================================================
def load_json(name: str) -> Any:
    p = DATA / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


print("Loading data ...", flush=True)
PLAYS: list[dict] = load_json("plays.json") or []
CHARS: list[dict] = load_json("characters.json") or []
RELATIONS: dict = load_json("relations.json") or {}
NARRATIVES: dict = load_json("narratives.json") or {}
THEMES: dict = load_json("themes.json") or {}

PLAY_BY_ID: dict[str, dict] = {p["id"]: p for p in PLAYS}
CHARS_BY_ID: dict[str, dict] = {c["id"]: c for c in CHARS}
CHARS_BY_PLAY: dict[str, list[dict]] = defaultdict(list)
for c in CHARS:
    CHARS_BY_PLAY[c["playId"]].append(c)

THEMES_RECORDS: list[dict] = THEMES.get("themes", [])  # [{playId, theme, weight}]
THEMES_BY_PLAY: dict[str, list[dict]] = defaultdict(list)
for t in THEMES_RECORDS:
    THEMES_BY_PLAY[t["playId"]].append(t)

NARRATIVE_TENSIONS: list[dict] = NARRATIVES.get("tensionSeries", [])
TENSIONS_BY_PLAY: dict[str, list[dict]] = defaultdict(list)
for t in NARRATIVE_TENSIONS:
    TENSIONS_BY_PLAY[t["playId"]].append(t)

REL_EDGES: list[dict] = RELATIONS.get("edges", [])
REL_NODES: list[dict] = RELATIONS.get("nodes", [])

# Per-play indices (precomputed once — used to avoid scanning REL_EDGES per request)
REL_EDGES_BY_PLAY: dict[str, list[dict]] = defaultdict(list)
for e in REL_EDGES:
    REL_EDGES_BY_PLAY[e["playId"]].append(e)
REL_NODES_BY_PLAY: dict[str, list[dict]] = defaultdict(list)
for n in REL_NODES:
    REL_NODES_BY_PLAY[n["playId"]].append(n)

# Per-play signature: dominant relation + top theme + pattern + genre + title.
# Used by /api/associations to avoid O(plays × edges) scan per request.
PLAY_SIGNATURE: dict[str, dict] = {}
for pid in PLAY_BY_ID:
    p = PLAY_BY_ID[pid]
    rel_ct = Counter()
    for e in REL_EDGES_BY_PLAY.get(pid, []):
        rel_ct[e["relationType"]] += e.get("weight", 0)
    dom_rel = rel_ct.most_common(1)[0][0] if rel_ct else "共现"
    themes_p = sorted(THEMES_BY_PLAY.get(pid, []), key=lambda t: -t.get("weight", 0))
    top_theme = themes_p[0]["theme"] if themes_p else "未知"
    PLAY_SIGNATURE[pid] = {
        "playId": pid,
        "title": p.get("title", pid),
        "dominantRelation": dom_rel,
        "topTheme": top_theme,
        "narrativePattern": p.get("narrativePattern", ""),
        "genre": p.get("genre", "其他"),
    }

print(f"  plays={len(PLAYS)} chars={len(CHARS)} edges={len(REL_EDGES)} "
      f"themes={len(THEMES_RECORDS)} tensionRows={len(NARRATIVE_TENSIONS)}", flush=True)
print(f"  precomputed PLAY_SIGNATURE for {len(PLAY_SIGNATURE)} plays", flush=True)


# Payload size caps when no narrow filter is applied
MAX_NODES_GLOBAL = 120
MAX_EDGES_GLOBAL = 500
MAX_CHARS_GLOBAL = 500
MAX_TENSION_GLOBAL = 1500
MAX_TURNING_GLOBAL = 300


# ===========================================================
# App
# ===========================================================
app = FastAPI(title="京剧可视分析 API", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================
# Filtering
# ===========================================================
def common_filters(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
) -> dict[str, Optional[str]]:
    return {
        "period": period or None,
        "genre": genre or None,
        "playId": playId or None,
        "roleType": roleType or None,
        "characterId": characterId or None,
        "theme": theme or None,
        "narrativePattern": narrativePattern or None,
    }


def filter_play_ids(filters: dict) -> set[str]:
    out_ids: set[str] = set()
    theme_ids: Optional[set[str]] = None
    if filters["theme"]:
        theme_ids = {t["playId"] for t in THEMES_RECORDS if t["theme"] == filters["theme"]}
    for p in PLAYS:
        if filters["period"] and p.get("period") != filters["period"]:
            continue
        if filters["genre"] and p.get("genre") != filters["genre"]:
            continue
        if filters["playId"] and p["id"] != filters["playId"]:
            continue
        if filters["narrativePattern"] and p.get("narrativePattern") != filters["narrativePattern"]:
            continue
        if theme_ids is not None and p["id"] not in theme_ids:
            continue
        out_ids.add(p["id"])

    if filters["roleType"] or filters["characterId"]:
        matching_char_play_ids = {
            c["playId"]
            for c in CHARS
            if (not filters["roleType"] or c.get("roleMain") == filters["roleType"])
            and (not filters["characterId"] or c["id"] == filters["characterId"])
        }
        out_ids &= matching_char_play_ids

    return out_ids


def filter_chars(filters: dict, play_ids: set[str]) -> list[dict]:
    out = []
    for c in CHARS:
        if c["playId"] not in play_ids:
            continue
        if filters["roleType"] and c.get("roleMain") != filters["roleType"]:
            continue
        if filters["characterId"] and c["id"] != filters["characterId"]:
            continue
        out.append(c)
    return out


def scene_sort_key(row: dict) -> int:
    scene_num = row.get("sceneNum")
    if isinstance(scene_num, (int, float)):
        return int(scene_num)
    scene = str(row.get("scene", ""))
    digits = "".join(ch for ch in scene if ch.isdigit())
    return int(digits) if digits else 10**9


def select_complete_tension_curves(tension_series: list[dict], max_rows: int) -> tuple[list[dict], set[str]]:
    """Keep whole play curves under the global payload cap."""
    by_play: dict[str, list[dict]] = defaultdict(list)
    for row in tension_series:
        by_play[row["playId"]].append(row)
    for rows in by_play.values():
        rows.sort(key=scene_sort_key)

    grouped_ids: dict[str, list[str]] = defaultdict(list)
    for play_id in by_play:
        play = PLAY_BY_ID.get(play_id, {})
        pattern = play.get("narrativePattern") or ""
        grouped_ids[pattern].append(play_id)

    for ids in grouped_ids.values():
        ids.sort(key=lambda pid: (PLAY_BY_ID.get(pid, {}).get("genre", ""), pid))

    selected_rows: list[dict] = []
    selected_ids: set[str] = set()
    patterns = sorted(grouped_ids)
    while patterns:
        progressed = False
        for pattern in patterns:
            ids = grouped_ids[pattern]
            while ids:
                play_id = ids.pop(0)
                rows = by_play[play_id]
                if selected_rows and len(selected_rows) + len(rows) > max_rows:
                    continue
                selected_rows.extend(rows)
                selected_ids.add(play_id)
                progressed = True
                break
        patterns = [pattern for pattern in patterns if grouped_ids[pattern]]
        if not progressed:
            break

    return selected_rows, selected_ids


def build_theme_sunburst(profiles: list[dict]) -> dict[str, Any]:
    genre_theme_counter: dict[str, Counter] = defaultdict(Counter)

    for profile in profiles:
        play_meta = PLAY_BY_ID.get(profile["playId"], {})
        genre = play_meta.get("genre") or "其他"
        for theme_name in profile.get("topThemes", []):
            genre_theme_counter[genre][theme_name] += 1

    return {
        "name": "京剧主题",
        "children": [
            {
                "name": genre,
                "children": [
                    {"name": theme_name, "value": value}
                    for theme_name, value in theme_counter.most_common()
                ],
            }
            for genre, theme_counter in sorted(genre_theme_counter.items(), key=lambda item: item[0])
        ],
    }


def performance_cue_for_character(character: dict) -> str:
    evidence_text = " ".join(character.get("evidence", []))
    has_singing_cue = any(token in evidence_text for token in ["西皮", "二黄", "慢板", "原板", "流水", "摇板", "散板", "唱", "板"])
    has_speech_cue = "·白】" in evidence_text or "念" in evidence_text or "白" in evidence_text

    if character.get("actionScore", 0) >= 0.35:
        return "做打线索强"
    if has_singing_cue or has_speech_cue:
        return "唱念线索强"
    if character.get("emotionScore", 0) >= 0.22:
        return "情感推动强"
    if character.get("appearanceCount", 0) >= 8:
        return "出场高频"
    return "辅助角色"


# ===========================================================
# /api/filter-options
# ===========================================================
@app.get("/api/filter-options")
def get_filter_options(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    period_ids = filter_play_ids({**filters, "period": None})
    genre_ids = filter_play_ids({**filters, "genre": None})
    play_ids = filter_play_ids({**filters, "playId": None})
    role_ids = filter_play_ids({**filters, "roleType": None, "characterId": None})
    theme_ids = filter_play_ids({**filters, "theme": None})
    pattern_ids = filter_play_ids({**filters, "narrativePattern": None})

    periods = sorted({PLAY_BY_ID[pid]["period"] for pid in period_ids if pid in PLAY_BY_ID and PLAY_BY_ID[pid].get("period")})
    genres = sorted({PLAY_BY_ID[pid]["genre"] for pid in genre_ids if pid in PLAY_BY_ID and PLAY_BY_ID[pid].get("genre")})
    plays = sorted(
        [{"id": PLAY_BY_ID[pid]["id"], "title": PLAY_BY_ID[pid]["title"]} for pid in play_ids if pid in PLAY_BY_ID],
        key=lambda x: x["id"],
    )
    role_types = sorted({c["roleMain"] for c in CHARS if c.get("roleMain") and c["playId"] in role_ids})
    themes = sorted({t["theme"] for t in THEMES_RECORDS if t.get("theme") and t["playId"] in theme_ids})
    patterns = sorted({
        PLAY_BY_ID[pid]["narrativePattern"]
        for pid in pattern_ids
        if pid in PLAY_BY_ID and PLAY_BY_ID[pid].get("narrativePattern")
    })
    return {
        "periods": periods,
        "genres": genres,
        "plays": plays,
        "roleTypes": role_types,
        "themes": themes,
        "narrativePatterns": patterns,
    }


# ===========================================================
# /api/overview
# ===========================================================
@app.get("/api/overview")
def get_overview(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)
    chars = filter_chars(filters, play_ids)
    relevant_plays = [PLAY_BY_ID[i] for i in play_ids if i in PLAY_BY_ID]

    # summary
    inferred_count = sum(1 for c in chars if not c.get("isMainCharacter") and c.get("roleMain"))
    theme_set = {t["theme"] for pid in play_ids for t in THEMES_BY_PLAY.get(pid, [])}
    relation_count = sum(1 for e in REL_EDGES if e["playId"] in play_ids)
    avg_scene = (sum(p.get("sceneCount", 0) for p in relevant_plays) /
                 max(len(relevant_plays), 1))
    summary = {
        "playCount": len(relevant_plays),
        "characterCount": len(chars),
        "inferredRoleCount": inferred_count,
        "themeCount": len(theme_set),
        "relationCount": relation_count,
        "avgSceneCount": round(avg_scene, 2),
    }

    # period × genre
    pg = Counter()
    for p in relevant_plays:
        pg[(p.get("period", "未知"), p.get("genre", "其他"))] += 1
    period_genre = [
        {"period": pe, "genre": ge, "value": v}
        for (pe, ge), v in pg.most_common()
    ]

    # role distribution
    rd = Counter(c["roleMain"] for c in chars if c.get("roleMain"))
    role_distribution = [{"roleType": k, "value": v} for k, v in rd.most_common()]

    # top themes
    tc = Counter()
    for pid in play_ids:
        for t in THEMES_BY_PLAY.get(pid, []):
            tc[t["theme"]] += 1
    top_themes = [{"theme": k, "value": v} for k, v in tc.most_common(15)]

    # narrative patterns
    np_ct = Counter(p.get("narrativePattern", "") for p in relevant_plays if p.get("narrativePattern"))
    narr_patterns = [{"pattern": k, "value": v} for k, v in np_ct.most_common()]

    play_list = [
        {
            "id": p["id"],
            "title": p["title"],
            "period": p.get("period", ""),
            "genre": p.get("genre", ""),
            "sceneCount": p.get("sceneCount", 0),
        }
        for p in relevant_plays
    ]
    play_list.sort(key=lambda x: x["id"])

    return {
        "summary": summary,
        "periodGenreDistribution": period_genre,
        "roleDistribution": role_distribution,
        "topThemes": top_themes,
        "narrativePatterns": narr_patterns,
        "apiGuide": [
            {"endpoint": "/api/overview", "description": "总览统计与剧目清单"},
            {"endpoint": "/api/character-roles", "description": "角色行当推断"},
            {"endpoint": "/api/relations", "description": "角色关系网络"},
            {"endpoint": "/api/themes", "description": "主题结构"},
            {"endpoint": "/api/narratives", "description": "叙事张力分析"},
            {"endpoint": "/api/associations", "description": "综合关联分析"},
        ],
        "playList": play_list,
    }


# ===========================================================
# /api/character-roles
# ===========================================================
@app.get("/api/character-roles")
def get_character_roles(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)
    chars = filter_chars(filters, play_ids)

    # Sankey: period → performance cue → roleMain
    sankey_pairs1 = Counter()  # (period, performance cue)
    sankey_pairs2 = Counter()  # (performance cue, roleMain)
    for c in chars:
        play = PLAY_BY_ID.get(c["playId"], {})
        period_v = play.get("period", "未知时期")
        cue = performance_cue_for_character(c)
        role = c.get("roleMain") or c.get("roleSubtype") or "未识别行当"
        sankey_pairs1[(period_v, cue)] += 1
        sankey_pairs2[(cue, role)] += 1

    # Build sankey node list with category for each layer
    nodes_seen: dict[str, str] = {}  # name -> category
    for (period_v, cue), _ in sankey_pairs1.items():
        nodes_seen.setdefault(period_v, "时期")
        nodes_seen.setdefault(cue, "表演线索")
    for (cue, role), _ in sankey_pairs2.items():
        nodes_seen.setdefault(cue, "表演线索")
        nodes_seen.setdefault(role, "行当")
    sankey_nodes = [{"name": n, "category": c} for n, c in nodes_seen.items()]
    sankey_links = [
        {"source": period_v, "target": cue, "value": v}
        for (period_v, cue), v in sankey_pairs1.items()
    ] + [
        {"source": cue, "target": role, "value": v}
        for (cue, role), v in sankey_pairs2.items()
    ]

    # Heatmap: period × roleType × feature (avg actionScore / emotionScore / appearanceCount)
    feature_aggregate: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for c in chars:
        p = PLAY_BY_ID.get(c["playId"], {})
        period_v = p.get("period", "未知")
        role = c.get("roleMain", "未知")
        feature_aggregate[(period_v, role, "actionScore")].append(c.get("actionScore", 0))
        feature_aggregate[(period_v, role, "emotionScore")].append(c.get("emotionScore", 0))
        feature_aggregate[(period_v, role, "appearanceCount")].append(c.get("appearanceCount", 0))
    heatmap = []
    for (pe, ro, feat), vals in feature_aggregate.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        heatmap.append({"period": pe, "roleType": ro, "feature": feat, "value": round(avg, 4)})

    # Timeline: period × roleType count
    timeline_ct = Counter()
    for c in chars:
        p = PLAY_BY_ID.get(c["playId"], {})
        timeline_ct[(p.get("period", "未知"), c.get("roleMain", "未知"))] += 1
    timeline = [
        {"period": pe, "roleType": ro, "value": v}
        for (pe, ro), v in timeline_ct.most_common()
    ]

    # Characters list — cap when no narrow filter, keep top-N by appearanceCount
    narrow_filter = bool(filters["playId"] or filters["characterId"])
    chars_sorted = sorted(chars, key=lambda c: -c.get("appearanceCount", 0))
    if not narrow_filter and len(chars_sorted) > MAX_CHARS_GLOBAL:
        chars_sorted = chars_sorted[:MAX_CHARS_GLOBAL]
    char_records = []
    for c in chars_sorted:
        evidence = c.get("evidence", [])
        if not narrow_filter:
            evidence = evidence[:1]
        char_records.append({
            "id": c["id"],
            "playId": c["playId"],
            "name": c["name"],
            "gender": c.get("gender", "未知"),
            "ageGroup": c.get("ageGroup", "未知"),
            "identity": c.get("identity", "其他"),
            "personalityTags": c.get("personalityTags", []),
            "roleMain": c.get("roleMain", ""),
            "roleSubtype": c.get("roleSubtype", ""),
            "confidence": c.get("confidence", 0.0),
            "actionScore": c.get("actionScore", 0.0),
            "emotionScore": c.get("emotionScore", 0.0),
            "appearanceCount": c.get("appearanceCount", 0),
            "evidence": evidence,
        })

    return {
        "sankeyNodes": sankey_nodes,
        "sankeyLinks": sankey_links,
        "heatmap": heatmap,
        "timeline": timeline,
        "characters": char_records,
        "totalCharacters": len(chars),
    }


# ===========================================================
# /api/relations
# ===========================================================
@app.get("/api/relations")
def get_relations(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)

    # Use per-play index instead of scanning the global edge list every request
    edges: list[dict] = []
    nodes: list[dict] = []
    for pid in play_ids:
        edges.extend(REL_EDGES_BY_PLAY.get(pid, []))
        nodes.extend(REL_NODES_BY_PLAY.get(pid, []))

    # Optional further filter by roleType / characterId
    if filters["roleType"]:
        keep_node_ids = {n["id"] for n in nodes if n.get("roleType") == filters["roleType"]}
        nodes = [n for n in nodes if n["id"] in keep_node_ids]
        edges = [e for e in edges if e["source"] in keep_node_ids and e["target"] in keep_node_ids]
    if filters["characterId"]:
        edges = [e for e in edges if e["source"] == filters["characterId"] or e["target"] == filters["characterId"]]
        keep_node_ids = {filters["characterId"]}
        for edge in edges:
            keep_node_ids.add(edge["source"])
            keep_node_ids.add(edge["target"])
        nodes = [n for n in nodes if n["id"] in keep_node_ids]

    # When no playId narrows the request, the graph is huge (~14k nodes / 49k edges).
    # Force-directed rendering chokes — return a top-N node subgraph instead.
    narrow_filter = bool(filters["playId"] or filters["characterId"])
    total_nodes_before_cap = len(nodes)
    total_edges_before_cap = len(edges)
    if not narrow_filter and len(nodes) > MAX_NODES_GLOBAL:
        nodes_sorted = sorted(nodes, key=lambda n: -n.get("size", 0))[:MAX_NODES_GLOBAL]
        keep_ids = {n["id"] for n in nodes_sorted}
        nodes = nodes_sorted
        edges = [e for e in edges
                 if e["source"] in keep_ids and e["target"] in keep_ids][:MAX_EDGES_GLOBAL]

    # adjacency aggregated by relationType
    adj_ct = Counter()
    for e in edges:
        adj_ct[(e["relationType"], e["relationType"])] += e["weight"]
    adjacency = [
        {"source": rt, "target": rt, "value": v}
        for (rt, _), v in adj_ct.items()
    ]

    # metrics by genre (from precomputed)
    metrics = RELATIONS.get("metrics", [])
    if filters["genre"]:
        metrics = [m for m in metrics if m.get("genre") == filters["genre"]]

    # relationTrend (recompute using filtered edges)
    trend_ct = Counter()
    for e in edges:
        pid = e["playId"]
        sc_total = max((s["sceneNum"] for s in []), default=0)
        play = PLAY_BY_ID.get(pid)
        if not play:
            continue
        sc_total = play.get("sceneCount", 0) or 1
        for sn in e["scenes"]:
            ratio = sn / sc_total
            bucket = "启" if ratio <= 0.25 else "承" if ratio <= 0.5 else "转" if ratio <= 0.75 else "合"
            trend_ct[(bucket, e["relationType"])] += 1
    relation_trend = [
        {"scene": s, "relationType": r, "value": v}
        for (s, r), v in trend_ct.most_common()
    ]

    return {
        "nodes": nodes,
        "links": [
            {
                "source": e["source"],
                "target": e["target"],
                "relationType": e["relationType"],
                "weight": e["weight"],
                "scenes": [f"第{n}场" for n in e["scenes"]],
            }
            for e in edges
        ],
        "adjacency": adjacency,
        "metrics": metrics,
        "relationTrend": relation_trend,
        "totals": {
            "nodes": total_nodes_before_cap,
            "edges": total_edges_before_cap,
            "capped": not narrow_filter and total_nodes_before_cap > MAX_NODES_GLOBAL,
        },
    }


# ===========================================================
# /api/themes
# ===========================================================
@app.get("/api/themes")
def get_themes(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)

    # When no filter narrows things, return the precomputed structures
    no_filter = not any(filters.values())
    if no_filter:
        return {
            "sunburst": THEMES.get("sunburst", {"name": "京剧主题", "children": []}),
            "cooccurrenceNodes": THEMES.get("cooccurrenceNodes", []),
            "cooccurrenceLinks": THEMES.get("cooccurrenceLinks", []),
            "genreDistribution": THEMES.get("genreDistribution", []),
            "combinations": THEMES.get("combinations", []),
            "playProfiles": THEMES.get("playProfiles", []),
        }

    # Recompute against filtered plays
    profiles = [pp for pp in THEMES.get("playProfiles", []) if pp["playId"] in play_ids]
    theme_count = Counter()
    cooccur = Counter()
    combos = Counter()
    genre_theme = Counter()
    for pp in profiles:
        p_meta = PLAY_BY_ID.get(pp["playId"], {})
        themes_pp = pp.get("topThemes", [])
        for th in themes_pp:
            theme_count[th] += 1
            genre_theme[(p_meta.get("genre", "其他"), th)] += 1
        for a, b in combinations(sorted(set(themes_pp)), 2):
            cooccur[(a, b)] += 1
        combos[tuple(sorted(set(themes_pp)))] += 1

    return {
        "sunburst": build_theme_sunburst(profiles),
        "cooccurrenceNodes": [{"id": th, "value": cnt} for th, cnt in theme_count.most_common()],
        "cooccurrenceLinks": [
            {"source": a, "target": b, "value": v}
            for (a, b), v in cooccur.most_common(50)
        ],
        "genreDistribution": [
            {"genre": g, "theme": th, "value": v}
            for (g, th), v in genre_theme.most_common()
        ],
        "combinations": [
            {"combination": list(c), "value": v}
            for c, v in combos.most_common(20)
        ],
        "playProfiles": profiles,
    }


# ===========================================================
# /api/narratives
# ===========================================================
@app.get("/api/narratives")
def get_narratives(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)

    # When a single play is selected, don't reduce the 叙事曲线 to one lonely line —
    # add a small 对照组 of plays sharing the same narrativePattern. The chart then
    # highlights the focus play and dims the peers, so "对照各剧目" still holds.
    focus_play_id = ""
    if filters["playId"] and filters["playId"] in PLAY_BY_ID:
        focus_play_id = filters["playId"]
        pattern = PLAY_BY_ID[focus_play_id].get("narrativePattern", "")
        peers = [
            p for p in PLAYS
            if p["id"] != focus_play_id
            and p.get("narrativePattern") == pattern
            and p.get("sceneCount", 0) > 0
        ]
        peers.sort(key=lambda p: -p.get("sceneCount", 0))
        play_ids = {focus_play_id} | {p["id"] for p in peers[:5]}

    tension_series = [t for t in NARRATIVE_TENSIONS if t["playId"] in play_ids]

    # performance distribution: stage × form within filtered set
    perf_ct = Counter()
    for t in tension_series:
        perf_ct[(t["stage"], t["form"])] += 1
    perf_dist = [
        {"stage": s, "form": f, "value": v}
        for (s, f), v in perf_ct.most_common()
    ]

    clusters = [pc for pc in NARRATIVES.get("patternClusters", []) if pc["playId"] in play_ids]
    turning = [tp for tp in NARRATIVES.get("turningPoints", []) if tp["playId"] in play_ids]

    # Cap when no narrow filter — frontend can't render thousands of points
    narrow_filter = bool(filters["playId"] or filters["characterId"])
    total_tension_before_cap = len(tension_series)
    total_turning_before_cap = len(turning)
    if not narrow_filter and len(tension_series) > MAX_TENSION_GLOBAL:
        tension_series, capped_play_ids = select_complete_tension_curves(tension_series, MAX_TENSION_GLOBAL)
        clusters = [pc for pc in clusters if pc["playId"] in capped_play_ids]
        turning = [tp for tp in turning if tp["playId"] in capped_play_ids]
    if not narrow_filter and len(turning) > MAX_TURNING_GLOBAL:
        turning = sorted(turning, key=lambda t: -t.get("tension", 0))[:MAX_TURNING_GLOBAL]

    return {
        "stages": NARRATIVES.get("stages", []),
        "tensionSeries": tension_series,
        "performanceDistribution": perf_dist,
        "patternClusters": clusters,
        "turningPoints": turning,
        "focusPlayId": focus_play_id,
        "totals": {
            "tensionSeries": total_tension_before_cap,
            "turningPoints": total_turning_before_cap,
            "capped": not narrow_filter and total_tension_before_cap > MAX_TENSION_GLOBAL,
        },
    }


# ===========================================================
# /api/associations
# ===========================================================
@app.get("/api/associations")
def get_associations(
    period: Optional[str] = None,
    genre: Optional[str] = None,
    playId: Optional[str] = None,
    roleType: Optional[str] = None,
    characterId: Optional[str] = None,
    theme: Optional[str] = None,
    narrativePattern: Optional[str] = None,
):
    """Cross-analysis: how relation types × themes × narrative patterns co-vary."""
    filters = common_filters(period, genre, playId, roleType, characterId, theme, narrativePattern)
    play_ids = filter_play_ids(filters)

    # Per-play signatures are precomputed at startup — just look them up.
    play_signatures: list[dict] = [PLAY_SIGNATURE[pid] for pid in play_ids if pid in PLAY_SIGNATURE]

    # The scatter (clusters) needs a background distribution: when a single play is
    # selected, don't collapse it to one dot — show the same filter set ignoring
    # playId, and highlight the selected one. So you can see where the play sits.
    focus_play_id = filters["playId"] if (filters["playId"] and filters["playId"] in PLAY_BY_ID) else ""
    if focus_play_id:
        cluster_ids = filter_play_ids({**filters, "playId": None})
    else:
        cluster_ids = play_ids
    cluster_sigs: list[dict] = [PLAY_SIGNATURE[pid] for pid in cluster_ids if pid in PLAY_SIGNATURE]

    sankey_links_ct = Counter()
    matrix_ct = Counter()  # (relationFeature, targetFeature)
    for sig in play_signatures:
        genre_v = sig["genre"]
        dom_rel = sig["dominantRelation"]
        top_theme = sig["topTheme"]
        pattern = sig["narrativePattern"]
        sankey_links_ct[(genre_v, dom_rel)] += 1
        sankey_links_ct[(dom_rel, top_theme)] += 1
        sankey_links_ct[(top_theme, pattern)] += 1
        matrix_ct[(dom_rel, top_theme)] += 1

    nodes_cat = {}
    for (a, b), _ in sankey_links_ct.items():
        nodes_cat.setdefault(a, "?")
        nodes_cat.setdefault(b, "?")
    # try to label categories from origin layer
    for d in play_signatures:
        nodes_cat[d["genre"]] = "类型"
        nodes_cat[d["dominantRelation"]] = "关系"
        nodes_cat[d["topTheme"]] = "主题"
        nodes_cat[d["narrativePattern"]] = "叙事"
    sankey_nodes = [{"name": n, "category": c} for n, c in nodes_cat.items()]
    sankey_links = [{"source": a, "target": b, "value": v}
                    for (a, b), v in sankey_links_ct.items()]
    matrix = [
        {"relationFeature": rt, "targetFeature": th, "value": v}
        for (rt, th), v in matrix_ct.most_common()
    ]

    # clusters: re-use narratives.patternClusters but enrich with topTheme + dominantRelation.
    # Uses cluster_sigs (background distribution) so the scatter keeps many points.
    base_clusters = {pc["playId"]: pc for pc in NARRATIVES.get("patternClusters", [])}
    clusters: list[dict] = []
    for sig in cluster_sigs:
        b = base_clusters.get(sig["playId"])
        if not b:
            continue
        clusters.append({
            "playId": sig["playId"],
            "title": sig["title"],
            "genre": sig["genre"],
            "x": b["x"],
            "y": b["y"],
            "pattern": sig["narrativePattern"],
            "topTheme": sig["topTheme"],
            "dominantRelation": sig["dominantRelation"],
        })

    # association rules — simple frequency-based: which (relation, theme) co-occur the most
    rules = []
    for idx, ((rt, th), v) in enumerate(matrix_ct.most_common(15), 1):
        support = v / max(len(play_signatures), 1)
        # confidence: of plays with this relation, fraction that also have this theme
        with_rel = sum(1 for s in play_signatures if s["dominantRelation"] == rt)
        confidence = v / with_rel if with_rel else 0
        rules.append({
            "id": f"R{idx}",
            "title": f"{rt} ⇒ {th}",
            "support": round(support, 4),
            "confidence": round(confidence, 4),
            "description": f"{rt}主导的剧本中，常以「{th}」为核心主题",
            "samples": [s["playId"] for s in play_signatures
                        if s["dominantRelation"] == rt and s["topTheme"] == th][:5],
        })

    return {
        "sankeyNodes": sankey_nodes,
        "sankeyLinks": sankey_links,
        "matrix": matrix,
        "clusters": clusters,
        "rules": rules,
        "focusPlayId": focus_play_id,
    }


# ===========================================================
# /api/plays/:playId
# ===========================================================
@app.get("/api/plays/{play_id}")
def get_play_detail(play_id: str):
    p = PLAY_BY_ID.get(play_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"play {play_id} not found")

    chars = CHARS_BY_PLAY.get(play_id, [])
    themes_p = sorted(THEMES_BY_PLAY.get(play_id, []), key=lambda t: -t.get("weight", 0))
    tensions_p = sorted(TENSIONS_BY_PLAY.get(play_id, []), key=lambda t: t["sceneNum"])

    # Lightweight character list for detail page
    char_list = []
    for c in chars[:50]:
        related = [e["targetName"] if e["source"] == c["id"] else e["sourceName"]
                   for e in REL_EDGES
                   if e["playId"] == play_id and (e["source"] == c["id"] or e["target"] == c["id"])]
        related = list(dict.fromkeys(related))[:5]
        char_list.append({
            "id": c["id"],
            "name": c["name"],
            "roleSubtype": c.get("roleSubtype", "") or c.get("roleMain", ""),
            "identity": c.get("identity", ""),
            "relationHint": "、".join(related) if related else "",
        })

    # Evidence: take 6 most interesting lines from main characters
    evidence = []
    for c in chars:
        if not c.get("isMainCharacter"):
            continue
        for i, ev in enumerate(c.get("evidence", [])[:2]):
            evidence.append({
                "id": f"{c['id']}_{i}",
                "type": "唱念",
                "speaker": c["name"],
                "text": ev,
            })
        if len(evidence) >= 6:
            break

    return {
        "play": {
            "id": p["id"],
            "title": p["title"],
            "period": p.get("period", ""),
            "genre": p.get("genre", ""),
            "authorEra": p.get("authorEra", ""),
            "sceneCount": p.get("sceneCount", 0),
            "narrativePattern": p.get("narrativePattern", ""),
            "summary": p.get("summary", ""),
        },
        "characters": char_list,
        "themes": [{"theme": t["theme"], "weight": t["weight"]} for t in themes_p[:10]],
        "narrative": [{"scene": t["scene"], "tension": t["tension"]} for t in tensions_p],
        "evidence": evidence,
    }


@app.get("/health")
def health():
    return {"ok": True, "plays": len(PLAYS), "chars": len(CHARS),
            "edges": len(REL_EDGES), "themes": len(THEMES_RECORDS)}
