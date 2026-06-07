"""Parse every PDF in 京剧剧本/ directly into one JSON per play.

Each JSON contains the raw structured content extracted from a single PDF:
- Play metadata (title, alt titles, collection, source)
- Plot summary and notes
- Main characters with their raw 行当 labels
- Scenes (list with number and title)
- Lines (character / actionType / content, in original order)

Output layout mirrors the source folder structure:
    京剧剧本_json/<collection_code>/<play_id>_<title>.json

A `_index.json` (top-level lookup) and `_parse_report.txt` are also written.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import pymupdf  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXTRACT_DIR = ROOT / "京剧剧本"
DEFAULT_OUT_DIR = ROOT / "京剧剧本_json"
SCRIPT_DIR_NAME = "京剧剧本"
DATASET_DIR_NAME = "赛题1-I京剧数据集"
SPEC_FILE_NAME = "数据说明.xlsx"

# ============================================================
# Regex
# ============================================================
URL_LINE = re.compile(r"^https?://")
DATE_LINE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
PAGE_NUM_ONLY = re.compile(r"^\d{1,4}$")

SCENE_HEAD = re.compile(
    r"^【第\s*([零〇一二三四五六七八九十百千两\d]+)\s*"
    r"(场|出|折|回|本|幕)"
    r"(?:[\s:：·\-—]\s*(.+?))?\s*】"
)

LINE_DIALOGUE = re.compile(
    r"^([^\s\(\)（）【】〖〗：:]{1,30}(?:[、和及][^\s\(\)（）【】〖〗：:]{1,30}){0,8})\s+"
    r"[（\(]([^（）\(\)]{1,20})[\)）]\s*(.*)$"
)
LINE_CONT_ACTION = re.compile(
    r"^[\s　]{2,}[（\(]([^（）\(\)]{1,20})[\)）]\s*(.*)$"
)
STAGE_DIR = re.compile(r"^[\s　]*[（\(](.+?)[\)）][\s　]*$")

ALT_TITLE = re.compile(r"（一名[：:]《(.+?)》")
SOURCE_LINE = re.compile(r"^根据《(.+?)》(.*)整理")

YEAR_RE = re.compile(r"(1[89][0-9]{2}|20[0-9]{2})\s*年")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Jingju PDFs into per-play JSON files.")
    parser.add_argument(
        "--source-dir",
        default="",
        help="Directory containing PDFs, zip archives, or 数据说明.xlsx. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Directory for generated play JSON files.",
    )
    parser.add_argument(
        "--extract-dir",
        default=str(DEFAULT_EXTRACT_DIR),
        help="Where zip archives are extracted before parsing.",
    )
    parser.add_argument(
        "--no-extract-zips",
        action="store_true",
        help="Do not auto-extract zip archives when no PDFs are found.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show detected paths and counts without extracting or writing JSON files.",
    )
    return parser.parse_args()


def iter_files(root: Path, suffix: str):
    suffix = suffix.lower()
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() == suffix:
            yield p


def count_files(root: Path, suffix: str) -> int:
    return sum(1 for _ in iter_files(root, suffix))


def has_files(root: Path, suffix: str) -> bool:
    return any(True for _ in iter_files(root, suffix))


def source_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_dir = os.getenv("JINGJU_SCRIPT_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend(
        [
            ROOT / SCRIPT_DIR_NAME,
            ROOT.parent / DATASET_DIR_NAME / SCRIPT_DIR_NAME,
            ROOT.parent / SCRIPT_DIR_NAME,
        ]
    )
    # Keep order but avoid duplicates after resolving what exists.
    seen: set[str] = set()
    out: list[Path] = []
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p.absolute())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def looks_like_source_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return (
        has_files(path, ".pdf")
        or has_files(path, ".zip")
        or (path / SPEC_FILE_NAME).exists()
    )


def resolve_source_dir(source_arg: str) -> Path:
    if source_arg:
        source = Path(source_arg).expanduser()
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
        if not looks_like_source_dir(source):
            raise SystemExit(f"Source directory has no PDFs/zips/spec file: {source}")
        return source

    for candidate in source_candidates():
        if looks_like_source_dir(candidate):
            return candidate

    searched = "\n  ".join(str(p) for p in source_candidates())
    raise SystemExit(
        "Could not find Jingju source data. Checked:\n"
        f"  {searched}\n"
        "Pass --source-dir or set JINGJU_SCRIPT_DIR."
    )


def find_spec_file(source_dir: Path, extract_dir: Path) -> Path | None:
    for candidate in (
        source_dir / SPEC_FILE_NAME,
        source_dir.parent / SPEC_FILE_NAME,
        extract_dir / SPEC_FILE_NAME,
    ):
        if candidate.exists():
            return candidate
    return None


def decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """Recover GBK/GB18030 member names from zips without the UTF-8 flag."""
    name = info.filename.replace("\\", "/")
    if info.flag_bits & 0x800:
        return name

    for encoding in ("gb18030", "gbk"):
        try:
            return name.encode("cp437").decode(encoding).replace("\\", "/")
        except UnicodeError:
            continue
    return name


def extract_pdf_zips(source_dir: Path, extract_dir: Path) -> int:
    """Extract PDFs from collection zip archives into extract_dir/<zip-stem>/."""
    zips = sorted(iter_files(source_dir, ".zip"))
    if not zips:
        return 0

    extract_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    for zip_path in zips:
        out_subdir = extract_dir / zip_path.stem
        out_subdir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            pdf_infos = [
                info for info in zf.infolist()
                if not info.is_dir() and Path(decode_zip_member_name(info)).suffix.lower() == ".pdf"
            ]
            for info in pdf_infos:
                filename = Path(decode_zip_member_name(info)).name
                out_path = out_subdir / filename
                if out_path.exists() and out_path.stat().st_size == info.file_size:
                    continue
                with zf.open(info) as src, out_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1
        print(f"  extracted {zip_path.name} -> {out_subdir}", flush=True)
    return extracted


def prepare_pdf_source(source_dir: Path, extract_dir: Path, *, extract_zips: bool) -> Path:
    if has_files(source_dir, ".pdf"):
        return source_dir

    if not has_files(source_dir, ".zip"):
        return source_dir

    if not extract_zips:
        raise SystemExit(f"No PDFs found in {source_dir}, and zip extraction is disabled.")

    print(f"No PDFs found in {source_dir}; extracting zip archives to {extract_dir} ...", flush=True)
    extracted = extract_pdf_zips(source_dir, extract_dir)
    print(f"  extracted/updated PDFs: {extracted}", flush=True)
    return extract_dir


def cn_num_to_int(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if s in digits:
        return digits[s]
    total = 0
    section = 0
    for ch in s:
        if ch == "十":
            section = section if section else 1
            total += section * 10
            section = 0
        elif ch == "百":
            total += (section if section else 1) * 100
            section = 0
        elif ch == "千":
            total += (section if section else 1) * 1000
            section = 0
        elif ch in digits:
            section = digits[ch]
    return total + section


def collection_code_of(play_id: str) -> str:
    if play_id.startswith("7"):
        return play_id[:5] + "000"
    return play_id[:2] + "000000"


def load_collection_names(spec_path: Path | None) -> dict[str, str]:
    if spec_path is None or not spec_path.exists():
        return {}
    df = pd.read_excel(spec_path)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = row.get("文件")
        name = row.get("集合")
        if pd.isna(code) or pd.isna(name):
            continue
        out[str(int(code)).zfill(8)] = str(name).strip()
    return out


# ============================================================
# Text extraction
# ============================================================
def clean_page_lines(text: str, title: str) -> list[str]:
    out = []
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            out.append(raw)
            continue
        if URL_LINE.match(s):
            continue
        if DATE_LINE.match(s):
            continue
        if s == "中国京剧戏考":
            continue
        if s == f"《{title}》":
            continue
        if PAGE_NUM_ONLY.match(s) and len(s) <= 4:
            continue
        out.append(raw)
    return out


def extract_metadata(first_page_lines: list[str]) -> dict:
    """From the first page, pull alt_titles, main characters, plot, notes, source."""
    result = {
        "altTitles": [],
        "mainCharacters": [],
        "plot": "",
        "notes": "",
        "sourceCollection": "",
    }
    SECTION_KEYS = ("主要角色", "情节", "注释")
    section: str | None = None
    section_buf: dict[str, list[str]] = {k: [] for k in SECTION_KEYS}
    leading_buf: list[str] = []

    for raw in first_page_lines:
        s = raw.strip()
        if s in SECTION_KEYS:
            section = s
            continue
        m = SOURCE_LINE.match(s)
        if m:
            result["sourceCollection"] = m.group(1)
            section = None
            continue
        if SCENE_HEAD.match(s):
            break
        if section is None:
            leading_buf.append(raw)
        else:
            section_buf[section].append(raw)

    for line in leading_buf:
        for m in ALT_TITLE.finditer(line):
            result["altTitles"].append(m.group(1))

    for line in section_buf["主要角色"]:
        s = line.strip()
        if not s:
            continue
        if "：" in s:
            name, role = s.split("：", 1)
        elif ":" in s:
            name, role = s.split(":", 1)
        else:
            name, role = s, ""
        name, role = name.strip(), role.strip()
        if name:
            result["mainCharacters"].append({"name": name, "roleTypeRaw": role})

    result["plot"] = "\n".join(l for l in section_buf["情节"] if l.strip()).strip()
    result["notes"] = "\n".join(l for l in section_buf["注释"] if l.strip()).strip()
    return result


def extract_body(all_lines: list[str]) -> tuple[list[dict], list[dict]]:
    """Walk through cleaned body lines, emit (scenes, lines)."""
    line_records: list[dict] = []
    scenes: list[dict] = []
    cur_scene_num = 0
    cur_scene_title = ""
    cur_scene_chars: set[str] = set()
    cur_scene_line_count = 0
    cur_scene_actions: dict[str, int] = {}

    last_char: str | None = None
    line_idx = 0

    def flush_scene():
        nonlocal cur_scene_chars, cur_scene_line_count, cur_scene_actions
        if cur_scene_line_count == 0 and not cur_scene_chars and cur_scene_num == 0:
            return
        scenes.append({
            "sceneNum": cur_scene_num,
            "sceneTitle": cur_scene_title,
            "numLines": cur_scene_line_count,
            "characters": sorted(c for c in cur_scene_chars if c),
            "actions": dict(cur_scene_actions),
        })
        cur_scene_chars = set()
        cur_scene_line_count = 0
        cur_scene_actions = {}

    for raw in all_lines:
        s = raw.rstrip()
        if not s.strip():
            continue

        m = SCENE_HEAD.match(s.strip())
        if m:
            flush_scene()
            num_str, _kind, scene_title = m.groups()
            cur_scene_num = cn_num_to_int(num_str)
            cur_scene_title = (scene_title or "").strip()
            last_char = None
            continue

        m = LINE_DIALOGUE.match(s)
        if m:
            char, action, content = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            line_idx += 1
            line_records.append({
                "lineIdx": line_idx,
                "sceneNum": cur_scene_num,
                "sceneTitle": cur_scene_title,
                "character": char,
                "actionType": action,
                "content": content,
            })
            cur_scene_line_count += 1
            cur_scene_chars.add(char)
            cur_scene_actions[action] = cur_scene_actions.get(action, 0) + 1
            last_char = char
            continue

        m = LINE_CONT_ACTION.match(s)
        if m:
            action, content = m.group(1).strip(), m.group(2).strip()
            if last_char is not None:
                line_idx += 1
                line_records.append({
                    "lineIdx": line_idx,
                    "sceneNum": cur_scene_num,
                    "sceneTitle": cur_scene_title,
                    "character": last_char,
                    "actionType": action,
                    "content": content,
                })
                cur_scene_line_count += 1
                cur_scene_actions[action] = cur_scene_actions.get(action, 0) + 1
            continue

        m = STAGE_DIR.match(s)
        if m:
            content = m.group(1).strip()
            line_idx += 1
            line_records.append({
                "lineIdx": line_idx,
                "sceneNum": cur_scene_num,
                "sceneTitle": cur_scene_title,
                "character": "",
                "actionType": "舞台",
                "content": content,
            })
            cur_scene_line_count += 1
            cur_scene_actions["舞台"] = cur_scene_actions.get("舞台", 0) + 1
            continue

        # Unmatched: soft-wrap continuation of previous line
        if line_records:
            line_records[-1]["content"] = (line_records[-1]["content"] + s.strip()).strip()

    flush_scene()
    return scenes, line_records


# ============================================================
# Per-PDF pipeline
# ============================================================
def parse_pdf(pdf_path: Path, collection_names: dict[str, str]) -> tuple[dict, str | None]:
    """Returns (json_dict, error_message_or_None)."""
    stem = pdf_path.stem  # e.g. "01001001_空城计"
    if "_" in stem:
        play_id, title = stem.split("_", 1)
    else:
        play_id, title = stem, stem
    coll_code = collection_code_of(play_id)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        return ({}, f"open_failed: {e!r}")
    num_pages = len(doc)
    if num_pages == 0:
        doc.close()
        return (
            {
                "playId": play_id,
                "title": title,
                "altTitles": [],
                "collectionCode": coll_code,
                "collectionName": collection_names.get(coll_code, ""),
                "pdfFile": pdf_path.name,
                "numPages": 0,
                "plot": "",
                "notes": "",
                "yearsFound": [],
                "sourceCollection": "",
                "mainCharacters": [],
                "scenes": [],
                "lines": [],
                "stats": {"numScenes": 0, "numLines": 0, "numMainCharacters": 0},
                "parseError": "empty_pdf",
            },
            "empty_pdf",
        )

    pages_text = [page.get_text() for page in doc]
    doc.close()
    cleaned_pages = [clean_page_lines(p, title) for p in pages_text]

    metadata = extract_metadata(cleaned_pages[0])

    p1 = cleaned_pages[0]
    body_start = 0
    for i, raw in enumerate(p1):
        s = raw.strip()
        if not s:
            continue
        if SCENE_HEAD.match(s) or LINE_DIALOGUE.match(s):
            body_start = i
            break
        if STAGE_DIR.match(s):
            body_start = i
            break
    body_lines: list[str] = list(p1[body_start:])
    for p in cleaned_pages[1:]:
        body_lines.extend(p)

    scenes, lines = extract_body(body_lines)

    years_found = sorted(set(int(m.group(1)) for m in YEAR_RE.finditer(metadata["notes"])))

    play_json = {
        "playId": play_id,
        "title": title,
        "altTitles": metadata["altTitles"],
        "collectionCode": coll_code,
        "collectionName": collection_names.get(coll_code, ""),
        "pdfFile": pdf_path.name,
        "numPages": num_pages,
        "plot": metadata["plot"],
        "notes": metadata["notes"],
        "yearsFound": years_found,
        "sourceCollection": metadata["sourceCollection"],
        "mainCharacters": metadata["mainCharacters"],
        "scenes": scenes,
        "lines": lines,
        "stats": {
            "numScenes": sum(1 for s in scenes if s["sceneNum"] > 0),
            "numLines": len(lines),
            "numMainCharacters": len(metadata["mainCharacters"]),
        },
    }
    return play_json, None


# ============================================================
# Main
# ============================================================
def main():
    args = parse_args()
    source_dir = resolve_source_dir(args.source_dir)
    output_dir = Path(args.output_dir).expanduser()
    extract_dir = Path(args.extract_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    if not extract_dir.is_absolute():
        extract_dir = (Path.cwd() / extract_dir).resolve()

    spec_path = find_spec_file(source_dir, extract_dir)
    source_pdf_dir = source_dir if has_files(source_dir, ".pdf") else extract_dir
    pdf_count = count_files(source_dir, ".pdf")
    zip_count = count_files(source_dir, ".zip")

    print("Source detection:", flush=True)
    print(f"  source dir:  {source_dir}", flush=True)
    print(f"  PDFs:        {pdf_count}", flush=True)
    print(f"  zip files:   {zip_count}", flush=True)
    print(f"  spec file:   {spec_path or '(not found)'}", flush=True)
    print(f"  output dir:  {output_dir}", flush=True)
    print(f"  extract dir: {extract_dir}", flush=True)

    if args.dry_run:
        if pdf_count == 0 and zip_count > 0 and not args.no_extract_zips:
            print("Dry run: zip archives would be extracted before parsing.", flush=True)
        print("Dry run: no files were extracted or written.", flush=True)
        return 0

    source_pdf_dir = prepare_pdf_source(
        source_dir,
        extract_dir,
        extract_zips=not args.no_extract_zips,
    )

    output_dir.mkdir(exist_ok=True)
    coll_names = load_collection_names(spec_path)

    pdfs = sorted(iter_files(source_pdf_dir, ".pdf"))
    print(f"Found {len(pdfs)} PDFs", flush=True)
    if not pdfs:
        raise SystemExit(f"No PDF files found after source preparation: {source_pdf_dir}")

    written = 0
    failures: list[tuple[str, str]] = []
    index_rows: list[dict] = []
    t0 = time.time()

    for i, pdf in enumerate(pdfs, 1):
        rel_dir = collection_code_of(pdf.stem.split("_", 1)[0])
        out_subdir = output_dir / rel_dir
        out_subdir.mkdir(parents=True, exist_ok=True)
        out_path = out_subdir / f"{pdf.stem}.json"

        play_json, err = parse_pdf(pdf, coll_names)
        if err and not play_json:
            failures.append((str(pdf.relative_to(source_pdf_dir)), err))
            continue
        try:
            out_path.write_text(
                json.dumps(play_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            written += 1
            index_rows.append({
                "playId": play_json["playId"],
                "title": play_json["title"],
                "collectionCode": play_json["collectionCode"],
                "collectionName": play_json["collectionName"],
                "numPages": play_json["numPages"],
                "numScenes": play_json["stats"]["numScenes"],
                "numLines": play_json["stats"]["numLines"],
                "numMainCharacters": play_json["stats"]["numMainCharacters"],
                "yearsFound": play_json["yearsFound"],
                "altTitles": play_json["altTitles"],
                "file": str(out_path.relative_to(output_dir)).replace("\\", "/"),
            })
            if err:  # partial (e.g. empty_pdf written for traceability)
                failures.append((str(pdf.relative_to(source_pdf_dir)), err))
        except Exception as e:
            failures.append((str(pdf.relative_to(source_pdf_dir)), f"write_failed: {e!r}"))

        if i % 200 == 0 or i == len(pdfs):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            print(f"[{i}/{len(pdfs)}] written={written} fail={len(failures)} ({rate:.1f}/s)", flush=True)

    # Top-level index for downstream code
    (output_dir / "_index.json").write_text(
        json.dumps(
            {
                "totalPlays": written,
                "totalPdfs": len(pdfs),
                "sourceDir": str(source_dir),
                "sourcePdfDir": str(source_pdf_dir),
                "failures": [{"file": f, "reason": r} for f, r in failures],
                "plays": sorted(index_rows, key=lambda x: x["playId"]),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Human-readable summary
    role_counter: dict[str, int] = {}
    action_counter: dict[str, int] = {}
    coll_counter: dict[str, int] = {}
    role_blank = 0
    for row in index_rows:
        coll = row["collectionCode"]
        coll_counter[coll] = coll_counter.get(coll, 0) + 1
    for json_file in output_dir.rglob("*.json"):
        if json_file.name.startswith("_"):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in data.get("mainCharacters", []):
            rt = c.get("roleTypeRaw", "")
            if not rt:
                role_blank += 1
                continue
            role_counter[rt] = role_counter.get(rt, 0) + 1
        for ln in data.get("lines", []):
            a = ln.get("actionType", "")
            action_counter[a] = action_counter.get(a, 0) + 1

    report = []
    report.append("=== PDF → JSON 解析报告 ===")
    report.append(f"Total PDFs:     {len(pdfs)}")
    report.append(f"Wrote JSON:     {written}")
    report.append(f"Failures:       {len(failures)}")
    report.append("")
    report.append("--- Plays per collection ---")
    for code, cnt in sorted(coll_counter.items()):
        report.append(f"  {code}  {coll_names.get(code, ''):<25}  {cnt:>4}")
    report.append("")
    report.append(f"--- Top role_type_raw (blank: {role_blank}) ---")
    for k, v in sorted(role_counter.items(), key=lambda x: -x[1])[:40]:
        report.append(f"  {k:<25}  {v}")
    report.append("")
    report.append("--- Top action_type ---")
    for k, v in sorted(action_counter.items(), key=lambda x: -x[1])[:30]:
        report.append(f"  {k:<25}  {v}")
    if failures:
        report.append("")
        report.append("--- Failures (first 20) ---")
        for f, r in failures[:20]:
            report.append(f"  {f}: {r}")
    (output_dir / "_parse_report.txt").write_text("\n".join(report), encoding="utf-8")

    print("")
    print("\n".join(report[:6]))
    print(f"=== Output: {output_dir} ===")


if __name__ == "__main__":
    sys.exit(main())
