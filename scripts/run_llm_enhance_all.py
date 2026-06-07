"""Run the full DeepSeek LLM data-enhancement pipeline unattended.

The full run overwrites the app's four main derived JSON files:
  - data/characters.json  by scripts/infer_roles.py
  - data/relations.json   by scripts/augment_relations_llm.py
  - data/narratives.json  by scripts/augment_narratives_llm.py
  - data/themes.json      by scripts/augment_themes_llm.py

When CS3320/jingju-script-json (the actual Chinese directory name is
encoded below as unicode escapes) exists, the runner also refreshes the
rule-based relation/narrative/theme baselines before the LLM pass. When it is
missing, baseline rebuilds are skipped so existing JSON files are not replaced
with empty outputs.

Examples:
    python scripts/run_llm_enhance_all.py --dry-run
    python scripts/run_llm_enhance_all.py
    python scripts/run_llm_enhance_all.py --relation-min-weight 2
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE_JSON_DIR = ROOT / "\u4eac\u5267\u5267\u672c_json"


@dataclass
class Step:
    name: str
    command: list[str]
    log_name: str
    note: str = ""


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all DeepSeek LLM data enhancements and overwrite main JSON outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every LLM script in dry-run mode; no API calls and no main JSON writes.",
    )
    parser.add_argument(
        "--relation-min-weight",
        type=int,
        default=3,
        help="Only refine relation edges whose co-occurrence weight is at least this value.",
    )
    parser.add_argument(
        "--skip-rule-rebuild",
        action="store_true",
        help="Skip build_relations/build_narratives/build_themes even if source JSON exists.",
    )
    parser.add_argument(
        "--require-source-json",
        action="store_true",
        help="Fail when CS3320/\u4eac\u5267\u5267\u672c_json is missing.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue later stages after a failed step; failures are still reported.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run child scripts.",
    )
    return parser.parse_args()


def has_source_json() -> bool:
    if not SOURCE_JSON_DIR.exists():
        return False
    return any(p.suffix.lower() == ".json" and not p.name.startswith("_") for p in SOURCE_JSON_DIR.rglob("*.json"))


def require_api_key(args: argparse.Namespace) -> None:
    if args.dry_run:
        return
    if os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY"):
        return
    raise SystemExit(
        "Missing DEEPSEEK_API_KEY. Set it first, for example:\n"
        '  $env:DEEPSEEK_API_KEY="your_api_key"\n'
        "Then rerun this script."
    )


def has_theme_baseline_deps() -> bool:
    return importlib.util.find_spec("jieba") is not None and importlib.util.find_spec("sklearn") is not None


def build_steps(args: argparse.Namespace, source_ok: bool) -> list[Step]:
    py = args.python

    if args.dry_run:
        return [
            Step("roles dry-run", [py, "scripts/infer_roles.py", "--dry-run"], "01_roles_dry_run.log"),
            Step(
                "relations dry-run",
                [py, "scripts/augment_relations_llm.py", "--dry-run", "--min-weight", str(args.relation_min_weight)],
                "02_relations_dry_run.log",
            ),
            Step("narratives dry-run", [py, "scripts/augment_narratives_llm.py", "--dry-run"], "03_narratives_dry_run.log"),
            Step("themes dry-run", [py, "scripts/augment_themes_llm.py", "--dry-run"], "04_themes_dry_run.log"),
        ]

    steps = [
        Step("roles -> data/characters.json", [py, "scripts/infer_roles.py"], "01_roles.log"),
    ]

    if source_ok and not args.skip_rule_rebuild:
        steps.extend(
            [
                Step("rebuild relation baseline -> data/relations.json", [py, "scripts/build_relations.py"], "02a_build_relations.log"),
                Step(
                    "relations LLM -> data/relations.json",
                    [py, "scripts/augment_relations_llm.py", "--min-weight", str(args.relation_min_weight)],
                    "02b_augment_relations.log",
                ),
                Step(
                    "rebuild narrative baseline -> data/narratives.json and data/plays.json",
                    [py, "scripts/build_narratives.py"],
                    "03a_build_narratives.log",
                ),
                Step("narratives LLM -> data/narratives.json and data/plays.json", [py, "scripts/augment_narratives_llm.py"], "03b_augment_narratives.log"),
            ]
        )
        if has_theme_baseline_deps():
            steps.append(Step("rebuild theme baseline -> data/themes.json", [py, "scripts/build_themes.py"], "04a_build_themes.log"))
            theme_note = ""
        else:
            theme_note = "jieba/sklearn is missing; skipped build_themes.py and will use existing theme hints."
        steps.append(Step("themes LLM -> data/themes.json", [py, "scripts/augment_themes_llm.py"], "04b_augment_themes.log", note=theme_note))
    else:
        if args.skip_rule_rebuild:
            note = "--skip-rule-rebuild was set; using existing baseline JSON files."
        else:
            note = f"{SOURCE_JSON_DIR} was not found; using existing baseline JSON files."
        steps.extend(
            [
                Step(
                    "relations LLM -> data/relations.json",
                    [py, "scripts/augment_relations_llm.py", "--min-weight", str(args.relation_min_weight)],
                    "02_augment_relations.log",
                    note=note,
                ),
                Step(
                    "narratives LLM -> data/narratives.json and data/plays.json",
                    [py, "scripts/augment_narratives_llm.py"],
                    "03_augment_narratives.log",
                    note=note,
                ),
                Step("themes LLM -> data/themes.json", [py, "scripts/augment_themes_llm.py"], "04_augment_themes.log", note=note),
            ]
        )

    return steps


def run_step(step: Step, run_dir: Path, env: dict[str, str]) -> int:
    log_path = run_dir / step.log_name
    start = time.time()

    print(f"\n=== {step.name} ===", flush=True)
    if step.note:
        print(f"Note: {step.note}", flush=True)
    print("Command:", " ".join(step.command), flush=True)
    print("Log:    ", log_path, flush=True)

    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(step.command)}\n")
        if step.note:
            log.write(f"note: {step.note}\n")
        log.write("\n")

        proc = subprocess.Popen(
            step.command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)

        code = proc.wait()
        elapsed = time.time() - start
        footer = f"\n[exit={code}] elapsed={elapsed:.1f}s\n"
        print(footer, end="")
        log.write(footer)
        return code


def write_summary(
    run_dir: Path,
    args: argparse.Namespace,
    source_ok: bool,
    failures: list[tuple[str, int]],
) -> None:
    summary_path = run_dir / "summary.txt"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(f"project={ROOT}\n")
        f.write(f"source_json_dir={SOURCE_JSON_DIR}\n")
        f.write(f"source_json_present={source_ok}\n")
        f.write(f"dry_run={args.dry_run}\n")
        f.write(f"relation_min_weight={args.relation_min_weight}\n")
        f.write(f"skip_rule_rebuild={args.skip_rule_rebuild}\n")
        if failures:
            f.write("status=failed\n")
            f.write("failures:\n")
            for name, code in failures:
                f.write(f"  {name}: exit {code}\n")
        else:
            f.write("status=success\n")


def main() -> int:
    configure_stdio()
    args = parse_args()
    require_api_key(args)

    source_ok = has_source_json()
    if args.require_source_json and not source_ok:
        raise SystemExit(f"{SOURCE_JSON_DIR} is missing or has no play JSON files.")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = DATA / "llm_runs" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("DEEPSEEK_MODEL", "deepseek-chat")
    env.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    env.setdefault("LLM_RESPONSE_FORMAT", "json_object")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    print("DeepSeek LLM data-enhancement pipeline")
    print(f"Project:              {ROOT}")
    print(f"Run logs:             {run_dir}")
    print(f"Source JSON dir:      {SOURCE_JSON_DIR}")
    print(f"Source JSON present:  {source_ok}")
    print(f"Model:                {env.get('DEEPSEEK_MODEL') or env.get('LLM_MODEL')}")
    print(f"Relation min weight:  {args.relation_min_weight}")
    print(f"Dry run:              {args.dry_run}")
    if not source_ok:
        print("Warning: source play JSON was not found, so baseline rebuild steps will be skipped.")

    failures: list[tuple[str, int]] = []
    for step in build_steps(args, source_ok):
        code = run_step(step, run_dir, env)
        if code != 0:
            failures.append((step.name, code))
            if not args.continue_on_error:
                break

    write_summary(run_dir, args, source_ok, failures)

    if failures:
        print("\nPipeline finished with failures:")
        for name, code in failures:
            print(f"  - {name}: exit {code}")
        print(f"See logs in {run_dir}")
        return 1

    print("\nPipeline finished successfully.")
    print(f"See logs in {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
