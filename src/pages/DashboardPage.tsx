import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { apiClient } from '@/api/client'
import type {
  AssociationResponse,
  CharacterRecord,
  CharacterRoleResponse,
  GlobalFilters,
  NarrativeResponse,
  OverviewResponse,
  RelationNetworkResponse,
  ThemeResponse,
} from '@/api/types'
import { ChartPanel } from '@/components/ChartPanel'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { cn } from '@/lib/utils'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

type TaskKey = 'roles' | 'relations' | 'themes' | 'narratives' | 'associations'
type ChartId = 'overview' | 'roles' | 'relations' | 'themes' | 'narratives' | 'associations'

type InteractionState = {
  chartId: ChartId
  label: string
  tokens: string[]
}

type TokenCarrier = { tokens: string[] }

type ClickPoint = {
  value: number | number[]
  tokens: string[]
  label?: string
  axisLabel?: string
  source?: string
  target?: string
}

type OverviewSeries = {
  name: string
  data: Array<{ value: number; tokens: string[] }>
}

type SankeyNode = {
  name: string
  label: string
  category: string
  value: number
  tokens: string[]
}

type SankeyLink = {
  source: string
  target: string
  label?: string
  value: number
  tokens: string[]
}

type CompactSankeyData = {
  nodes: SankeyNode[]
  links: SankeyLink[]
}

type GraphNode = {
  id: string
  name: string
  category: string
  value: number
  tokens: string[]
}

type GraphLink = {
  source: string
  target: string
  value: number
  tokens: string[]
}

type HeatmapCell = {
  x: string
  y: string
  value: number
  tokens: string[]
}

type LineSeries = {
  name: string
  group?: string
  isFocus?: boolean
  data: Array<{ x: string; value: number | null; tokens: string[] }>
}

type LineChartPayload = {
  xLabels: string[]
  series: LineSeries[]
  valueRange?: { min: number; max: number }
}

type ScatterPoint = {
  id: string
  label: string
  x: number
  y: number
  size: number
  category: string
  genre: string
  topTheme?: string
  dominantRelation?: string
  isFocus?: boolean
  tokens: string[]
}

type DashboardData = {
  overview: OverviewResponse
  roles: CharacterRoleResponse
  relations: RelationNetworkResponse
  themes: ThemeResponse
  narratives: NarrativeResponse
  associations: AssociationResponse
}

const taskMeta: Record<TaskKey, { label: string; focusCharts: ChartId[]; hint: string }> = {
  roles: {
    label: '角色与行当',
    focusCharts: ['roles', 'relations', 'narratives'],
    hint: '优先看角色行当图，再结合关系网络和叙事曲线观察角色如何推动剧情。',
  },
  relations: {
    label: '关系网络',
    focusCharts: ['relations', 'associations', 'narratives'],
    hint: '优先看关系网络，再联动综合关联图和叙事曲线判断关系结构如何影响剧情。',
  },
  themes: {
    label: '主题分析',
    focusCharts: ['themes', 'overview', 'associations'],
    hint: '优先看主题热力图，再回到样本分布和综合关联图总结主题偏向。',
  },
  narratives: {
    label: '叙事结构',
    focusCharts: ['narratives', 'relations', 'themes'],
    hint: '优先看叙事张力曲线，再用关系网络与主题热力图解释结构起伏的来源。',
  },
  associations: {
    label: '关联分析',
    focusCharts: ['associations', 'relations', 'themes'],
    hint: '优先看综合结构散点，再联动关系网络和主题热力图串起跨任务证据。',
  },
}

const chartTitles: Record<ChartId, string> = {
  overview: '样本分布图',
  roles: '角色特征与行当图',
  relations: '角色关系网络图',
  themes: '主题分布图',
  narratives: '叙事趋势图',
  associations: '跨任务综合图',
}

async function loadDashboardData(filters: GlobalFilters): Promise<DashboardData> {
  const [overview, roles, relations, themes, narratives, associations] = await Promise.all([
    apiClient.getOverview(filters),
    apiClient.getCharacterRoles(filters),
    apiClient.getRelations(filters),
    apiClient.getThemes(filters),
    apiClient.getNarratives(filters),
    apiClient.getAssociations(filters),
  ])

  return { overview, roles, relations, themes, narratives, associations }
}

