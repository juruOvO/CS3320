"""Predict roleMain for unlabeled characters via supervised learning.

Pipeline:
1. Build a feature row for every character (labeled + unlabeled).
2. Train a RandomForest on the labeled subset (生/旦/净/丑 — drop "杂" and "未知").
3. Hold-out validation report.
4. Predict roleMain for unlabeled rows; predicted probability becomes confidence.
5. Backfill roleSubtype with a small rule table (age/action keywords).
6. Overwrite data/characters.json.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = ROOT / "京剧剧本_json"

LABELS = ["生", "旦", "净", "丑"]


# ===========================================================
# Feature extraction
# ===========================================================
def aggregate_action_dist(lines: list[dict]) -> Counter:
    return Counter(ln.get("actionType", "") for ln in lines)


def is_sing(action_type: str) -> bool:
    return any(s in action_type for s in ("唱", "板", "腔", "调", "梆子", "导板", "二六", "原板",
                                          "慢板", "快板", "流水板", "散板", "摇板", "平板", "吹腔"))


def is_fast(action_type: str) -> bool:
    return any(s in action_type for s in ("快板", "流水板", "二六板", "急急风"))


def is_slow(action_type: str) -> bool:
    return any(s in action_type for s in ("慢板", "原板", "平板"))


def is_emotional(action_type: str) -> bool:
    return action_type in ("哭", "笑", "叫头", "三叫头", "哭头", "同笑", "同哭", "同笑", "三笑")


NAME_FEAT_TOKENS = {
    "name_娘": ["娘"],
    "name_姑": ["姑"],
    "name_妃": ["妃", "贵妃"],
    "name_夫人": ["夫人"],
    "name_氏": ["氏"],
    "name_姐妹": ["姐", "妹"],
    "name_皇王": ["皇", "帝", "天子", "万岁"],
    "name_将": ["将军", "元帅", "都督", "总兵"],
    "name_丞相": ["丞相", "宰相", "尚书"],
    "name_老": ["老"],
    "name_小": ["小"],
    "name_童儿": ["童", "儿"],
    "name_军卒兵": ["军", "兵", "卒"],
    "name_鬼妖": ["鬼", "妖", "怪", "魔"],
    "name_僧道": ["僧", "和尚", "道士", "尼姑", "道人"],
    "name_店": ["店家", "酒保", "店小二"],
    "name_丫鬟": ["丫鬟", "婢", "侍女"],
    "name_书生": ["书生", "公子", "举人", "秀才"],
    "name_公主小姐": ["公主", "小姐", "郡主"],
    "name_龙王神": ["龙王", "玉帝", "神", "仙", "罗汉", "菩萨"],
}


def name_features(name: str) -> dict[str, int]:
    out = {}
    for key, tokens in NAME_FEAT_TOKENS.items():
        out[key] = int(any(t in name for t in tokens))
    out["name_len"] = len(name)
    return out


def co_role_dist(char_name: str, play_chars: list[dict], play_scenes: list[dict],
                 known_role_map: dict[str, str]) -> dict[str, float]:
    """Distribution of labeled co-actors' roleMain that appear in the same scenes."""
    own_scenes: set[int] = set()
    for sc in play_scenes:
        if char_name in sc.get("characters", []):
            own_scenes.add(sc["sceneNum"])
    co_names: set[str] = set()
    for sc in play_scenes:
        if sc["sceneNum"] in own_scenes:
            for c in sc.get("characters", []):
                if c != char_name:
                    co_names.add(c)
    co_roles = Counter(known_role_map[c] for c in co_names if c in known_role_map)
    total = sum(co_roles.values())
    if total == 0:
        return {f"co_p_{lab}": 0.0 for lab in LABELS} | {"co_n": 0}
    out = {f"co_p_{lab}": co_roles.get(lab, 0) / total for lab in LABELS}
    out["co_n"] = total
    return out


