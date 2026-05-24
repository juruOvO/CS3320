"""Derive `data/plays.json` and `data/characters.json` from `京剧剧本_json/`.

Rule-based / heuristic layer (LLM augmentation comes later):

plays.json
    id, title, altTitles, period, genre, summary, sceneCount, authorEra,
    narrativePattern (placeholder), collectionCode, collectionName,
    sourceCollection, yearsFound, numPages, numLines, numMainCharacters

characters.json
    id (= playId_name), playId, name, gender, ageGroup, identity,
    personalityTags ([] placeholder for LLM later),
    roleTypeRaw, roleMain, roleSubtype, confidence,
    actionScore, emotionScore, appearanceCount,
    evidence (3 representative lines),
    isMainCharacter (bool)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "京剧剧本_json"
OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)

# ===========================================================
# Period mapping
# ===========================================================
def period_of(years_found: list[int], collection_code: str) -> str:
    if years_found:
        y = min(years_found)
        if y < 1912:
            return "清末"
        if y < 1949:
            return "民国"
        if y < 1966:
            return "建国初期"
        if y < 2000:
            return "新时期"
        return "新世纪"
    # Heuristic by collection
    if collection_code in ("01000000", "02000000", "13000000"):
        return "传统(清末民初)"
    if collection_code in ("03000000", "04000000", "05000000", "07000000",
                            "08000000", "10000000", "11000000", "14000000", "15000000"):
        return "传统(整理本)"
    if collection_code in ("70001000", "70002000", "70003000", "70004000", "70005000", "70006000",
                            "70201000", "70202000", "70203000", "70204000",
                            "70401000", "70402000", "70601000"):
        return "流派传承"
    if collection_code.startswith("708"):
        return "建国初期"
    if collection_code.startswith("709"):
        return "昆曲传承"
    if collection_code == "80000000":
        return "录音整理"
    if collection_code in ("90000000", "94000000"):
        return "现代藏本"
    return "未知"


def author_era_of(collection_code: str) -> str:
    if collection_code in ("01000000", "02000000", "13000000"):
        return "清末民初"
    if collection_code in ("03000000", "04000000", "05000000", "07000000",
                            "08000000", "10000000", "11000000", "14000000", "15000000"):
        return "传统"
    if collection_code in ("70001000", "70002000", "70003000", "70004000", "70005000", "70006000"):
        return "老生流派"
    if collection_code in ("70201000", "70202000", "70203000", "70204000"):
        return "旦行流派"
    if collection_code in ("70401000", "70402000"):
        return "净行流派"
    if collection_code == "70601000":
        return "丑行流派"
    if collection_code.startswith("708"):
        return "现代编剧"
    if collection_code.startswith("709"):
        return "昆曲"
    if collection_code == "80000000":
        return "录音整理"
    if collection_code in ("90000000", "94000000"):
        return "院团演出"
    return "未知"


# ===========================================================
# Genre classification (keyword rules)
# ===========================================================
GENRE_KEYWORDS: dict[str, list[str]] = {
    "历史戏": ["帝", "皇", "天子", "汉", "唐", "宋", "元", "明", "清", "三国", "春秋",
                "战国", "楚", "秦", "丞相", "宰相", "将军", "元帅", "诸侯", "朝廷",
                "出征", "兴兵", "破阵", "天下", "御", "诏", "金兀术", "辽国", "番邦", "城池"],
    "家庭戏": ["夫妻", "夫人", "妻", "妾", "姑", "嫂", "婆", "媳", "婚", "嫁", "聘", "公婆",
                "翁", "媒", "亲家", "兄嫂", "夫主", "贤妻"],
    "公案戏": ["杀", "审", "告", "冤", "包公", "判", "案", "贼", "盗", "刑", "斩",
                "御史", "知县", "府尹", "包拯", "查", "冤情", "鸣冤", "县衙"],
    "神怪戏": ["仙", "神", "妖", "鬼", "天宫", "龙宫", "罗汉", "菩萨", "玉皇", "孙悟空",
                "猴", "魔", "雷神", "雪神", "天兵", "天将", "凡间", "下凡"],
    "爱情戏": ["情", "恋", "相思", "钟情", "私订", "姻缘", "才子", "佳人", "西厢", "私会",
                "私奔", "幽会", "情书"],
    "伦理戏": ["孝", "忠", "义", "节", "烈", "守节", "殉", "感天动地", "贞节", "孝子",
                "忠臣", "节妇", "孝行"],
    "公侠戏": ["侠", "义士", "镖", "绿林", "草莽", "山寨"],
}

GENRE_PRIORITY = ["历史戏", "公案戏", "公侠戏", "神怪戏", "伦理戏", "爱情戏", "家庭戏"]


def classify_genre(text: str) -> str:
    if not text:
        return "其他"
    scores: dict[str, int] = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        scores[genre] = sum(text.count(k) for k in keywords)
    max_score = max(scores.values()) if scores else 0
    if max_score == 0:
        return "其他"
    # Apply priority among ties
    for genre in GENRE_PRIORITY:
        if scores[genre] == max_score:
            return genre
    return "其他"


# ===========================================================
# 行当 normalization
# ===========================================================
SPLIT_RE = re.compile(r"[、，,]")

ROLE_MAP: dict[str, tuple[str, str]] = {
    # 生
    "老生": ("生", "老生"), "正生": ("生", "老生"), "须生": ("生", "老生"),
    "末": ("生", "末"), "外": ("生", "外"),
    "小生": ("生", "小生"), "武小生": ("生", "武小生"),
    "巾生": ("生", "巾生"), "冠生": ("生", "冠生"),
    "雉尾生": ("生", "雉尾生"), "穷生": ("生", "穷生"),
    "武生": ("生", "武生"), "武老生": ("生", "武老生"),
    "红生": ("生", "红生"),
    "娃娃生": ("生", "娃娃生"), "童": ("生", "娃娃生"),
    "副生": ("生", "副生"), "生": ("生", "生"),
    # 旦
    "旦": ("旦", "旦"),
    "正旦": ("旦", "青衣"), "青衣": ("旦", "青衣"),
    "花旦": ("旦", "花旦"),
    "武旦": ("旦", "武旦"), "刀马旦": ("旦", "刀马旦"),
    "老旦": ("旦", "老旦"),
    "彩旦": ("旦", "彩旦"), "丑旦": ("旦", "彩旦"), "搽旦": ("旦", "彩旦"),
    "贴旦": ("旦", "贴旦"), "小旦": ("旦", "小旦"),
    "闺门旦": ("旦", "闺门旦"), "五旦": ("旦", "闺门旦"),
    "六旦": ("旦", "贴旦"), "占旦": ("旦", "占旦"),
    "作旦": ("旦", "作旦"),
    # 净
    "净": ("净", "净"), "正净": ("净", "正净"), "副净": ("净", "副净"),
    "武净": ("净", "武净"), "武花脸": ("净", "武花脸"),
    "铜锤花脸": ("净", "铜锤"), "铜锤": ("净", "铜锤"),
    "架子花脸": ("净", "架子"), "架子": ("净", "架子"),
    "白面": ("净", "白面"), "红净": ("净", "红净"),
    # 丑
    "丑": ("丑", "丑"), "文丑": ("丑", "文丑"), "武丑": ("丑", "武丑"),
    "小丑": ("丑", "文丑"), "彩丑": ("丑", "彩丑"), "付": ("丑", "付"),
    # 杂
    "杂": ("杂", "杂"),
}


def normalize_role(raw: str) -> tuple[str, str, str]:
    """Return (clean_label, role_main, role_subtype). Empty if no label."""
    if not raw or not raw.strip():
        return "", "", ""
    lead = SPLIT_RE.split(raw.strip(), 1)[0].strip()
    lead = re.sub(r"[（(].*?[)）]", "", lead).strip()
    if lead in ROLE_MAP:
        m, s = ROLE_MAP[lead]
        return lead, m, s
    for k in sorted(ROLE_MAP.keys(), key=lambda x: -len(x)):
        if lead.startswith(k):
            m, s = ROLE_MAP[k]
            return lead, m, s
    return lead, "未知", lead


# ===========================================================
# Character attribute heuristics (gender / ageGroup / identity)
# ===========================================================
FEMALE_NAME_TOKENS = ["娘", "姑", "夫人", "媳", "嫂", "婆", "妃", "公主", "皇后",
                      "姨", "姬", "氏", "女", "丫鬟", "婢", "尼", "贵人"]
MALE_NAME_TOKENS = ["公子", "和尚", "僧", "道士", "道人", "先生", "员外", "老爷"]


def infer_gender(name: str, role_main: str, role_subtype: str) -> str:
    if role_main == "旦":
        return "女"
    if role_subtype in ("彩旦", "贴旦", "占旦", "作旦", "闺门旦"):
        return "女"
    for tok in FEMALE_NAME_TOKENS:
        if tok in name:
            return "女"
    for tok in MALE_NAME_TOKENS:
        if tok in name:
            return "男"
    if role_main in ("生", "净", "丑"):
        return "男"
    return "未知"


def infer_age(name: str, role_main: str, role_subtype: str) -> str:
    if role_subtype in ("老生", "老旦", "末", "外"):
        return "老年"
    if role_subtype in ("娃娃生",) or any(k in name for k in ("儿", "童", "童子", "小")):
        return "少年"
    if role_subtype in ("小生", "小旦", "花旦", "巾生", "贴旦", "闺门旦", "六旦"):
        return "青年"
    if role_subtype in ("武生", "武小生", "武丑", "武旦", "刀马旦"):
        return "青壮年"
    if role_subtype in ("青衣", "正旦", "铜锤", "架子", "净", "丑", "武净", "武花脸"):
        return "中年"
    if role_main in ("生", "旦", "净", "丑"):
        return "中年"
    return "未知"


IDENTITY_RULES = [
    (["皇上", "皇帝", "万岁", "陛下", "天子"], "帝王"),
    (["太子"], "太子"),
    (["皇后", "贵妃", "妃"], "皇室女眷"),
    (["公主", "郡主"], "公主"),
    (["王爷", "王"], "王侯"),
    (["元帅", "将军", "总兵", "都督", "提督"], "武将"),
    (["丞相", "宰相", "尚书", "御史", "大夫"], "文臣"),
    (["知县", "县令", "县官", "知府", "府尹"], "地方官"),
    (["夫人"], "夫人"),
    (["小姐"], "小姐"),
    (["丫鬟", "婢女", "婢", "侍女"], "丫鬟"),
    (["书生", "公子", "举人", "秀才"], "书生"),
    (["和尚", "僧", "尼", "道士", "道人", "道姑"], "僧道"),
    (["店家", "店主", "店小二", "酒保", "伙计"], "店家"),
    (["军", "兵", "卒"], "士兵"),
    (["渔翁", "渔夫", "樵夫", "猎户", "农夫"], "平民"),
    (["太监"], "太监"),
    (["龙王", "玉帝", "天帝", "神", "仙"], "神仙"),
    (["妖", "魔", "鬼"], "妖魔"),
]


def infer_identity(name: str, role_main: str, role_subtype: str) -> str:
    for tokens, label in IDENTITY_RULES:
        for tok in tokens:
            if tok in name:
                return label
    # By role subtype fallback
    if role_subtype in ("老旦",):
        return "母亲"
    if role_subtype in ("彩旦",):
        return "媒婆"
    if role_subtype == "丑":
        return "市井"
    return "其他"


# ===========================================================
# Per-character scores (action / emotion) and evidence
# ===========================================================
EMOTION_ACTIONS = {"哭", "笑", "叫头", "三叫头", "哭头", "同笑", "同哭"}
# 节奏紧 / 武戏色彩重的板式 (heuristic stand-in for actionScore)
ACTION_ACTIONS = {
    "西皮快板", "西皮流水板", "西皮二六板", "西皮散板", "西皮摇板",
    "二黄快板", "二黄流水板", "二黄二六板", "二黄散板", "二黄摇板",
    "急急风", "扑灯蛾",
}
# Words in stage directions that imply physical action
ACTION_KEYWORDS_IN_STAGE = [
    "打", "战", "杀", "翻", "跌", "对刀", "抢背", "亮相", "起霸",
    "上马", "下马", "急上", "败下", "拥下", "夺", "刺", "射", "追",
]
EMOTION_KEYWORDS_IN_STAGE = ["哭", "笑", "怒", "惊", "惧", "悲"]


def compute_char_scores(name: str, lines: list[dict]) -> dict:
    """Return action / emotion / appearance for a single character."""
    own_lines = [ln for ln in lines if ln.get("character") == name]
    n = len(own_lines)
    if n == 0:
        return {"actionScore": 0.0, "emotionScore": 0.0, "appearanceCount": 0}

    n_emo = sum(1 for ln in own_lines if ln.get("actionType") in EMOTION_ACTIONS)
    n_act = sum(1 for ln in own_lines if ln.get("actionType") in ACTION_ACTIONS)

    # Stage directions referring to the character contribute too
    stage_lines = [ln for ln in lines if ln.get("actionType") == "舞台" and name in ln.get("content", "")]
    for ln in stage_lines:
        content = ln.get("content", "")
        if any(k in content for k in ACTION_KEYWORDS_IN_STAGE):
            n_act += 1
        if any(k in content for k in EMOTION_KEYWORDS_IN_STAGE):
            n_emo += 1

    denom = n + len(stage_lines)
    return {
        "actionScore": round(n_act / denom, 4) if denom else 0.0,
        "emotionScore": round(n_emo / denom, 4) if denom else 0.0,
        "appearanceCount": n,
    }


def pick_evidence(name: str, lines: list[dict], k: int = 3) -> list[str]:
    """Pick up to k representative lines for the character (long, non-stage)."""
    own_lines = [
        ln for ln in lines
        if ln.get("character") == name and ln.get("actionType") not in ("舞台", "")
    ]
    if not own_lines:
        return []
    # Prefer long content with rich types
    PREFERRED = {"唱", "念", "引子", "白", "西皮原板", "二黄原板", "西皮慢板", "二黄慢板"}
    own_lines.sort(
        key=lambda ln: (
            ln.get("actionType") in PREFERRED,
            len(ln.get("content", "")),
        ),
        reverse=True,
    )
    out = []
    seen_content = set()
    for ln in own_lines:
        content = ln.get("content", "").strip()
        if not content or content in seen_content:
            continue
        action = ln.get("actionType", "")
        scene = ln.get("sceneNum", 0)
        snippet = f"【第{scene}场·{action}】{content[:80]}{'…' if len(content) > 80 else ''}"
        out.append(snippet)
        seen_content.add(content)
        if len(out) >= k:
            break
    return out


# ===========================================================
# Main
# ===========================================================
def iter_play_files():
    for p in sorted(SRC.rglob("*.json")):
        if p.name.startswith("_"):
            continue
        yield p


def main():
    play_files = list(iter_play_files())
    print(f"Found {len(play_files)} play files", flush=True)

    plays_out: list[dict] = []
    chars_out: list[dict] = []

    t0 = time.time()
    for i, p in enumerate(play_files, 1):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! failed to read {p}: {e}", flush=True)
            continue
        if data.get("parseError") == "empty_pdf":
            # Skip empty PDFs but record minimal stub
            plays_out.append({
                "id": data["playId"],
                "title": data["title"],
                "altTitles": [],
                "period": "未知",
                "genre": "其他",
                "summary": "",
                "sceneCount": 0,
                "authorEra": author_era_of(data.get("collectionCode", "")),
                "narrativePattern": "",
                "collectionCode": data.get("collectionCode", ""),
                "collectionName": data.get("collectionName", ""),
                "sourceCollection": "",
                "yearsFound": [],
                "numPages": 0,
                "numLines": 0,
                "numMainCharacters": 0,
                "parseError": "empty_pdf",
            })
            continue

        pid = data["playId"]
        title = data["title"]
        years = data.get("yearsFound", [])
        coll_code = data.get("collectionCode", "")
        plot = data.get("plot", "")
        notes = data.get("notes", "")
        genre_text = f"{title}\n{plot}\n{notes}"

        play_record = {
            "id": pid,
            "title": title,
            "altTitles": data.get("altTitles", []),
            "period": period_of(years, coll_code),
            "genre": classify_genre(genre_text),
            "summary": plot[:280] if plot else "",
            "sceneCount": data.get("stats", {}).get("numScenes", 0),
            "authorEra": author_era_of(coll_code),
            "narrativePattern": "",  # filled by build_narratives.py
            "collectionCode": coll_code,
            "collectionName": data.get("collectionName", ""),
            "sourceCollection": data.get("sourceCollection", ""),
            "yearsFound": years,
            "numPages": data.get("numPages", 0),
            "numLines": data.get("stats", {}).get("numLines", 0),
            "numMainCharacters": data.get("stats", {}).get("numMainCharacters", 0),
        }
        plays_out.append(play_record)

        # ----- characters -----
        lines = data.get("lines", [])
        main_chars = data.get("mainCharacters", [])
        main_names = {c["name"] for c in main_chars}

        # All characters appearing in lines (incl. minor ones not in main list)
        all_names_in_lines: set[str] = set()
        for ln in lines:
            c = ln.get("character", "")
            if c and ln.get("actionType") != "舞台":
                # Skip multi-character composites like "众人" or "甲、乙、丙"
                if "、" in c or c in ("众人", "众"):
                    continue
                all_names_in_lines.add(c)

        # 1) Main characters from header
        for mc in main_chars:
            name = mc["name"]
            raw = mc.get("roleTypeRaw", "")
            clean, main_t, sub_t = normalize_role(raw)
            scores = compute_char_scores(name, lines)
            confidence = 1.0 if clean and main_t != "未知" else (0.5 if clean else 0.0)
            chars_out.append({
                "id": f"{pid}_{name}",
                "playId": pid,
                "name": name,
                "gender": infer_gender(name, main_t, sub_t),
                "ageGroup": infer_age(name, main_t, sub_t),
                "identity": infer_identity(name, main_t, sub_t),
                "personalityTags": [],  # LLM placeholder
                "roleTypeRaw": raw,
                "roleClean": clean,
                "roleMain": main_t,
                "roleSubtype": sub_t,
                "confidence": confidence,
                "actionScore": scores["actionScore"],
                "emotionScore": scores["emotionScore"],
                "appearanceCount": scores["appearanceCount"],
                "evidence": pick_evidence(name, lines),
                "isMainCharacter": True,
            })

        # 2) Minor characters: in lines but not in main list
        for name in sorted(all_names_in_lines - main_names):
            scores = compute_char_scores(name, lines)
            if scores["appearanceCount"] < 2:
                # Skip extremely rare names (often noise / numbered minor extras)
                continue
            chars_out.append({
                "id": f"{pid}_{name}",
                "playId": pid,
                "name": name,
                "gender": infer_gender(name, "", ""),
                "ageGroup": infer_age(name, "", ""),
                "identity": infer_identity(name, "", ""),
                "personalityTags": [],
                "roleTypeRaw": "",
                "roleClean": "",
                "roleMain": "",        # will be filled by infer_roles.py
                "roleSubtype": "",
                "confidence": 0.0,     # placeholder for inference
                "actionScore": scores["actionScore"],
                "emotionScore": scores["emotionScore"],
                "appearanceCount": scores["appearanceCount"],
                "evidence": pick_evidence(name, lines),
                "isMainCharacter": False,
            })

        if i % 200 == 0 or i == len(play_files):
            print(f"[{i}/{len(play_files)}] plays={len(plays_out)} chars={len(chars_out)} elapsed={time.time()-t0:.1f}s", flush=True)

    # Write
    (OUT / "plays.json").write_text(
        json.dumps(plays_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "characters.json").write_text(
        json.dumps(chars_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- report ---
    from collections import Counter
    period_dist = Counter(p["period"] for p in plays_out)
    genre_dist = Counter(p["genre"] for p in plays_out)
    role_main_dist = Counter(c["roleMain"] for c in chars_out)
    role_sub_dist = Counter(c["roleSubtype"] for c in chars_out)
    gender_dist = Counter(c["gender"] for c in chars_out)
    age_dist = Counter(c["ageGroup"] for c in chars_out)
    identity_dist = Counter(c["identity"] for c in chars_out)
    main_count = sum(1 for c in chars_out if c["isMainCharacter"])
    minor_count = len(chars_out) - main_count
    inferable = sum(1 for c in chars_out if c["confidence"] == 0.0 and not c["roleMain"])

    report = [
        "=== build_features.py 报告 ===",
        f"plays:       {len(plays_out)}",
        f"characters:  {len(chars_out)}  (main={main_count}, minor={minor_count})",
        f"未标注且待推断: {inferable}",
        "",
        "--- period 分布 ---",
    ]
    for k, v in sorted(period_dist.items(), key=lambda x: -x[1]):
        report.append(f"  {k:<14}  {v}")
    report.append("\n--- genre 分布 ---")
    for k, v in sorted(genre_dist.items(), key=lambda x: -x[1]):
        report.append(f"  {k:<10}  {v}")
    report.append("\n--- roleMain 分布 ---")
    for k, v in sorted(role_main_dist.items(), key=lambda x: -x[1]):
        report.append(f"  {(k or '<empty>'):<8}  {v}")
    report.append("\n--- roleSubtype 分布 (top 20) ---")
    for k, v in role_sub_dist.most_common(20):
        report.append(f"  {(k or '<empty>'):<12}  {v}")
    report.append("\n--- gender 分布 ---")
    for k, v in gender_dist.most_common():
        report.append(f"  {k:<6}  {v}")
    report.append("\n--- ageGroup 分布 ---")
    for k, v in age_dist.most_common():
        report.append(f"  {k:<8}  {v}")
    report.append("\n--- identity 分布 (top 15) ---")
    for k, v in identity_dist.most_common(15):
        report.append(f"  {k:<10}  {v}")

    (OUT / "_features_report.txt").write_text("\n".join(report), encoding="utf-8")
    print()
    print("\n".join(report))
    print(f"\nWrote: {OUT/'plays.json'} and {OUT/'characters.json'}")


if __name__ == "__main__":
    sys.exit(main())