export default function DashboardPage() {
  const { filters } = useFiltersStore()
  const [activeTask, setActiveTask] = useState<TaskKey>('roles')
  const [interaction, setInteraction] = useState<InteractionState | null>(null)
  const dashboardState = useAsyncData(() => loadDashboardData(filters), [filters])
  const dashboard = dashboardState.data ?? null
  const linkedNarrativePlayId =
    interaction?.chartId === 'associations' ? getTokenValue(interaction.tokens, 'play') : ''
  const linkedNarrativesState = useAsyncData(
    (): Promise<NarrativeResponse | null> =>
      linkedNarrativePlayId ? apiClient.getNarratives({ playId: linkedNarrativePlayId }) : Promise.resolve(null),
    [linkedNarrativePlayId],
  )
  const linkedNarratives =
    linkedNarrativePlayId &&
    linkedNarrativesState.data &&
    hasNarrativePlay(linkedNarrativesState.data, linkedNarrativePlayId)
      ? linkedNarrativesState.data
      : null

  useEffect(() => {
    setInteraction(null)
  }, [activeTask, filters])

  const overviewPayload = useMemo(
    () => (dashboard ? getOverviewPayload(buildOverviewChart(dashboard.overview), interaction) : null),
    [dashboard, interaction],
  )
  const rolesPayload = useMemo(
    () => (dashboard ? getSankeyPayload(buildRolesChart(dashboard.roles), interaction) : null),
    [dashboard, interaction],
  )
  const relationsPayload = useMemo(
    () => (dashboard ? getGraphPayload(buildRelationsChart(dashboard.relations), interaction) : null),
    [dashboard, interaction],
  )
  const themesPayload = useMemo(
    () => (dashboard ? getHeatmapPayload(buildThemesChart(dashboard.themes), interaction) : null),
    [dashboard, interaction],
  )
  const narrativesPayload = useMemo(
    () => (dashboard ? getLinePayload(buildNarrativesChart(linkedNarratives ?? dashboard.narratives), interaction) : null),
    [dashboard, interaction, linkedNarratives],
  )
  const associationsPayload = useMemo(
    () => (dashboard ? getScatterPayload(buildAssociationsChart(dashboard.associations), interaction) : null),
    [dashboard, interaction],
  )

  if (dashboardState.loading && !dashboardState.data) return <LoadingSurface />
  if (
    dashboardState.error ||
    !dashboard ||
    !overviewPayload ||
    !rolesPayload ||
    !relationsPayload ||
    !themesPayload ||
    !narrativesPayload ||
    !associationsPayload
  ) {
    return <ErrorSurface message={dashboardState.error ?? '联动看板数据为空'} />
  }

  return (
    <div>
      <Surface title="任务切换">
        <div className="flex flex-wrap gap-3">
          {(Object.keys(taskMeta) as TaskKey[]).map((task) => (
            <button
              key={task}
              type="button"
              onClick={() => setActiveTask(task)}
              className={cn(
                'rounded-full border px-4 py-2 text-sm transition',
                activeTask === task
                  ? 'border-[#8C1D18] bg-[#8C1D18] text-white shadow-lg'
                  : 'border-stone-200 bg-white/80 text-stone-600 hover:border-[#8C1D18] hover:text-[#8C1D18]',
              )}
            >
              {taskMeta[task].label}
            </button>
          ))}
        </div>
      </Surface>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartSlot chartId="overview" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.overview}
            subtitle="从样本构成进入，全局查看时期与剧类的整体分布。"
            option={createOverviewOption(overviewPayload)}
            height={380}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({ chartId: 'overview', label: point.label ?? '样本分布', tokens: point.tokens })
              },
            }}
          />
        </ChartSlot>

        <ChartSlot chartId="roles" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.roles}
            subtitle="查看角色特征如何流向主类行当和细分行当。"
            option={createSankeyOption(rolesPayload)}
            height={420}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({
                  chartId: 'roles',
                  label: point.label ?? '角色与行当',
                  tokens: point.tokens,
                })
              },
            }}
          />
        </ChartSlot>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartSlot chartId="relations" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.relations}
            subtitle="查看角色之间的互动结构、强弱和局部团簇。"
            option={createGraphOption(relationsPayload)}
            height={420}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({
                  chartId: 'relations',
                  label: point.source && point.target ? `${point.source} → ${point.target}` : point.label ?? '关系网络',
                  tokens: point.tokens,
                })
              },
            }}
          />
        </ChartSlot>

        <ChartSlot chartId="themes" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.themes}
            subtitle="按剧类和主题交叉观察主题分布，支持与其他图共享筛选。"
            option={createHeatmapOption(themesPayload)}
            height={420}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({ chartId: 'themes', label: point.label ?? '主题分布', tokens: point.tokens })
              },
            }}
          />
        </ChartSlot>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartSlot chartId="narratives" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.narratives}
            subtitle={
              filters.playId
                ? '高亮所选剧目，叠加同叙事模式的剧目作背景对照。'
                : '按剧情进度（0→100%）对照各剧目叙事张力的起伏。'
            }
            option={createLineOption(narrativesPayload)}
            height={420}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({ chartId: 'narratives', label: point.label ?? '叙事趋势', tokens: point.tokens })
              },
            }}
          />
        </ChartSlot>

        <ChartSlot chartId="associations" activeTask={activeTask}>
          <ChartPanel
            title={chartTitles.associations}
            subtitle="在综合结构空间里观察剧目之间的相似性，并回联其他图查看原因。"
            option={createScatterOption(associationsPayload)}
            height={380}
            onEvents={{
              click: (params) => {
                const point = getClickPoint(params)
                if (!point || point.tokens.length === 0) return
                setInteraction({ chartId: 'associations', label: point.label ?? '综合结构', tokens: point.tokens })
              },
            }}
          />
        </ChartSlot>
      </div>
    </div>
  )
}

function ChartSlot({
  chartId,
  activeTask,
  children,
}: {
  chartId: ChartId
  activeTask: TaskKey
  children: ReactNode
}) {
  const focused = taskMeta[activeTask].focusCharts.includes(chartId)

  return (
    <div>
      <div
        className={cn(
          'rounded-[30px] transition',
          focused
            ? 'ring-2 ring-[#8C1D18]/22 ring-offset-2 ring-offset-transparent'
            : 'opacity-95 saturate-[0.92]',
        )}
      >
      {children}
      </div>
    </div>
  )
}

function buildOverviewChart(data: OverviewResponse) {
  const periods = unique(data.periodGenreDistribution.map((item) => item.period))
  const genres = unique(data.periodGenreDistribution.map((item) => item.genre))

  return {
    xLabels: periods,
    series: genres.map((genre) => ({
      name: genre,
      data: periods.map((period) => ({
        value: data.periodGenreDistribution
          .filter((item) => item.period === period && item.genre === genre)
          .reduce((sum, item) => sum + item.value, 0),
        tokens: uniqueTokens([`period:${period}`, `genre:${genre}`]),
      })),
    })),
  }
}

