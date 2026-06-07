# LLM 数据增强说明

这版流程把“可由规则稳定计算的部分”和“需要语义判断的部分”分开：

- 角色：`scripts/infer_roles.py` 用 DeepSeek 推断低置信度或缺失的行当、身份、性别、年龄、性格标签，输出仍是 `data/characters.json`。
- 关系：`scripts/augment_relations_llm.py` 只复核高权重的“共现”边，把证据充分的边细化为君臣、夫妻、敌对等类型，输出仍是 `data/relations.json`。
- 叙事：`scripts/augment_narratives_llm.py` 保留规则脚本生成的张力曲线，用 DeepSeek 增强叙事模式、冲突类型和转折点解释，输出 `data/narratives.json`，并同步更新 `data/plays.json`。
- 主题：`scripts/augment_themes_llm.py` 用 DeepSeek 进行多标签语义主题标注，重建兼容前端的 `data/themes.json`。

## 一键运行

推荐先 dry-run，确认候选规模和日志路径：

```powershell
cd C:\Users\ROG\Desktop\ChinaVis\CS3320
$env:DEEPSEEK_API_KEY="你的 DeepSeek API key"
python scripts/build_play_json.py --dry-run
python scripts/build_play_json.py
python scripts/build_features.py
python scripts/run_llm_enhance_all.py --dry-run
```

确认无误后全量运行：

```powershell
python scripts/run_llm_enhance_all.py
```

全量运行会覆盖四个主文件：

```text
data/characters.json
data/relations.json
data/narratives.json
data/themes.json
```

叙事增强还会同步更新 `data/plays.json` 中的 `narrativePattern`、`conflictType` 等字段。每次运行的终端输出都会写入：

```text
data/llm_runs/<时间戳>/
```

如果中途失败，先看该目录下对应步骤的 `.log`。LLM 结果会同时使用 `data/llm_cache/` 缓存，重新运行时相同输入会优先复用缓存。

## 常用参数

```powershell
python scripts/run_llm_enhance_all.py --relation-min-weight 3
python scripts/run_llm_enhance_all.py --relation-min-weight 2
python scripts/run_llm_enhance_all.py --continue-on-error
python scripts/run_llm_enhance_all.py --skip-rule-rebuild
```

- `--relation-min-weight 3` 是默认值，成本和质量比较均衡。
- `--relation-min-weight 2` 会复核更多关系边，质量可能更细，但调用量明显增加。
- `--continue-on-error` 适合无人值守长跑，某一步失败后继续跑后面的步骤。
- `--skip-rule-rebuild` 强制跳过 `build_relations.py`、`build_narratives.py`、`build_themes.py`，直接基于现有 `data/*.json` 做 LLM 增强。

如果项目根目录下存在 `京剧剧本_json/`，总控脚本会先重建关系、叙事、主题的规则基线，再做 LLM 增强；如果该目录不存在，会自动跳过基线重建，避免把现有 JSON 覆盖成空结果。

如果只想修复已经生成的数据，不再调用 API，可以运行：

```powershell
python scripts/infer_roles.py --fill-only
python scripts/augment_relations_llm.py --fill-only
python scripts/augment_narratives_llm.py --fill-only
```

这些命令会把空行当、关系审计字段里的“未知”、叙事里的“未知”改为低置信度兜底结果。正常 LLM 运行时，失败批次会自动拆成更小批次重试，减少 DeepSeek 偶发 JSON 格式错误造成的整批丢失。

## 单独调试

需要抽样检查时可以单独运行：

```powershell
python scripts/infer_roles.py --dry-run --limit 20
python scripts/augment_relations_llm.py --dry-run --limit 20 --min-weight 3
python scripts/augment_narratives_llm.py --dry-run --limit 20
python scripts/augment_themes_llm.py --dry-run --limit 20
```

主题和叙事在使用 `--limit` 或 `--play-id` 时默认写预览文件，不覆盖主文件：

```text
data/themes_llm_preview.json
data/narratives_llm_preview.json
data/plays_llm_preview.json
```

只有全量运行，或显式增加 `--write-partial`，才会覆盖主文件。

## 质量控制

LLM 必须从固定枚举中选择标签；证据不足时允许输出“未知”或保持“共现”。脚本会保留 `confidence`、`llmEvidence`、`llmReason`、`roleInferenceSource`、`relationInferenceSource` 等审计字段，方便后续检查哪些内容来自原始标注、规则推断或 LLM 推断。
