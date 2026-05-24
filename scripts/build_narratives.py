"""Build narrative tension curves + pattern clusters.

Output: data/narratives.json with five keys:
  stages                  fixed 4-stage definition (启/承/转/合)
  tensionSeries           one row per (playId, scene) — tension/action/emotion
  performanceDistribution stage × form aggregate
  patternClusters         per-play 2-D embedding + assigned pattern label
  turningPoints           per-play scene with the tension peak

Side-effect:
  Writes back data/plays.json with narrativePattern filled in for each play.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"

# ===========================================================
# Stage definition
# ===========================================================
STAGES = [
    {"stage": "启", "order": 1, "description": "故事开端,人物登场,背景交代"},
    {"stage": "承", "order": 2, "description": "矛盾铺垫,情节展开"},
    {"stage": "转", "order": 3, "description": "冲突激化,剧情高潮"},
    {"stage": "合", "order": 4, "description": "结局收尾,剧情终章"},
]


def scene_to_stage(scene_num: int, total_scenes: int) -> str:
    if total_scenes <= 1:
        return "启"
    ratio = scene_num / total_scenes
    if ratio <= 0.25:
        return "启"
    if ratio <= 0.5:
        return "承"
    if ratio <= 0.75:
        return "转"
    return "合"


# ===========================================================
# Per-scene scoring
# ===========================================================
FAST_RHYTHMS = {"西皮快板", "西皮流水板", "西皮二六板", "二黄快板",
                "二黄流水板", "二黄二六板", "急急风", "扑灯蛾"}
EMOTION_ACTIONS = {"哭", "笑", "叫头", "三叫头", "哭头", "同笑", "同哭", "三笑"}
ACTION_STAGE_KEYWORDS = ["打", "战", "杀", "翻", "跌", "对刀", "刺", "射", "急上",
                          "败下", "争斗", "拚", "搏", "夺", "追", "抢", "斗"]
EMOTION_STAGE_KEYWORDS = ["哭", "笑", "怒", "惊", "惧", "悲", "怒喝", "惊呼"]


def per_scene_scores(scene: dict, lines_in_scene: list[dict]) -> dict:
    """Compute action / emotion / tension for one scene."""
    n_total = max(len(lines_in_scene), 1)

    # Fast-rhythm music cues + explicit emotion actions
    n_fast = sum(1 for ln in lines_in_scene if ln.get("actionType") in FAST_RHYTHMS)
    n_emo_act = sum(1 for ln in lines_in_scene if ln.get("actionType") in EMOTION_ACTIONS)

    # Stage-direction lines: count physical / emotional keywords
    n_stage_act = 0
    n_stage_emo = 0
    for ln in lines_in_scene:
        if ln.get("actionType") != "舞台":
            continue
        c = ln.get("content", "")
        if any(k in c for k in ACTION_STAGE_KEYWORDS):
            n_stage_act += 1
        if any(k in c for k in EMOTION_STAGE_KEYWORDS):
            n_stage_emo += 1

    action = (n_fast + n_stage_act) / n_total
    emotion = (n_emo_act + n_stage_emo) / n_total
    # tension is a soft combination — scale-free
    tension = 0.55 * action + 0.30 * emotion + 0.15 * min(len(scene.get("characters", [])) / 8, 1.0)
    return {
        "action": round(min(action, 1.0), 4),
        "emotion": round(min(emotion, 1.0), 4),
        "tension": round(min(tension, 1.0), 4),
        "numCharacters": len(scene.get("characters", [])),
        "numLines": scene.get("numLines", 0),
    }


def dominant_form(scene: dict) -> str:
    """Return the dominant performance form for the scene (唱/念/白/做)."""
    actions = scene.get("actions", {})
    buckets = {"唱": 0, "念": 0, "白": 0, "做": 0}
    for a, n in actions.items():
        if a in FAST_RHYTHMS or "唱" in a or "板" in a or "腔" in a or "调" in a or "梆子" in a:
            buckets["唱"] += n
        elif a in ("念", "同念", "引子", "点绛唇"):
            buckets["念"] += n
        elif a in ("白", "同白", "内白", "夹白", "京白", "内同白"):
            buckets["白"] += n
        elif a in EMOTION_ACTIONS or a == "舞台":
            buckets["做"] += n
    if sum(buckets.values()) == 0:
        return "白"
    return max(buckets.items(), key=lambda x: x[1])[0]


# ===========================================================
# Tension curve → fixed-length vector for clustering
# ===========================================================
N_BINS = 10  # collapse each play's scene-curve into 10 normalized buckets


def resample_curve(values: list[float], n_bins: int = N_BINS) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(n_bins)
    if len(values) == 1:
        return np.full(n_bins, values[0])
    # piecewise linear interpolation to n_bins
    xs = np.linspace(0, 1, len(values))
    target = np.linspace(0, 1, n_bins)
    return np.interp(target, xs, values)


def label_pattern_for_curve(curve: np.ndarray) -> str:
    """Hand-craft a pattern label from the resampled curve shape."""
    if curve.max() <= 1e-6:
        return "平稳型"
    norm = (curve - curve.min()) / (curve.max() - curve.min() + 1e-9)
    # Where is the peak?
    peak_idx = int(np.argmax(norm))
    peak_pos = peak_idx / (len(norm) - 1)
    early = norm[:len(norm) // 3].mean()
    mid = norm[len(norm) // 3:2 * len(norm) // 3].mean()
    late = norm[2 * len(norm) // 3:].mean()
    rng = norm.std()
    if rng < 0.15:
        return "平稳型"
    if peak_pos < 0.33:
        return "急起型"
    if peak_pos > 0.66:
        return "尾重型"
    if mid > early and mid > late:
        return "高潮型"
    if late > early:
        return "渐进型"
    return "起伏型"


# ===========================================================
# Turning points
# ===========================================================
def find_turning_points(tensions: list[float]) -> list[int]:
    """Return scene-indices of up to 3 most prominent peaks / shifts."""
    n = len(tensions)
    if n == 0:
        return []
    arr = np.array(tensions)
    candidates: list[tuple[int, float]] = []
    # Local maxima
    for i in range(1, n - 1):
        if arr[i] >= arr[i - 1] and arr[i] >= arr[i + 1] and arr[i] > arr.mean():
            candidates.append((i, arr[i]))
    # Global max
    candidates.append((int(arr.argmax()), float(arr.max())))
    # Dedup and pick top 3 by tension value
    uniq = {i: v for i, v in candidates}
    ranked = sorted(uniq.items(), key=lambda x: -x[1])[:3]
    return [i for i, _ in ranked]


# ===========================================================
# Main
# ===========================================================
def main():
    print("Loading data ...", flush=True)
    plays = json.loads((DATA / "plays.json").read_text(encoding="utf-8"))
    play_index = {p["id"]: p for p in plays}

    play_jsons: dict[str, dict] = {}
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        play_jsons[d["playId"]] = d
    print(f"  loaded {len(play_jsons)} plays", flush=True)

    tension_series: list[dict] = []
    performance_pairs: Counter = Counter()  # (stage, form) → n_scenes
    per_play_curves: dict[str, list[float]] = {}
    per_play_meta: dict[str, dict] = {}
    turning_points: list[dict] = []

    t0 = time.time()
    for i, play in enumerate(play_jsons.values(), 1):
        pid = play["playId"]
        title = play["title"]
        scenes = play.get("scenes", [])
        scenes = [s for s in scenes if s.get("sceneNum", 0) > 0]  # ignore null scene
        scenes.sort(key=lambda s: s["sceneNum"])
        if not scenes:
            per_play_curves[pid] = []
            per_play_meta[pid] = {"title": title, "genre": play_index.get(pid, {}).get("genre", "其他")}
            continue
        total = max(s["sceneNum"] for s in scenes)

        # group lines by scene
        lines_by_scene: dict[int, list[dict]] = defaultdict(list)
        for ln in play.get("lines", []):
            sn = ln.get("sceneNum", 0)
            if sn > 0:
                lines_by_scene[sn].append(ln)

        curve = []
        for sc in scenes:
            sn = sc["sceneNum"]
            scores = per_scene_scores(sc, lines_by_scene.get(sn, []))
            stage = scene_to_stage(sn, total)
            form = dominant_form(sc)
            tension_series.append({
                "playId": pid,
                "scene": f"第{sn}场",
                "sceneNum": sn,
                "stage": stage,
                "form": form,
                "tension": scores["tension"],
                "action": scores["action"],
                "emotion": scores["emotion"],
            })
            performance_pairs[(stage, form)] += 1
            curve.append(scores["tension"])

        per_play_curves[pid] = curve
        per_play_meta[pid] = {
            "title": title,
            "genre": play_index.get(pid, {}).get("genre", "其他"),
        }

        # turning points
        peaks = find_turning_points(curve)
        for rank, idx_in_curve in enumerate(peaks, 1):
            scene_num = scenes[idx_in_curve]["sceneNum"]
            scene_title = scenes[idx_in_curve].get("sceneTitle") or f"第{scene_num}场"
            tension_val = curve[idx_in_curve]
            label = "高潮" if rank == 1 else ("转折" if rank == 2 else "波动")
            turning_points.append({
                "playId": pid,
                "scene": f"第{scene_num}场",
                "sceneNum": scene_num,
                "label": label,
                "tension": tension_val,
                "description": f"{scene_title} · 张力 {tension_val:.2f}",
            })

        if i % 200 == 0 or i == len(play_jsons):
            print(f"[{i}/{len(play_jsons)}]  elapsed={time.time()-t0:.1f}s", flush=True)

    # ===========================================================
    # Pattern clustering on resampled curves
    # ===========================================================
    print("Clustering tension curves ...", flush=True)
    play_ids_with_curves = [pid for pid, c in per_play_curves.items() if c]
    matrix = np.stack([resample_curve(per_play_curves[pid]) for pid in play_ids_with_curves])
    print(f"  matrix shape: {matrix.shape}", flush=True)

    pattern_labels = [label_pattern_for_curve(matrix[i]) for i in range(matrix.shape[0])]

    # 2-D projection via PCA (no extra sklearn install — already pulled it for ML)
    from sklearn.decomposition import PCA
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(matrix)
    # Normalize coords to [0,100] for nicer display
    if coords.size:
        cmin = coords.min(axis=0)
        cmax = coords.max(axis=0)
        coords = (coords - cmin) / (cmax - cmin + 1e-9) * 100

    pattern_clusters: list[dict] = []
    for arr_i, pid in enumerate(play_ids_with_curves):
        meta = per_play_meta[pid]
        pattern_clusters.append({
            "playId": pid,
            "title": meta["title"],
            "genre": meta["genre"],
            "x": round(float(coords[arr_i, 0]), 2),
            "y": round(float(coords[arr_i, 1]), 2),
            "pattern": pattern_labels[arr_i],
        })

    # ===========================================================
    # Backfill plays.json with narrativePattern
    # ===========================================================
    pid_to_pattern = {pc["playId"]: pc["pattern"] for pc in pattern_clusters}
    for p in plays:
        p["narrativePattern"] = pid_to_pattern.get(p["id"], "平稳型")
    (DATA / "plays.json").write_text(json.dumps(plays, ensure_ascii=False, indent=2), encoding="utf-8")

    # ===========================================================
    # Final narratives.json
    # ===========================================================
    performance_distribution = [
        {"stage": s, "form": f, "value": v}
        for (s, f), v in performance_pairs.most_common()
    ]
    out = {
        "stages": STAGES,
        "tensionSeries": tension_series,
        "performanceDistribution": performance_distribution,
        "patternClusters": pattern_clusters,
        "turningPoints": turning_points,
    }
    (DATA / "narratives.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Report
    pattern_dist = Counter(pc["pattern"] for pc in pattern_clusters)
    stage_dist = Counter(tr["stage"] for tr in tension_series)
    report = [
        "=== build_narratives.py 报告 ===",
        f"plays:              {len(plays)}",
        f"plays with curve:   {len(play_ids_with_curves)}",
        f"scenes scored:      {len(tension_series)}",
        f"turning points:     {len(turning_points)}",
        "",
        "--- pattern 分布 ---",
    ]
    for k, v in pattern_dist.most_common():
        report.append(f"  {k:<8}  {v}")
    report.append("\n--- stage 分布 ---")
    for k, v in stage_dist.most_common():
        report.append(f"  {k:<4}  {v}")
    report.append("\n--- performance stage × form (top 12) ---")
    for d in performance_distribution[:12]:
        report.append(f"  {d['stage']}/{d['form']:<2}  {d['value']}")
    (DATA / "_narratives_report.txt").write_text("\n".join(report), encoding="utf-8")
    print()
    print("\n".join(report))
    print(f"\nWrote: {DATA/'narratives.json'} (and updated {DATA/'plays.json'})")


if __name__ == "__main__":
    sys.exit(main())