function buildRolesChart(data: CharacterRoleResponse) {
  const sourceNames = new Set(data.sankeyLinks.map((link) => link.source))
  const targetNames = new Set(data.sankeyLinks.map((link) => link.target))
  const roleNames = new Set([...targetNames].filter((name) => !sourceNames.has(name)))

  const getNodeId = (layer: 'source' | 'middle' | 'target', label: string) => `${layer}:${label}`
  const getNodeLabel = (nodeId: string) => nodeId.split(':').slice(1).join(':')
  const roleWeights = buildNodeWeightMap(
    data.sankeyLinks.map((link) => {
      const isRoleLink = roleNames.has(link.target)
      return {
        source: getNodeId(isRoleLink ? 'middle' : 'source', link.source),
        target: getNodeId(isRoleLink ? 'target' : 'middle', link.target),
        value: link.value,
      }
    }),
  )

  const nodeTokens = new Map<string, string[]>()
  const edgeTokens = new Map<string, string[]>()
  const registerNode = (nodeId: string) => {
    if (nodeTokens.has(nodeId)) return
    nodeTokens.set(nodeId, collectRoleTokensForName(getNodeLabel(nodeId), data.characters))
  }

  const links = data.sankeyLinks.map((link) => {
    const isRoleLink = roleNames.has(link.target)
    const source = getNodeId(isRoleLink ? 'middle' : 'source', link.source)
    const target = getNodeId(isRoleLink ? 'target' : 'middle', link.target)
    const label = `${link.source} → ${link.target}`

    registerNode(source)
    registerNode(target)
    edgeTokens.set(
      `${source}=>${target}`,
      uniqueTokens(
        data.characters
          .filter(
            (character) => roleNameMatchesCharacter(link.source, character) && roleNameMatchesCharacter(link.target, character),
          )
          .flatMap(buildCharacterTokens),
      ),
    )

    return {
      source,
      target,
      label,
      value: link.value,
      tokens: edgeTokens.get(`${source}=>${target}`) ?? uniqueTokens([`role:${link.target}`]),
    }
  })

  const nodes = unique(links.flatMap((link) => [link.source, link.target])).map((nodeId) => {
    const category = nodeId.startsWith('source:') ? '性别' : nodeId.startsWith('middle:') ? '年龄' : '行当'
    return {
      name: nodeId,
      label: getNodeLabel(nodeId),
      category,
      value: roleWeights.get(nodeId) ?? 1,
      tokens: nodeTokens.get(nodeId) ?? [],
    }
  })

  return compactLeftSankeyNodes({ nodes, links })
}

function buildRelationsChart(data: RelationNetworkResponse) {
  const nodeMeta = new Map(data.nodes.map((node) => [node.id, node]))

  return {
    nodes: data.nodes.map((node) => ({
      id: node.id,
      name: node.name,
      category: node.roleType,
      value: node.size,
      tokens: uniqueTokens([`play:${node.playId}`, `role:${node.roleType}`, `character:${node.id}`, `name:${node.name}`]),
    })),
    links: data.links.map((link) => {
      const sourceNode = nodeMeta.get(link.source)
      const targetNode = nodeMeta.get(link.target)
      return {
        source: link.source,
        target: link.target,
        value: link.weight,
        tokens: uniqueTokens([
          `relation:${link.relationType}`,
          ...link.scenes.map((scene) => `scene:${scene}`),
          ...(sourceNode ? [`play:${sourceNode.playId}`, `role:${sourceNode.roleType}`] : []),
          ...(targetNode ? [`play:${targetNode.playId}`, `role:${targetNode.roleType}`] : []),
        ]),
      }
    }),
  }
}

function buildThemesChart(data: ThemeResponse) {
  const profileTokensByTheme = new Map<string, string[]>()

  data.playProfiles.forEach((profile) => {
    profile.topThemes.forEach((theme) => {
      const existing = profileTokensByTheme.get(theme) ?? []
      profileTokensByTheme.set(theme, uniqueTokens([...existing, `play:${profile.playId}`]))
    })
  })

  return {
    xLabels: unique(data.genreDistribution.map((item) => item.genre)),
    yLabels: unique(data.genreDistribution.map((item) => item.theme)),
    cells: data.genreDistribution.map((item) => ({
      x: item.genre,
      y: item.theme,
      value: item.value,
      tokens: uniqueTokens([`genre:${item.genre}`, `theme:${item.theme}`, ...(profileTokensByTheme.get(item.theme) ?? [])]),
    })),
  }
}

// Resample a per-scene tension series onto `steps` evenly-spaced progress points
// (linear interpolation). Plays with different scene counts thus line up on the
// same 0%→100% axis instead of leaving the right side blank.
function resampleTension(values: number[], steps: number): number[] {
  if (values.length === 0) return Array(steps).fill(null) as number[]
  if (values.length === 1) return Array(steps).fill(values[0]) as number[]
  const out: number[] = []
  for (let i = 0; i < steps; i += 1) {
    const pos = (i / (steps - 1)) * (values.length - 1)
    const lo = Math.floor(pos)
    const hi = Math.ceil(pos)
    const frac = pos - lo
    out.push(Number((values[lo] * (1 - frac) + values[hi] * frac).toFixed(4)))
  }
  return out
}

