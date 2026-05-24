# 戏曲文本可视化系统

基于 1063 部京剧/昆曲剧本的可视分析系统。涵盖角色行当、关系网络、主题、叙事结构与综合关联五大分析维度。

## 系统架构

```
[ React + Vite 前端 ]  →  [ FastAPI 后端 ]  →  data/*.json
       5173                    8000             (32MB 派生数据)
```

- **前端**：React 18 + TypeScript + Vite + Tailwind + ECharts，6 个分析页面 + 单剧详情
- **后端**：FastAPI 8 个 GET 接口（见 `BACKEND_API_REQUIREMENTS.md`），启动时把 `data/*.json` 加载到内存，按筛选参数返回切片
- **数据**：`data/` 已入库（32MB），包含派生好的剧本/角色/关系/叙事/主题。原 PDF 与中间 JSON 体积大未入库，但可由 `scripts/build_*.py` 重新生成

## 运行前准备

需要提前安装：

- `Node.js 18+` 和 `npm`
- `Python 3.10+` 和 `pip`
- `Git`

检查版本：

```bash
node -v
npm -v
python --version
```

## 启动（双进程：后端 + 前端）

### 1. 装依赖（首次）

```bash
git clone https://github.com/juruOvO/CS3320.git
cd CS3320
npm install
pip install fastapi uvicorn pandas pymupdf scikit-learn networkx jieba openpyxl
```

> 只看图、不重跑数据派生的话，pymupdf / scikit-learn / networkx / jieba 可以省略；最小集：`pip install fastapi uvicorn`。

### 2. 启动后端（FastAPI）

```bash
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

后端起来后访问 `http://127.0.0.1:8000/health` 应看到 `{"ok":true,"plays":1063,...}`。

### 3. 启动前端（Vite）

另开一个终端：

```bash
npm run dev
```

浏览器打开：

```
http://localhost:5173/
```

## 前端：mock 数据 vs 真后端

前端默认走 mock 数据，也可切到真后端。新建 `.env.local`：

```
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

切回 mock 把 `VITE_USE_MOCK` 改成 `true` 或删掉这个文件即可。

## 数据派生流水线（可选）

`data/` 已入库可直接用。**只有当你想从原始 PDF 重新生成数据时才需要跑下面这些**：

1. 准备原始 PDF：在项目根目录放 `京剧剧本/` 文件夹（38 个集合的 PDF + `数据说明.xlsx`）
2. 按顺序运行：

```bash
python scripts/build_play_json.py        # PDF → 京剧剧本_json/ (90MB)
python scripts/build_features.py         # 派生 plays.json + characters.json
python scripts/infer_roles.py            # 监督学习推断未标注角色行当
python scripts/build_relations.py        # 角色关系网络
python scripts/build_narratives.py       # 叙事张力 + 模式聚类
python scripts/build_themes.py           # LDA 主题模型
```

跑完后 `data/` 会被全部更新，重启后端即生效。

## 常用命令

```bash
npm run dev        # 启前端开发服
npm run build      # 生产构建
npm run lint       # ESLint
npm run test       # vitest
npm run check      # TypeScript 类型检查
```

## 生产构建

```bash
npm install
npm run build      # 产物在 dist/
```

预览构建产物：

```bash
npm run preview    # http://localhost:4173/
```

## 项目结构

```
.
├── src/                      # 前端 React 代码
├── server/main.py            # FastAPI 后端
├── scripts/                  # 数据派生脚本
├── data/                     # 派生数据 (32MB, 入库)
│   ├── plays.json            # 1063 剧本元信息
│   ├── characters.json       # 14232 角色 (含行当推断)
│   ├── relations.json        # 49031 关系边 + 网络指标
│   ├── narratives.json       # 张力曲线 + 模式聚类 + 转折点
│   └── themes.json           # LDA 主题 + 共现 + 旭日图
├── 京剧剧本/                  # 原始 PDF (未入库, 874MB)
├── 京剧剧本_json/             # 中间 JSON (未入库, 90MB)
└── BACKEND_API_REQUIREMENTS.md  # 接口契约
```
