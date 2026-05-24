# 后端 API 与数据要求

这份文档只说协作需要的内容。前端已经完成原型，后端按这里提供接口即可联调。

## 1. 基本约定

- 接口统一前缀：`/api`
- 请求方法目前全部使用 `GET`
- 返回格式统一为 JSON
- 编码统一为 `UTF-8`
- 所有时间、字符串、数组字段都不要返回 `undefined`
- 没有数据时：
  - 对象字段返回空对象 `{}` 或约定默认值
  - 列表字段返回空数组 `[]`
- ID 必须稳定，不能同一条数据每次请求都变
- 字段命名统一用 `camelCase`
- 前端当前默认走 mock；接真实后端时，只替换 `VITE_API_BASE_URL`

## 2. 全局筛选参数

以下查询参数会被多个接口复用，不需要的可以忽略：

```ts
interface GlobalFilters {
  period?: string
  genre?: string
  playId?: string
  roleType?: string
  characterId?: string
  theme?: string
  narrativePattern?: string
}
```

要求：

- 所有分析接口都应支持这些筛选参数
- 筛选后返回“筛选后的结果”，不要返回全量再让前端二次筛

## 3. 必要接口

### 3.1 获取筛选项

- `GET /api/filter-options`

返回：

```ts
{
  periods: string[]
  genres: string[]
  plays: Array<{ id: string; title: string }>
  roleTypes: string[]
  themes: string[]
  narrativePatterns: string[]
}
```

### 3.2 总览页

- `GET /api/overview`

返回：

```ts
{
  summary: {
    playCount: number
    characterCount: number
    inferredRoleCount: number
    themeCount: number
    relationCount: number
    avgSceneCount: number
  }
  periodGenreDistribution: Array<{ period: string; genre: string; value: number }>
  roleDistribution: Array<{ roleType: string; value: number }>
  topThemes: Array<{ theme: string; value: number }>
  narrativePatterns: Array<{ pattern: string; value: number }>
  apiGuide: Array<{ endpoint: string; description: string }>
  playList: Array<{ id: string; title: string; period: string; genre: string; sceneCount: number }>
}
```

说明：

- `apiGuide` 现在前端首页已不展示，但可以保留，不影响兼容
- `playList` 是总览页剧目清单的直接数据源

### 3.3 角色与行当

- `GET /api/character-roles`

返回：

```ts
{
  sankeyNodes: Array<{ name: string; category: string }>
  sankeyLinks: Array<{ source: string; target: string; value: number }>
  heatmap: Array<{ period: string; roleType: string; feature: string; value: number }>
  timeline: Array<{ period: string; roleType: string; value: number }>
  characters: Array<{
    id: string
    name: string
    playId: string
    gender: string
    ageGroup: string
    identity: string
    roleMain: string
    roleSubtype: string
    confidence: number
    actionScore: number
    emotionScore: number
    appearanceCount: number
    evidence: string[]
  }>
}
```

要求：

- `confidence` 取值范围 `0 ~ 1`
- `evidence` 至少给 1 条，可用于展示推断依据

### 3.4 关系网络

- `GET /api/relations`

返回：

```ts
{
  nodes: Array<{
    id: string
    name: string
    playId: string
    roleType: string
    size: number
    centrality: number
  }>
  links: Array<{
    source: string
    target: string
    relationType: string
    weight: number
    scenes: string[]
  }>
  adjacency: Array<{ source: string; target: string; value: number }>
  metrics: Array<{
    genre: string
    density: number
    avgDegree: number
    clustering: number
    centralization: number
    modularity: number
  }>
  relationTrend: Array<{ scene: string; relationType: string; value: number }>
}
```

要求：

- `source`、`target` 必须能和 `nodes.id` 对上
- `weight` 必须是数值，不要传字符串

### 3.5 主题分析

- `GET /api/themes`

返回：