function buildNarrativesChart(data: NarrativeResponse) {
  const STEPS = 11 // 0%, 10%, … 100% — every play is resampled onto these
  const xLabels = Array.from({ length: STEPS }, (_, i) => `${Math.round((i / (STEPS - 1)) * 100)}%`)
  const playMeta = new Map(data.patternClusters.map((item) => [item.playId, item]))
  const focusId = data.focusPlayId ?? ''
  const rawPlayIds = unique(data.tensionSeries.map((item) => item.playId))
  // focus play first so it survives series-count trimming and renders on top
  const playIds = focusId ? [focusId, ...rawPlayIds.filter((id) => id !== focusId)] : rawPlayIds

  // group each play's points and order them along the plot (启→合)
  const byPlay = new Map<string, NarrativeResponse['tensionSeries']>()
  for (const item of data.tensionSeries) {
    const arr = byPlay.get(item.playId) ?? []
    arr.push(item)
    byPlay.set(item.playId, arr)
  }
  for (const arr of byPlay.values()) {
    arr.sort((a, b) => getSceneOrder(a) - getSceneOrder(b))
  }

  return {
    xLabels,
    valueRange: { min: 0, max: 1 },
    series: playIds.map((playId) => {
      const points = byPlay.get(playId) ?? []
      const resampled = resampleTension(points.map((p) => p.tension), STEPS)
      return {
        name: playMeta.get(playId)?.title ?? playId,
        group: playMeta.get(playId)?.pattern ?? '未分类',
        isFocus: focusId ? playId === focusId : undefined,
        data: resampled.map((value, i) => ({
          x: xLabels[i],
          value,
          tokens: uniqueTokens([`play:${playId}`, `progress:${xLabels[i]}`]),
        })),
      }
    }),
  }
}

function buildAssociationsChart(data: AssociationResponse) {
  const focusId = data.focusPlayId ?? ''
  return {
    points: data.clusters.map((item) => ({
      id: item.playId,
      label: item.title,
      x: item.x,
      y: item.y,
      size: focusId && item.playId === focusId ? 30 : 18,
      category: item.pattern,
      genre: item.genre,
      topTheme: item.topTheme,
      dominantRelation: item.dominantRelation,
      isFocus: focusId ? item.playId === focusId : undefined,
      tokens: uniqueTokens([`play:${item.playId}`, `pattern:${item.pattern}`, `genre:${item.genre}`]),
    })),
  }
}

function createOverviewOption(payload: {
  xLabels: string[]
  series: OverviewSeries[]
}) {
  return {
    color: chartPalette,
    tooltip: { ...tooltipStyle, trigger: 'axis' },
    legend: {
      bottom: 0,
      width: '92%',
      itemWidth: 16,
      itemHeight: 10,
      textStyle: { color: '#6b6259', fontSize: 11 },
    },
    grid: { ...commonGrid, top: 44, bottom: 74 },
    xAxis: {
      type: 'category',
      data: payload.xLabels,
      ...axisStyle,
      axisLabel: {
        ...axisStyle.axisLabel,
        interval: 0,
        rotate: payload.xLabels.length > 7 ? 16 : 0,
        margin: 12,
        hideOverlap: true,
      },
    },
    yAxis: { type: 'value', ...axisStyle },
    series: payload.series.map((series) => ({
      name: series.name,
      type: 'bar',
      stack: 'sample',
      barMaxWidth: 34,
      data: payload.xLabels.map((label, index) => ({
        value: series.data[index]?.value ?? 0,
        tokens: series.data[index]?.tokens ?? [],
        label: `${series.name} · ${label}`,
      })),
    })),
  }
}

function createSankeyOption(payload: { nodes: SankeyNode[]; links: SankeyLink[] }) {
  return {
    color: chartPalette,
    tooltip: tooltipStyle,
    series: [
      {
        type: 'sankey',
        top: 20,
        bottom: 16,
        left: 18,
        right: 18,
        nodeGap: 18,
        nodeWidth: 14,
        emphasis: { focus: 'adjacency' },
        label: {
          color: '#574f46',
          fontSize: 11,
          width: 88,
          overflow: 'truncate',
          formatter: (params: { data?: { label?: string }; name?: string }) => params.data?.label ?? params.name ?? '',
        },
        lineStyle: { color: 'gradient', curveness: 0.45 },
        data: payload.nodes.map((node) => ({
          name: node.name,
          label: node.label,
          value: node.value,
          category: node.category,
          tokens: node.tokens,
        })),
        links: payload.links.map((link) => ({
          source: link.source,
          target: link.target,
          label: link.label,
          value: link.value,
          tokens: link.tokens,
        })),
      },
    ],
  }
}

function createGraphOption(payload: { nodes: GraphNode[]; links: GraphLink[] }) {
  const readablePayload = limitGraphForDisplay(payload, 42)
  const categories = unique(readablePayload.nodes.map((node) => node.category))
  const categoryIndex = new Map(categories.map((category, index) => [category, index]))

  return {
    color: chartPalette,
    tooltip: tooltipStyle,
    series: [
      {
        type: 'graph',
        layout: 'force',
        top: 42,
        right: 48,
        bottom: 42,
        left: 48,
        roam: true,
        draggable: true,
        force: {
          initLayout: 'circular',
          repulsion: 130,
          edgeLength: [68, 118],
          gravity: 0.32,
          layoutAnimation: false,
        },
        categories: categories.map((category) => ({ name: category })),
        label: {
          show: true,
          color: '#433b34',
          fontSize: 11,
          width: 58,
          overflow: 'truncate',
        },
        labelLayout: { hideOverlap: true },
        lineStyle: { opacity: 0.72, color: '#b38d68' },
        data: readablePayload.nodes.map((node) => ({
          id: node.id,
          name: node.name,
          category: categoryIndex.get(node.category) ?? 0,
          symbolSize: Math.max(16, Math.min(node.value * 1.25, 42)),
          tokens: node.tokens,
        })),
        links: readablePayload.links.map((link) => ({
          source: link.source,
          target: link.target,
          value: link.value,
          tokens: link.tokens,
          lineStyle: { width: Math.max(1.5, link.value / 1.8) },
        })),
      },
    ],
  }
}