def featurize_one(char: dict, play_json: dict, known_role_map: dict[str, str]) -> dict:
    name = char["name"]
    lines = play_json.get("lines", [])
    own_lines = [ln for ln in lines if ln.get("character") == name]
    n = len(own_lines)
    denom = max(n, 1)

    act = aggregate_action_dist(own_lines)
    n_sing = sum(v for a, v in act.items() if is_sing(a))
    n_fast = sum(v for a, v in act.items() if is_fast(a))
    n_slow = sum(v for a, v in act.items() if is_slow(a))
    n_emo = sum(v for a, v in act.items() if is_emotional(a))

    feat = {
        "n_lines": n,
        "p_白": act.get("白", 0) / denom,
        "p_同白": act.get("同白", 0) / denom,
        "p_唱": n_sing / denom,
        "p_念": act.get("念", 0) / denom,
        "p_引子": act.get("引子", 0) / denom,
        "p_快板": n_fast / denom,
        "p_慢板": n_slow / denom,
        "p_情感": n_emo / denom,
        "p_西皮": sum(v for a, v in act.items() if "西皮" in a) / denom,
        "p_二黄": sum(v for a, v in act.items() if "二黄" in a) / denom,
        "p_笑": act.get("笑", 0) / denom,
        "p_哭": act.get("哭", 0) / denom,
        "p_叫头": (act.get("叫头", 0) + act.get("三叫头", 0)) / denom,
        "action_score": char.get("actionScore", 0),
        "emotion_score": char.get("emotionScore", 0),
        "appearance_count": char.get("appearanceCount", 0),
        "is_main": int(char.get("isMainCharacter", False)),
    }
    feat.update(name_features(name))

    # Heuristic attrs
    feat["g_male"] = int(char.get("gender") == "男")
    feat["g_female"] = int(char.get("gender") == "女")
    feat["age_老"] = int(char.get("ageGroup") == "老年")
    feat["age_少"] = int(char.get("ageGroup") == "少年")
    feat["age_青"] = int(char.get("ageGroup") in ("青年", "青壮年"))
    feat["age_中"] = int(char.get("ageGroup") == "中年")

    # Identity one-hot (compact list)
    ident = char.get("identity", "其他")
    for key in ("帝王", "王侯", "武将", "文臣", "夫人", "丫鬟", "书生", "公主",
                "僧道", "士兵", "市井", "店家", "神仙", "妖魔", "母亲", "媒婆"):
        feat[f"id_{key}"] = int(ident == key)

    # Co-actor distribution
    feat.update(co_role_dist(name, [], play_json.get("scenes", []), known_role_map))

    return feat


# ===========================================================
# Sub-type rules (used after roleMain prediction)
# ===========================================================
def assign_subtype(role_main: str, feat: dict, name: str) -> str:
    if role_main == "生":
        if feat.get("age_老") or feat.get("name_老"):
            return "老生"
        if feat.get("age_少") or feat.get("name_童儿"):
            return "娃娃生"
        if feat.get("action_score", 0) > 0.18:
            return "武生"
        if feat.get("age_青") or feat.get("name_小") or feat.get("name_书生"):
            return "小生"
        return "生"
    if role_main == "旦":
        if feat.get("age_老") or feat.get("name_老"):
            return "老旦"
        if feat.get("action_score", 0) > 0.18:
            return "武旦"
        if feat.get("name_丫鬟") or feat.get("name_姐妹") or feat.get("name_小"):
            return "花旦"
        if feat.get("name_娘") or feat.get("name_媒婆"):
            return "彩旦"
        if feat.get("name_夫人") or feat.get("name_氏"):
            return "青衣"
        return "旦"
    if role_main == "净":
        if feat.get("action_score", 0) > 0.18:
            return "武净"
        if feat.get("name_鬼妖"):
            return "净"
        return "净"
    if role_main == "丑":
        if feat.get("action_score", 0) > 0.18:
            return "武丑"
        return "文丑"
    return role_main


