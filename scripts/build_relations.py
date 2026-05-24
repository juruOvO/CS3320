"""Build the character relation network from co-occurrence in scenes.

Output: data/relations.json with five top-level keys:
  edges        per-edge records  (playId, source, target, relationType, weight, scenes)
  nodes        per-node records  (id, name, playId, roleType, size, centrality)
  adjacency    flat aggregate (source, target, value)
  metrics      per-genre network metrics  (density, avgDegree, clustering, centralization, modularity)
  relationTrend  scene × relationType counts
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"

# ===========================================================
# Heuristics for relation type
# ===========================================================
RELATION_KEYWORDS = {
    "君臣": ["君臣", "朝拜", "见驾", "见君", "万岁", "陛下"],
    "父子": ["父子", "父王", "孩儿", "我儿", "父亲", "爹爹", "爹爹"],
    "母子": ["母子", "娘亲", "母亲", "妈妈", "娘"],
    "夫妻": ["夫妻", "夫人", "贤妻", "拙夫", "妾身"],
    "兄弟": ["兄弟", "贤弟", "兄长", "大哥", "二哥"],
    "姐妹": ["姐妹", "姐姐", "妹妹"],
    "主仆": ["丫鬟", "婢女", "婢", "侍女", "仆从", "家院", "管家"],
    "师徒": ["师父", "师傅", "师徒", "徒弟", "弟子"],
    "敌对": ["杀", "斩", "刺", "战", "破", "降", "擒", "贼"],
    "朋友": ["朋友", "知己", "结义"],
}


# Pair-of-identities → likely relation
IDENTITY_PAIRS = {
    frozenset(["帝王", "武将"]): "君臣",
    frozenset(["帝王", "文臣"]): "君臣",
    frozenset(["帝王", "皇室女眷"]): "夫妻",
    frozenset(["帝王", "公主"]): "父子",  # parent-child
    frozenset(["王侯", "武将"]): "君臣",
    frozenset(["王侯", "文臣"]): "君臣",
    frozenset(["王侯", "夫人"]): "夫妻",
    frozenset(["夫人", "丫鬟"]): "主仆",
    frozenset(["公主", "丫鬟"]): "主仆",
    frozenset(["小姐", "丫鬟"]): "主仆",
    frozenset(["书生", "小姐"]): "夫妻",
    frozenset(["僧道", "妖魔"]): "敌对",
}

GENDER_ROLE_TO_RELATION = {
    ("男", "女"): "夫妻",  # weak default for cross-gender mains
}


AGE_RANK = {"少年": 0, "青年": 1, "青壮年": 2, "中年": 3, "老年": 4}


def infer_relation_type(c1: dict, c2: dict, plot: str, lines_text: str) -> str:
    """Infer a textual relationType label for an edge between two characters.

    Strategy:
        1. Identity-pair lookup (帝王×文臣→君臣 etc.)
        2. Same-surname affinity → 父子/兄弟/姐妹/夫妻 by gender & age gap
        3. Both 净 → 敌对 (花脸对立面, mild)
        4. plot-level keyword scan (LIMITED to phrases that ONLY make sense as
           explicit relation words — no battle vocabulary, no "杀")
        5. Otherwise 共现.

    The text-level scan must reference BOTH names AND a strong relation word
    in close proximity, or it gets dropped —京剧文本里"杀/战"满文章都是,
    全文级关键词匹配几乎一定会误中.
    """
    # 1. identity pair rule
    ipair = frozenset([c1.get("identity", "其他"), c2.get("identity", "其他")])
    if ipair in IDENTITY_PAIRS:
        return IDENTITY_PAIRS[ipair]

    # 2. same-surname affinity
    name1, name2 = c1["name"], c2["name"]
    if len(name1) >= 2 and len(name2) >= 2 and name1[0] == name2[0] and name1 != name2:
        g1, g2 = c1.get("gender"), c2.get("gender")
        a1 = AGE_RANK.get(c1.get("ageGroup", ""), -1)
        a2 = AGE_RANK.get(c2.get("ageGroup", ""), -1)
        age_gap = abs(a1 - a2) if (a1 >= 0 and a2 >= 0) else -1
        if g1 == g2 == "男":
            return "父子" if age_gap >= 2 else "兄弟"
        if g1 == g2 == "女":
            return "母女" if age_gap >= 2 else "姐妹"
        if {g1, g2} == {"男", "女"}:
            return "父女" if age_gap >= 2 else "夫妻"

    # 3. role-based weak rule: two 净 角 → often opposing camps
    if c1.get("roleMain") == c2.get("roleMain") == "净":
        # Only trust this if neither side has a "good guy" identity
        good_ids = {"帝王", "王侯", "武将", "文臣"}
        if c1.get("identity") not in good_ids and c2.get("identity") not in good_ids:
            return "敌对"

    # 4. (skipped) global keyword scan was too noisy — left for LLM pass later
    return "共现"


# ===========================================================
# Per-play co-occurrence graph
# ===========================================================
def build_play_graph(play: dict, char_index: dict[tuple[str, str], dict]) -> tuple[nx.Graph, list[dict]]:
    """Return (graph, edges_records) for one play."""
    pid = play["playId"]
    G = nx.Graph()
    scene_member_lists: list[tuple[int, list[str]]] = []
    for sc in play.get("scenes", []):
        # Only include characters we have in characters.json (drop composites like "众人")
        members = []
        for c in sc.get("characters", []):
            if (pid, c) in char_index:
                members.append(c)
        if len(members) >= 2:
            scene_member_lists.append((sc["sceneNum"], members))

    # Collect edges
    edge_scenes: dict[tuple[str, str], list[int]] = defaultdict(list)
    for scene_num, members in scene_member_lists:
        for a, b in combinations(sorted(set(members)), 2):
            edge_scenes[(a, b)].append(scene_num)
        for m in members:
            G.add_node(m)

    # Build text bag once
    plot_text = play.get("plot", "")
    lines_text = "".join(ln.get("content", "") for ln in play.get("lines", []))

    edge_records = []
    for (a, b), scenes in edge_scenes.items():
        w = len(scenes)
        ca = char_index[(pid, a)]
        cb = char_index[(pid, b)]
        rtype = infer_relation_type(ca, cb, plot_text, lines_text)
        G.add_edge(a, b, weight=w, relationType=rtype)
        edge_records.append({
            "playId": pid,
            "source": ca["id"],
            "target": cb["id"],
            "sourceName": ca["name"],
            "targetName": cb["name"],
            "relationType": rtype,
            "weight": w,
            "scenes": scenes,
        })

    return G, edge_records


def network_metrics(G: nx.Graph) -> dict:
    n = G.number_of_nodes()
    m = G.number_of_edges()
    if n == 0:
        return {"density": 0, "avgDegree": 0, "clustering": 0,
                "centralization": 0, "modularity": 0, "nodes": 0, "edges": 0}
    density = nx.density(G)
    avg_deg = sum(dict(G.degree()).values()) / n
    clustering = nx.average_clustering(G) if n > 1 else 0
    # Centralization (Freeman) approximation using degree
    deg = dict(G.degree())
    if n > 2:
        d_max = max(deg.values())
        centralization = sum(d_max - d for d in deg.values()) / ((n - 1) * (n - 2))
    else:
        centralization = 0
    # Modularity via greedy community
    try:
        if m > 0:
            comms = nx.community.greedy_modularity_communities(G, weight="weight")
            modularity = nx.community.modularity(G, comms, weight="weight")
        else:
            modularity = 0.0
    except Exception:
        modularity = 0.0
    return {
        "density": round(density, 4),
        "avgDegree": round(avg_deg, 4),
        "clustering": round(clustering, 4),
        "centralization": round(centralization, 4),
        "modularity": round(modularity, 4),
        "nodes": n,
        "edges": m,
    }


# ===========================================================
# Main
# ===========================================================
def main():
    print("Loading data ...", flush=True)
    chars = json.loads((DATA / "characters.json").read_text(encoding="utf-8"))
    plays = json.loads((DATA / "plays.json").read_text(encoding="utf-8"))
    play_genre = {p["id"]: p.get("genre", "其他") for p in plays}

    char_index: dict[tuple[str, str], dict] = {(c["playId"], c["name"]): c for c in chars}

    play_jsons: dict[str, dict] = {}
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        play_jsons[d["playId"]] = d
    print(f"  loaded {len(play_jsons)} plays, {len(chars)} characters", flush=True)

    all_edges: list[dict] = []
    all_nodes: list[dict] = []
    per_genre_graphs: dict[str, list[nx.Graph]] = defaultdict(list)
    relation_trend: Counter = Counter()  # (scene_bucket, relationType)
    per_play_metrics: list[dict] = []

    t0 = time.time()
    for i, play in enumerate(play_jsons.values(), 1):
        G, edges = build_play_graph(play, char_index)
        all_edges.extend(edges)

        # Per-node centrality
        if G.number_of_nodes() > 0:
            try:
                centr = nx.eigenvector_centrality_numpy(G, weight="weight") if G.number_of_edges() > 0 else {n: 0 for n in G.nodes}
            except Exception:
                centr = nx.degree_centrality(G)
        else:
            centr = {}
        for n in G.nodes():
            c = char_index.get((play["playId"], n))
            if not c:
                continue
            all_nodes.append({
                "id": c["id"],
                "name": c["name"],
                "playId": play["playId"],
                "roleType": c["roleMain"] or "未知",
                "roleSubtype": c["roleSubtype"] or "",
                "size": G.degree(n, weight="weight"),
                "centrality": round(float(centr.get(n, 0)), 4),
            })

        genre = play_genre.get(play["playId"], "其他")
        per_genre_graphs[genre].append(G)
        per_play_metrics.append({
            "playId": play["playId"],
            "genre": genre,
            **network_metrics(G),
        })

        # Relation trend: bucket scene number into normalized stage [0..1] across the play
        sc_total = max((sc["sceneNum"] for sc in play.get("scenes", [])), default=0)
        for e in edges:
            for sn in e["scenes"]:
                bucket = "起" if sc_total <= 1 else ("启" if sn / sc_total <= 0.25 else
                                                     "承" if sn / sc_total <= 0.5 else
                                                     "转" if sn / sc_total <= 0.75 else "合")
                relation_trend[(bucket, e["relationType"])] += 1

        if i % 200 == 0 or i == len(play_jsons):
            print(f"[{i}/{len(play_jsons)}]  edges={len(all_edges)}  ({time.time()-t0:.1f}s)", flush=True)

    # ===== Adjacency aggregation (relationType -> total weight) =====
    rel_total = Counter()
    for e in all_edges:
        rel_total[e["relationType"]] += e["weight"]
    adjacency = [{"source": "_global", "target": rt, "value": w} for rt, w in rel_total.most_common()]

    # ===== Per-genre metrics =====
    genre_metrics: list[dict] = []
    for genre, graphs in per_genre_graphs.items():
        if not graphs:
            continue
        # Aggregate metrics: mean over plays of that genre, weighted by node count
        ms = [network_metrics(G) for G in graphs]
        node_total = sum(m["nodes"] for m in ms) or 1
        weighted = lambda key: sum(m[key] * m["nodes"] for m in ms) / node_total
        genre_metrics.append({
            "genre": genre,
            "density":        round(weighted("density"), 4),
            "avgDegree":      round(weighted("avgDegree"), 4),
            "clustering":     round(weighted("clustering"), 4),
            "centralization": round(weighted("centralization"), 4),
            "modularity":     round(weighted("modularity"), 4),
            "plays":          len(graphs),
            "totalNodes":     sum(m["nodes"] for m in ms),
            "totalEdges":     sum(m["edges"] for m in ms),
        })
    genre_metrics.sort(key=lambda x: -x["plays"])

    # ===== relationTrend output =====
    rel_trend_out = []
    for (bucket, rtype), v in relation_trend.most_common():
        rel_trend_out.append({"scene": bucket, "relationType": rtype, "value": v})

    out = {
        "edges": all_edges,
        "nodes": all_nodes,
        "adjacency": adjacency,
        "metrics": genre_metrics,
        "relationTrend": rel_trend_out,
        "perPlayMetrics": per_play_metrics,
    }
    (DATA / "relations.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ===== Report =====
    rel_dist = Counter(e["relationType"] for e in all_edges)
    report = [
        "=== build_relations.py 报告 ===",
        f"总边数: {len(all_edges)}",
        f"总节点: {len(all_nodes)}  (从 {len(chars)} 角色中, 仅同场共现>=1 才入图)",
        "",
        "--- relationType 分布 ---",
    ]
    for k, v in rel_dist.most_common():
        report.append(f"  {k:<8}  {v}")
    report.append("\n--- per-genre 网络指标 ---")
    report.append(f"  {'genre':<10} {'plays':>6} {'density':>8} {'avgDeg':>8} {'cluster':>8} {'centr':>8} {'mod':>8}")
    for m in genre_metrics:
        report.append(f"  {m['genre']:<10} {m['plays']:>6} {m['density']:>8.4f} {m['avgDegree']:>8.4f} {m['clustering']:>8.4f} {m['centralization']:>8.4f} {m['modularity']:>8.4f}")
    (DATA / "_relations_report.txt").write_text("\n".join(report), encoding="utf-8")
    print()
    print("\n".join(report))
    print(f"\nWrote: {DATA/'relations.json'}")


if __name__ == "__main__":
    sys.exit(main())