function createHeatmapOption(payload: {
  xLabels: string[]
  yLabels: string[]
  cells: HeatmapCell[]
}) {
  const maxValue = Math.max(...payload.cells.map((cell) => cell.value), 1)

  return {
    tooltip: tooltipStyle,
    grid: { ...commonGrid, top: 42, left: 96, bottom: 86 },
    xAxis: {
      type: 'category',
      data: payload.xLabels,
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, interval: 0, hideOverlap: true },
    },
    yAxis: {
      type: 'category',
      data: payload.yLabels,
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, width: 76, overflow: 'truncate' },
    },
    visualMap: {
      min: 0,
      max: maxValue,
      orient: 'horizontal',
      left: 'center',
      bottom: 6,
      itemWidth: 12,
      itemHeight: 180,
      inRange: { color: ['#f8efe1', '#d5ac76', '#8C1D18'] },
    },
    series: [
      {
        type: 'heatmap',
        data: payload.cells.map((cell) => ({
          value: [payload.xLabels.indexOf(cell.x), payload.yLabels.indexOf(cell.y), cell.value],
          tokens: cell.tokens,
          label: `${cell.y} × ${cell.x}`,
        })),
      },
    ],
  }
}

function createLineOption(payload: LineChartPayload) {
  const normalizedPayload =
    payload.series.length > 12
      ? aggregateNormalizedLineSeriesByGroup(payload.series)
      : { xLabels: payload.xLabels, series: pickRepresentativeLineSeries(payload.series, 6) }
  const displayedSeries = normalizedPayload.series
  const valueRange = payload.valueRange ?? getLineValueRange(displayedSeries)
  const hasFocus = displayedSeries.some((series) => series.isFocus)
  const showLegend = displayedSeries.length <= 8
  return {
    color: chartPalette,
    tooltip: { ...tooltipStyle, trigger: 'axis' },
    legend: showLegend
      ? {
          bottom: 0,
          width: '92%',
          itemWidth: 16,
          itemHeight: 10,
          textStyle: { color: '#6b6259', fontSize: 11 },
        }
      : { show: false },
    grid: { ...commonGrid, top: 42, bottom: showLegend ? 92 : 56 },
    xAxis: {
      type: 'category',
      data: normalizedPayload.xLabels,
      ...axisStyle,
      axisLabel: { ...axisStyle.axisLabel, margin: 12 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      min: valueRange.min,
      max: valueRange.max,
      axisLabel: {
        color: '#6b6259',
        fontSize: 11,
        formatter: (value: number) => value.toFixed(2),
      },
      splitLine: axisStyle.splitLine,
      axisLine: axisStyle.axisLine,
    },
    dataZoom:
      normalizedPayload.xLabels.length > 12
        ? [
            { type: 'inside', start: 0, end: 45 },
            { type: 'slider', bottom: showLegend ? 34 : 8, start: 0, end: 45, height: 18 },
          ]
        : undefined,
    series: displayedSeries.map((series, index) => {
      const isFocus = Boolean(series.isFocus)
      return {
        name: series.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: true,
        z: isFocus ? 10 : 2,
        lineStyle: {
          width: hasFocus ? (isFocus ? 3.4 : 1.3) : index < 4 ? 2.6 : 1.7,
          opacity: hasFocus ? (isFocus ? 1 : 0.3) : index < 4 ? 0.92 : 0.58,
        },
        data: normalizedPayload.xLabels.map((label) => {
          const point = series.data.find((item) => item.x === label)
          return {
            value: point?.value ?? null,
            tokens: point?.tokens ?? [],
            label: `${series.name} · ${label}`,
          }
        }),
      }
    }),
  }
}

function createScatterOption(payload: { points: ScatterPoint[] }) {
  const highlightPoints = pickHighlightedScatterPoints(payload.points, 10)
  const showAllLabels = payload.points.length <= 36
  const hasFocus = payload.points.some((point) => point.isFocus)
  return {
    color: chartPalette,
    tooltip: {
      ...tooltipStyle,
      trigger: 'item',
      formatter: (params: {
        data?: {
          label?: string
          genre?: string
          category?: string
          topTheme?: string
          dominantRelation?: string
          value?: number[]
        }
      }) => {
        const point = params.data
        if (!point) return ''
        const [x, y] = point.value ?? []
        return [
          `<div style="font-weight:600;margin-bottom:6px;">${point.label ?? '未命名剧目'}</div>`,
          `<div>剧类：${point.genre ?? '未知'}</div>`,
          `<div>叙事模式：${point.category ?? '未知'}</div>`,
          `<div>主导关系：${point.dominantRelation ?? '未知'}</div>`,
          `<div>核心主题：${point.topTheme ?? '未知'}</div>`,
          `<div>坐标：${formatNumber(x)} / ${formatNumber(y)}</div>`,
        ].join('')
      },
    },
    grid: { ...commonGrid, top: 54, right: 52, bottom: 58 },
    xAxis: {
      type: 'value',
      name: '关系复杂度',
      nameLocation: 'middle',
      nameGap: 34,
      ...axisStyle,
    },
    yAxis: {
      type: 'value',
      name: '主题-叙事耦合度',
      nameLocation: 'middle',
      nameGap: 42,
      ...axisStyle,
    },
    series: [
      {
        type: 'scatter',
        data: payload.points.map((point) => ({
          value: [point.x, point.y],
          label: point.label,
          genre: point.genre,
          category: point.category,
          topTheme: point.topTheme,
          dominantRelation: point.dominantRelation,
          tokens: point.tokens,
          symbolSize: point.isFocus
            ? 30
            : payload.points.length > 160
              ? Math.max(8, point.size - 8)
              : point.size,
          itemStyle: point.isFocus
            ? { color: '#8C1D18', opacity: 1, borderColor: '#ffffff', borderWidth: 2 }
            : undefined,
          isFocus: point.isFocus,
        })),
        itemStyle: { opacity: hasFocus ? 0.22 : showAllLabels ? 0.78 : 0.32 },
        label: {
          show: showAllLabels || hasFocus,
          formatter: (params: { data: { label?: string; isFocus?: boolean } }) =>
            hasFocus && !params.data.isFocus ? '' : String(params.data.label ?? ''),
          position: 'top',
          color: '#6b6259',
          fontSize: 11,
        },
        labelLayout: { hideOverlap: true },
        emphasis: {
          scale: true,
          itemStyle: { opacity: 1, borderColor: '#8C1D18', borderWidth: 2 },
          label: {
            show: true,
            formatter: (params: { data: { label?: string } }) => String(params.data.label ?? ''),
            position: 'top',
            color: '#433b34',
          },
        },
      },
      ...(showAllLabels
        ? []
        : [
            {
              type: 'scatter',
              data: highlightPoints.map((point) => ({
                value: [point.x, point.y],
                label: point.label,
                genre: point.genre,
                category: point.category,
                topTheme: point.topTheme,
                dominantRelation: point.dominantRelation,
                tokens: point.tokens,
                symbolSize: Math.max(point.size, 16),
              })),
              itemStyle: { opacity: 0.88 },
              label: {
                show: true,
                formatter: (params: { data: { label?: string } }) => String(params.data.label ?? ''),
                position: 'top',
                color: '#6b6259',
                fontSize: 11,
              },
              labelLayout: { hideOverlap: true },
            },
          ]),
    ],
  }
}

function getOverviewPayload(
  overview: { xLabels: string[]; series: OverviewSeries[] },
  interaction: InteractionState | null,
) {
  if (!interaction) return overview

  const series = overview.series
    .map((seriesItem) => ({
      ...seriesItem,
      data: seriesItem.data.map((point) => ({
        ...point,
        value: matchesTokens(point, interaction.tokens) ? point.value : 0,
      })),
    }))

  return { ...overview, series }
}

function getSankeyPayload(
  roles: { nodes: SankeyNode[]; links: SankeyLink[] },
  interaction: InteractionState | null,
) {
  if (!interaction) return roles

  const links = roles.links.filter((link) => matchesTokens(link, interaction.tokens))
  if (links.length === 0) return roles

  const nodeNames = new Set(links.flatMap((link) => [link.source, link.target]))
  return {
    nodes: roles.nodes.filter((node) => nodeNames.has(node.name)),
    links,
  }
}

function getGraphPayload(
  graph: { nodes: GraphNode[]; links: GraphLink[] },
  interaction: InteractionState | null,
) {
  if (!interaction) return graph

  const links = graph.links.filter((link) => matchesTokens(link, interaction.tokens))
  const nodes = graph.nodes.filter(
    (node) => matchesTokens(node, interaction.tokens) || links.some((link) => link.source === node.id || link.target === node.id),
  )

  return nodes.length > 0 ? { nodes, links } : graph
}

function getHeatmapPayload(
  heatmap: { xLabels: string[]; yLabels: string[]; cells: HeatmapCell[] },
  interaction: InteractionState | null,
) {
  if (!interaction) return heatmap

  const cells = heatmap.cells.filter((cell) => matchesTokens(cell, interaction.tokens))
  if (cells.length === 0) return heatmap

  return {
    xLabels: unique(cells.map((cell) => cell.x)),
    yLabels: unique(cells.map((cell) => cell.y)),
    cells,
  }
}

function getLinePayload(
  line: LineChartPayload,
  interaction: InteractionState | null,
) {
  if (!interaction) return line

  const filteredSeries = line.series
    .map((series) => ({
      ...series,
      data: series.data.filter((point) => matchesTokens(point, interaction.tokens)),
    }))
    .filter((series) => series.data.length > 0)

  if (filteredSeries.length === 0) return line

  return {
    xLabels: unique(filteredSeries.flatMap((series) => series.data.map((point) => point.x))),
    series: filteredSeries,
    valueRange: line.valueRange,
  }
}

function getScatterPayload(
  scatter: { points: ScatterPoint[] },
  interaction: InteractionState | null,
) {
  if (!interaction) return scatter
  const points = scatter.points.filter((point) => matchesTokens(point, interaction.tokens))
  return points.length > 0 ? { points } : scatter
}

function limitGraphForDisplay(graph: { nodes: GraphNode[]; links: GraphLink[] }, maxNodes: number) {
  if (graph.nodes.length <= maxNodes) return graph

  const linkWeight = new Map<string, number>()
  graph.links.forEach((link) => {
    linkWeight.set(link.source, (linkWeight.get(link.source) ?? 0) + link.value)
    linkWeight.set(link.target, (linkWeight.get(link.target) ?? 0) + link.value)
  })

  const visibleNodes = [...graph.nodes]
    .sort((a, b) => b.value + (linkWeight.get(b.id) ?? 0) * 0.35 - (a.value + (linkWeight.get(a.id) ?? 0) * 0.35))
    .slice(0, maxNodes)
  const visibleIds = new Set(visibleNodes.map((node) => node.id))
  const visibleLinks = graph.links
    .filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target))
    .sort((a, b) => b.value - a.value)
    .slice(0, maxNodes * 2)

  return { nodes: visibleNodes, links: visibleLinks }
}