```ts
{
  sunburst: {
    name: string
    children: Array<{
      name: string
      children: Array<{ name: string; value: number }>
    }>
  }
  cooccurrenceNodes: Array<{ id: string; value: number }>
  cooccurrenceLinks: Array<{ source: string; target: string; value: number }>
  genreDistribution: Array<{ genre: string; theme: string; value: number }>
  combinations: Array<{ combination: string[]; value: number }>
  playProfiles: Array<{ playId: string; title: string; topThemes: string[] }>
}
```

### 3.6 叙事结构

- `GET /api/narratives`

返回：

```ts
{
  stages: Array<{ stage: string; order: number; description: string }>
  tensionSeries: Array<{
    playId: string
    scene: string
    tension: number
    action: number
    emotion: number
  }>
  performanceDistribution: Array<{ stage: string; form: string; value: number }>
  patternClusters: Array<{
    playId: string
    title: string
    genre: string
    x: number
    y: number
    pattern: string
  }>
  turningPoints: Array<{
    playId: string
    scene: string
    label: string
    description: string
  }>
}
```

### 3.7 综合关联分析

- `GET /api/associations`

返回：

```ts
{
  sankeyNodes: Array<{ name: string; category: string }>
  sankeyLinks: Array<{ source: string; target: string; value: number }>
  matrix: Array<{ relationFeature: string; targetFeature: string; value: number }>
  clusters: Array<{
    playId: string
    title: string
    genre: string
    x: number
    y: number
    pattern: string
  }>
  rules: Array<{
    id: string
    title: string
    support: number
    confidence: number
    description: string
    samples: string[]
  }>
}
```

### 3.8 单剧详情

- `GET /api/plays/:playId`

返回：

```ts
{
  play: {
    id: string
    title: string
    period: string
    genre: string
    authorEra: string
    sceneCount: number
    narrativePattern: string
    summary: string
  }
  characters: Array<{
    id: string
    name: string
    roleSubtype: string
    identity: string
    relationHint: string
  }>
  themes: Array<{ theme: string; weight: number }>
  narrative: Array<{ scene: string; tension: number }>
  evidence: Array<{
    id: string
    type: string
    speaker?: string
    text: string
  }>
}
```

要求：

- `:playId` 必须能从总览页的 `playList.id` 直接跳转使用

## 4. 数据要求

### 4.1 剧目基础数据

每部剧至少要有：

- `id`
- `title`
- `period`
- `genre`
- `sceneCount`
- `summary`

### 4.2 角色数据

每个角色至少要有：

- `id`
- `playId`
- `name`
- `gender`
- `ageGroup`
- `identity`
- `roleMain`
- `roleSubtype`
- `confidence`

### 4.3 关系数据

每条关系至少要有：

- `playId`
- `source`
- `target`
- `relationType`
- `weight`

### 4.4 主题数据

每条主题记录至少要有：

- `playId`
- `theme`
- `weight`

### 4.5 叙事数据

每个场次/段落至少要有：

- `playId`
- `scene`
- `stage`
- `tension`
- `action`
- `emotion`

## 5. 字段约束

- `weight`、`value`、`tension`、`action`、`emotion` 都返回数字
- `confidence` 返回 `0~1` 小数
- `sceneCount` 返回整数
- 中文字段直接返回中文，不需要前端做映射
- 图表展示字段尽量直接可用，减少前端二次计算

## 6. 联调要求

- 先保证字段结构对齐，再考虑算法精度
- 前端已经按当前字段写死渲染逻辑，不要随意改字段名
- 如果必须改字段，请先同步前端
- 如果某个接口一时做不完，优先保证：
  1. `/api/filter-options`
  2. `/api/overview`
  3. `/api/plays/:playId`
  4. `/api/character-roles`

## 7. 最低交付标准

后端可联调，至少需要满足：

- 能返回真实筛选项
- 能按筛选参数返回筛选后的结果
- 能稳定返回 8 个接口
- 所有接口字段名与本文档一致
- 空数据不报错

## 8. 文件位置

- 前端接口调用位置：`src/api/client.ts`
- 类型定义位置：`src/api/types.ts`