"""Repair play titles using the original PDF names stored in source zip files.

Some source archives do not mark filenames as UTF-8. Python then decodes Chinese
PDF names as CP437, which produces mojibake titles in generated JSON. This script
rebuilds a playId -> title map from the raw zip entries and updates the derived
JSON files in data/ plus the per-play JSON metadata.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP_DIR = ROOT.parent / "赛题1-I京剧数据集" / "京剧剧本"
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_PLAY_JSON_DIR = ROOT / "京剧剧本_json"

PLAY_FILE_RE = re.compile(r"^(\d{8})_(.+)$")
MOJIBAKE_RE = re.compile(r"[�╔╚╦╩╠═║╣╬╢╥⌡╞┐└┘│├┤┬┴┼█▄▀]")
WINDOWS_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair generated Jingju titles from source zip filenames.")
    parser.add_argument("--zip-dir", default=str(DEFAULT_ZIP_DIR), help="Directory containing source .zip archives.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory containing plays/themes/narratives JSON.")
    parser.add_argument("--play-json-dir", default=str(DEFAULT_PLAY_JSON_DIR), help="Directory containing per-play JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files.")
    return parser.parse_args()


def decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    if info.flag_bits & 0x800:
        return name

    for encoding in ("gb18030", "gbk"):
        try:
            return name.encode("cp437").decode(encoding).replace("\\", "/")
        except UnicodeError:
            continue
    return name


def build_title_map(zip_dir: Path) -> dict[str, str]:
    title_map: dict[str, str] = {}
    for zip_path in sorted(zip_dir.rglob("*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                filename = Path(decode_zip_member_name(info)).name
                if Path(filename).suffix.lower() != ".pdf":
                    continue
                matched = PLAY_FILE_RE.match(Path(filename).stem)
                if not matched:
                    continue
                play_id, title = matched.groups()
                if not title:
                    continue
                existing = title_map.get(play_id)
                if existing is None or (MOJIBAKE_RE.search(existing) and not MOJIBAKE_RE.search(title)):
                    title_map[play_id] = title
    return title_map


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, dry_run: bool) -> None:
    if dry_run:
        return
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_title(obj: dict[str, Any], title_map: dict[str, str]) -> bool:
    play_id = obj.get("playId") or obj.get("id")
    if not isinstance(play_id, str):
        return False
    title = title_map.get(play_id)
    if not title:
        return False

    changed = False
    if obj.get("title") != title:
        obj["title"] = title
        changed = True
    if "pdfFile" in obj:
        next_pdf = f"{play_id}_{title}.pdf"
        if obj.get("pdfFile") != next_pdf:
            obj["pdfFile"] = next_pdf
            changed = True
    return changed


def repair_list_file(path: Path, title_map: dict[str, str], dry_run: bool) -> int:
    if not path.exists():
        return 0
    data = load_json(path)
    if not isinstance(data, list):
        return 0

    changed = 0
    for item in data:
        if isinstance(item, dict) and update_title(item, title_map):
            changed += 1
    write_json(path, data, dry_run) if changed else None
    return changed


def repair_profile_file(path: Path, profile_keys: list[str], title_map: dict[str, str], dry_run: bool) -> int:
    if not path.exists():
        return 0
    data = load_json(path)
    if not isinstance(data, dict):
        return 0

    changed = 0
    for key in profile_keys:
        profiles = data.get(key, [])
        if not isinstance(profiles, list):
            continue
        for item in profiles:
            if isinstance(item, dict) and update_title(item, title_map):
                changed += 1
    write_json(path, data, dry_run) if changed else None
    return changed


def repair_play_json_files(play_json_dir: Path, title_map: dict[str, str], dry_run: bool) -> int:
    if not play_json_dir.exists():
        return 0

    changed = 0
    for path in play_json_dir.rglob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if update_title(data, title_map):
            changed += 1
            write_json(path, data, dry_run)
    return changed


def repair_index_file(play_json_dir: Path, title_map: dict[str, str], dry_run: bool) -> int:
    index_path = play_json_dir / "_index.json"
    if not index_path.exists():
        return 0

    data = load_json(index_path)
    changed = 0
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and update_title(item, title_map):
                changed += 1
    elif isinstance(data, dict):
        for play_id, item in data.items():
            if isinstance(item, dict):
                item.setdefault("id", play_id)
                if update_title(item, title_map):
                    changed += 1

    write_json(index_path, data, dry_run) if changed else None
    return changed


def count_mojibake_titles(data_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}

    plays_path = data_dir / "plays.json"
    if plays_path.exists():
        plays = load_json(plays_path)
        counts["plays"] = sum(1 for item in plays if isinstance(item, dict) and MOJIBAKE_RE.search(str(item.get("title", ""))))

    themes_path = data_dir / "themes.json"
    if themes_path.exists():
        themes = load_json(themes_path)
        profiles = []
        if isinstance(themes, dict):
            profiles.extend(themes.get("playProfiles", []))
            profiles.extend(themes.get("llmThemeProfiles", []))
        counts["themes"] = sum(1 for item in profiles if isinstance(item, dict) and MOJIBAKE_RE.search(str(item.get("title", ""))))

    narratives_path = data_dir / "narratives.json"
    if narratives_path.exists():
        narratives = load_json(narratives_path)
        profiles = []
        if isinstance(narratives, dict):
            profiles.extend(narratives.get("patternClusters", []))
            profiles.extend(narratives.get("llmNarrativeProfiles", []))
        counts["narratives"] = sum(
            1 for item in profiles if isinstance(item, dict) and MOJIBAKE_RE.search(str(item.get("title", "")))
        )

    return counts


def main() -> None:
    args = parse_args()
    zip_dir = Path(args.zip_dir)
    data_dir = Path(args.data_dir)
    play_json_dir = Path(args.play_json_dir)

    title_map = build_title_map(zip_dir)
    if not title_map:
        raise SystemExit(f"No PDF title entries found in {zip_dir}")

    before = count_mojibake_titles(data_dir)
    changed = {
        "plays": repair_list_file(data_dir / "plays.json", title_map, args.dry_run),
        "themes": repair_profile_file(data_dir / "themes.json", ["playProfiles", "llmThemeProfiles"], title_map, args.dry_run),
        "narratives": repair_profile_file(
            data_dir / "narratives.json",
            ["patternClusters", "llmNarrativeProfiles"],
            title_map,
            args.dry_run,
        ),
        "play_json": repair_play_json_files(play_json_dir, title_map, args.dry_run),
        "play_index": repair_index_file(play_json_dir, title_map, args.dry_run),
    }
    after = before if args.dry_run else count_mojibake_titles(data_dir)

    print(f"title_map={len(title_map)}")
    print(f"changed={changed}")
    print(f"mojibake_before={before}")
    print(f"mojibake_after={after}")


if __name__ == "__main__":
    main()