function getClickPoint(params: unknown): ClickPoint | null {
  const payload = params as {
    value?: number | number[]
    data?: { value?: number | number[]; tokens?: string[]; label?: string; source?: string; target?: string }
    name?: string
    seriesName?: string
    dataType?: string
  }

  const data = payload.data ?? {}
  const tokens = data.tokens ?? []
  if (tokens.length === 0) return null

  return {
    value: data.value ?? payload.value ?? 0,
    tokens,
    label: data.label ?? payload.name ?? payload.seriesName,
    source: data.source,
    target: data.target,
  }
}

function buildNodeWeightMap(edges: Array<{ source: string; target: string; value: number }>) {
  const weightMap = new Map<string, number>()
  edges.forEach((edge) => {
    weightMap.set(edge.source, (weightMap.get(edge.source) ?? 0) + edge.value)
    weightMap.set(edge.target, (weightMap.get(edge.target) ?? 0) + edge.value)
  })
  return weightMap
}

function compactLeftSankeyNodes(data: CompactSankeyData): CompactSankeyData {
  const sourceNames = new Set(data.links.map((link) => link.source))
  const targetNames = new Set(data.links.map((link) => link.target))
  const leftNodes = data.nodes.filter((node) => sourceNames.has(node.name) && !targetNames.has(node.name))
  const otherNodes = data.nodes.filter((node) => !leftNodes.some((leftNode) => leftNode.name === node.name))

  const hiddenMap = new Map<string, { aggregateName: string; category: string }>()
  const compactNodes: SankeyNode[] = []

  groupBy(leftNodes, (node) => node.category).forEach((nodes, category) => {
    const sortedNodes = [...nodes].sort((a, b) => b.value - a.value)
    const keepNodes = sortedNodes.slice(0, 5)
    const hiddenNodes = sortedNodes.slice(5)
    compactNodes.push(...keepNodes)

    if (hiddenNodes.length > 0) {
      const aggregateName = `${category}其他`
      hiddenNodes.forEach((node) => hiddenMap.set(node.name, { aggregateName, category }))
      compactNodes.push({
        name: aggregateName,
        label: `${category}其他`,
        category,
        value: hiddenNodes.reduce((sum, node) => sum + node.value, 0),
        tokens: uniqueTokens(hiddenNodes.flatMap((node) => node.tokens)),
      })
    }
  })

  if (hiddenMap.size === 0) {
    return data
  }

  const mergedLinks = new Map<string, SankeyLink>()
  data.links.forEach((link) => {
    const sourceOverride = hiddenMap.get(link.source)
    const nextSource = sourceOverride?.aggregateName ?? link.source
    const key = `${nextSource}=>${link.target}`
    const existing = mergedLinks.get(key)

    if (existing) {
      existing.value += link.value
      existing.tokens = uniqueTokens([...existing.tokens, ...link.tokens])
      return
    }

    mergedLinks.set(key, {
      source: nextSource,
      target: link.target,
      label: link.label,
      value: link.value,
      tokens: [...link.tokens],
    })
  })

  return {
    nodes: [...compactNodes, ...otherNodes],
    links: [...mergedLinks.values()],
  }
}