# ===========================================================
# Main
# ===========================================================
def main():
    print("Loading characters.json + plays...", flush=True)
    chars = json.loads((DATA / "characters.json").read_text(encoding="utf-8"))
    plays = json.loads((DATA / "plays.json").read_text(encoding="utf-8"))

    play_jsons: dict[str, dict] = {}
    for p in SRC.rglob("*.json"):
        if p.name.startswith("_"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        play_jsons[d["playId"]] = d
    print(f"  loaded {len(play_jsons)} plays, {len(chars)} characters", flush=True)

    # Build per-play known role map (for co-occurrence features)
    play_role_map: dict[str, dict[str, str]] = {}
    for c in chars:
        if c["roleMain"] in LABELS:
            play_role_map.setdefault(c["playId"], {})[c["name"]] = c["roleMain"]

    # ===========================================================
    # Feature extraction
    # ===========================================================
    print("Extracting features...", flush=True)
    t0 = time.time()
    rows = []
    for i, c in enumerate(chars):
        pid = c["playId"]
        play = play_jsons.get(pid, {})
        known = play_role_map.get(pid, {})
        # When featurizing labeled rows, exclude their own label from co-actor map
        if c["name"] in known:
            local_known = {k: v for k, v in known.items() if k != c["name"]}
        else:
            local_known = known
        feat = featurize_one(c, play, local_known)
        feat["_id"] = c["id"]
        feat["_label"] = c["roleMain"] if c["roleMain"] in LABELS else ""
        rows.append(feat)
        if (i + 1) % 2000 == 0:
            print(f"  {i+1}/{len(chars)}  elapsed={time.time()-t0:.1f}s", flush=True)
    df = pd.DataFrame(rows)
    print(f"  feature matrix: {df.shape}  ({time.time()-t0:.1f}s)", flush=True)

    # Drop features that are *derived from* roleMain in build_features.py,
    # otherwise they leak the label and the model collapses on unlabeled rows
    # (gender/age/some identity buckets are partly back-mapped from the
    # subtype, so they are perfectly aligned with labels in the training set
    # but ~empty for unlabeled minor characters).
    LEAKY_FEATURES = {
        "g_male", "g_female",
        "age_老", "age_少", "age_青", "age_中",
        "id_市井",   # 丑 fallback in infer_identity
        "id_母亲",   # 老旦 fallback
        "id_媒婆",   # 彩旦 fallback
    }
    feature_cols = [c for c in df.columns if not c.startswith("_") and c not in LEAKY_FEATURES]
    print(f"  using {len(feature_cols)} features ({len(LEAKY_FEATURES)} dropped as leaky)", flush=True)
    X_all = df[feature_cols].astype(float).values

    # ===========================================================
    # Train on labeled subset
    # ===========================================================
    labeled_mask = df["_label"].isin(LABELS).values
    X_lab = X_all[labeled_mask]
    y_lab = df.loc[labeled_mask, "_label"].values
    print(f"\nLabeled rows: {len(y_lab)}", flush=True)
    print(f"Label dist: {dict(Counter(y_lab))}", flush=True)

    X_train, X_val, y_train, y_val = train_test_split(
        X_lab, y_lab, test_size=0.2, random_state=42, stratify=y_lab
    )

    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    print("Training RandomForest...", flush=True)
    clf.fit(X_train, y_train)

    val_pred = clf.predict(X_val)
    val_acc = (val_pred == y_val).mean()
    print(f"\nValidation accuracy: {val_acc:.4f}", flush=True)
    print("\nClassification report (validation):", flush=True)
    print(classification_report(y_val, val_pred, labels=LABELS, zero_division=0), flush=True)
    print("Confusion matrix (rows=true, cols=pred; order: 生/旦/净/丑):", flush=True)
    print(confusion_matrix(y_val, val_pred, labels=LABELS), flush=True)

    # Feature importance
    importances = sorted(
        zip(feature_cols, clf.feature_importances_), key=lambda x: -x[1]
    )
    print("\nTop 15 feature importances:", flush=True)
    for n, imp in importances[:15]:
        print(f"  {n:<22} {imp:.4f}", flush=True)

    # ===========================================================
    # Refit on full labeled set, then predict on unlabeled
    # ===========================================================
    print("\nRefitting on full labeled set...", flush=True)
    clf.fit(X_lab, y_lab)

    unlabeled_mask = ~labeled_mask
    n_unlab = unlabeled_mask.sum()
    print(f"Unlabeled rows to predict: {n_unlab}", flush=True)

    proba = clf.predict_proba(X_all[unlabeled_mask])
    pred = clf.classes_[proba.argmax(axis=1)]
    pred_conf = proba.max(axis=1)

    # Write back
    label_idx_in_chars = np.where(unlabeled_mask)[0]
    for arr_pos, idx in enumerate(label_idx_in_chars):
        c = chars[idx]
        feat_row = df.iloc[idx].to_dict()
        c["roleMain"] = pred[arr_pos]
        c["confidence"] = round(float(pred_conf[arr_pos]), 4)
        c["roleSubtype"] = assign_subtype(pred[arr_pos], feat_row, c["name"])
        c["roleClean"] = c["roleSubtype"]  # display-friendly cleaned label

    # Also assign more specific subtypes for some labeled characters that have only 主行当 (no sub)
    for idx, c in enumerate(chars):
        if not labeled_mask[idx]:
            continue
        if c["roleSubtype"] in ("生", "旦", "净", "丑") and c["roleMain"] in LABELS:
            feat_row = df.iloc[idx].to_dict()
            c["roleSubtype"] = assign_subtype(c["roleMain"], feat_row, c["name"])

    # ===========================================================
    # Backfill gender / ageGroup using the now-known 行当.
    # These were derived in build_features.py BEFORE minor characters had a
    # 行当 (it's inferred here), so ~9000 came out "未知". Now re-derive them
    # with the same heuristics — only filling values still "未知", never
    # overriding one that was already determined.
    # ===========================================================
    from build_features import infer_gender, infer_age  # same heuristic table

    gender_filled = 0
    age_filled = 0
    for c in chars:
        if c.get("gender") == "未知":
            g = infer_gender(c["name"], c.get("roleMain", ""), c.get("roleSubtype", ""))
            if g != "未知":
                c["gender"] = g
                gender_filled += 1
        if c.get("ageGroup") == "未知":
            a = infer_age(c["name"], c.get("roleMain", ""), c.get("roleSubtype", ""))
            if a != "未知":
                c["ageGroup"] = a
                age_filled += 1
    print(f"Backfilled gender for {gender_filled}, ageGroup for {age_filled} characters "
          f"using inferred 行当", flush=True)

    # ===========================================================
    # Persist + report
    # ===========================================================
    (DATA / "characters.json").write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    final_role_main = Counter(c["roleMain"] for c in chars)
    final_role_sub = Counter(c["roleSubtype"] for c in chars)
    conf_buckets = Counter()
    for c in chars:
        if c["confidence"] >= 0.99:
            conf_buckets[">=0.99"] += 1
        elif c["confidence"] >= 0.7:
            conf_buckets["0.7-0.99"] += 1
        elif c["confidence"] >= 0.5:
            conf_buckets["0.5-0.7"] += 1
        else:
            conf_buckets["<0.5"] += 1

    report = [
        "=== infer_roles.py 报告 ===",
        f"Total characters:     {len(chars)}",
        f"Labeled (train pool): {labeled_mask.sum()}",
        f"Unlabeled (predicted):{n_unlab}",
        f"Validation accuracy:  {val_acc:.4f}",
        "",
        "--- Final roleMain distribution ---",
    ]
    for k, v in final_role_main.most_common():
        report.append(f"  {(k or '<empty>'):<8}  {v}")
    report.append("\n--- Top roleSubtype ---")
    for k, v in final_role_sub.most_common(20):
        report.append(f"  {(k or '<empty>'):<10}  {v}")
    report.append("\n--- confidence buckets ---")
    for k, v in conf_buckets.most_common():
        report.append(f"  {k:<10}  {v}")
    report.append("\n--- Top 15 feature importances ---")
    for n, imp in importances[:15]:
        report.append(f"  {n:<22} {imp:.4f}")
    (DATA / "_infer_roles_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[-10:]))
    print(f"\nWrote: {DATA/'characters.json'}")


if __name__ == "__main__":
    sys.exit(main())