function collectRoleTokensForName(name: string, characters: CharacterRecord[]) {
  return uniqueTokens(characters.filter((character) => roleNameMatchesCharacter(name, character)).flatMap(buildCharacterTokens))
}

function roleNameMatchesCharacter(name: string, character: CharacterRecord) {
  return (
    character.roleMain === name ||
    character.roleSubtype === name ||
    character.identity === name ||
    character.ageGroup === name ||
    character.gender === name ||
    character.personalityTags.includes(name)
  )
}

function buildCharacterTokens(character: CharacterRecord) {
  return uniqueTokens([
    `play:${character.playId}`,
    `role:${character.roleMain}`,
    `role:${character.roleSubtype}`,
    `character:${character.id}`,
  ])
}

function unique<T>(items: T[]) {
  return [...new Set(items)]
}

function uniqueTokens(tokens: string[]) {
  return unique(tokens.filter(Boolean))
}

function getTokenValue(tokens: string[], key: string) {
  const prefix = `${key}:`
  const token = tokens.find((item) => item.startsWith(prefix))
  return token ? token.slice(prefix.length) : ''
}

function hasNarrativePlay(data: NarrativeResponse, playId: string) {
  return data.tensionSeries.some((item) => item.playId === playId)
}

function getSceneOrder(point: { scene?: string; sceneNum?: number }) {
  if (typeof point.sceneNum === 'number') return point.sceneNum
  const matched = point.scene?.match(/\d+/)
  return matched ? Number(matched[0]) : Number.MAX_SAFE_INTEGER
}

function pickRepresentativeLineSeries(series: LineSeries[], maxSeries: number) {
  if (series.length <= maxSeries) return series

  const scoredSeries = [...series]
    .map((item) => ({ item, score: scoreLineSeries(item) }))
    .sort((a, b) => b.score - a.score)

  const selectedByGroup = new Map<string, { item: LineSeries; score: number }>()
  scoredSeries.forEach((entry) => {
    const group = entry.item.group ?? entry.item.name
    if (!selectedByGroup.has(group)) {
      selectedByGroup.set(group, entry)
    }
  })

  const selected = [...selectedByGroup.values()]
    .sort((a, b) => b.score - a.score)
    .slice(0, maxSeries)

  if (selected.length < maxSeries) {
    const usedNames = new Set(selected.map((entry) => entry.item.name))
    scoredSeries.forEach((entry) => {
      if (selected.length >= maxSeries || usedNames.has(entry.item.name)) return
      selected.push(entry)
      usedNames.add(entry.item.name)
    })
  }

  return selected.map(({ item }) => item)
}

function aggregateNormalizedLineSeriesByGroup(series: LineSeries[]) {
  const normalizedAxis = buildNormalizedAxis(11)
  const groupedSeries = groupBy(series, (item) => item.group ?? '未分类')

  const aggregatedSeries = [...groupedSeries.entries()]
    .map(([group, groupSeries]) => ({
      name: `${group}平均趋势`,
      group,
      data: normalizedAxis.map((axisPoint) => {
        const sampledPoints = groupSeries
          .map((item) => sampleLineSeriesAtPosition(item, axisPoint.position))
          .filter((point): point is { value: number; tokens: string[] } => point !== null)

        return {
          x: axisPoint.label,
          value:
            sampledPoints.length > 0
              ? Number((sampledPoints.reduce((sum, point) => sum + point.value, 0) / sampledPoints.length).toFixed(3))
              : null,
          tokens: uniqueTokens(sampledPoints.flatMap((point) => point.tokens)),
        }
      }),
    }))
    .sort((a, b) => scoreLineSeries(b) - scoreLineSeries(a))

  return {
    xLabels: normalizedAxis.map((item) => item.label),
    series: aggregatedSeries,
  }
}

function buildNormalizedAxis(stepCount: number) {
  return Array.from({ length: stepCount }, (_, index) => {
    const position = stepCount === 1 ? 0 : index / (stepCount - 1)
    return {
      position,
      label: `${Math.round(position * 100)}%`,
    }
  })
}

function sampleLineSeriesAtPosition(series: LineSeries, position: number) {
  const points = series.data.filter((point): point is { x: string; value: number; tokens: string[] } => point.value !== null)
  if (points.length === 0) return null
  if (points.length === 1) {
    return { value: points[0].value, tokens: points[0].tokens }
  }

  const scaledIndex = position * (points.length - 1)
  const leftIndex = Math.floor(scaledIndex)
  const rightIndex = Math.min(Math.ceil(scaledIndex), points.length - 1)
  const leftPoint = points[leftIndex]
  const rightPoint = points[rightIndex]

  if (!leftPoint || !rightPoint) return null
  if (leftIndex === rightIndex) {
    return { value: leftPoint.value, tokens: uniqueTokens([...leftPoint.tokens, ...rightPoint.tokens]) }
  }

  const ratio = scaledIndex - leftIndex
  return {
    value: Number((leftPoint.value + (rightPoint.value - leftPoint.value) * ratio).toFixed(3)),
    tokens: uniqueTokens([...leftPoint.tokens, ...rightPoint.tokens]),
  }
}

function pickHighlightedScatterPoints(points: ScatterPoint[], maxLabels: number) {
  if (points.length <= maxLabels) return points

  const centerX = points.reduce((sum, point) => sum + point.x, 0) / points.length
  const centerY = points.reduce((sum, point) => sum + point.y, 0) / points.length

  return [...points]
    .map((point) => {
      const distance = Math.hypot(point.x - centerX, point.y - centerY)
      const score = distance + point.size * 0.6
      return { point, score }
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, maxLabels)
    .map(({ point }) => point)
}

function scoreLineSeries(series: LineSeries) {
  const values = series.data.map((point) => point.value).filter((value): value is number => value !== null)
  const peak = values.length > 0 ? Math.max(...values) : 0
  const trough = values.length > 0 ? Math.min(...values) : 0
  const variation = values.length > 1 ? values.slice(1).reduce((sum, value, index) => sum + Math.abs(value - values[index]), 0) : 0
  return values.length * 10 + peak * 12 + (peak - trough) * 8 + variation * 4
}

function getLineValueRange(series: LineSeries[]) {
  const values = series.flatMap((item) => item.data.map((point) => point.value).filter((value): value is number => value !== null))
  if (values.length === 0) {
    return { min: 0, max: 1 }
  }

  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const span = rawMax - rawMin
  const visibleSpan = Math.max(span, 0.035)
  const padding = visibleSpan * 0.18

  return {
    min: Math.max(0, Number((rawMin - padding).toFixed(3))),
    max: Math.min(1, Number((rawMax + padding).toFixed(3))),
  }
}

function formatNumber(value: number | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return value.toFixed(1)
}

function groupBy<T>(items: T[], getKey: (item: T) => string) {
  const groups = new Map<string, T[]>()
  items.forEach((item) => {
    const key = getKey(item)
    const bucket = groups.get(key) ?? []
    bucket.push(item)
    groups.set(key, bucket)
  })
  return groups
}

function matchesTokens(item: TokenCarrier, activeTokens?: string[]) {
  if (!activeTokens || activeTokens.length === 0) return true
  return item.tokens.some((token) => activeTokens.includes(token))
}
