import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { EvidencePanel } from '@/components/EvidencePanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function RolesPage() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getCharacterRoles(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '角色与行当数据为空'} />

  const heatmapPeriods = [...new Set(data.heatmap.map((item) => item.period))]
  const heatmapFeatures = [...new Set(data.heatmap.map((item) => `${item.roleType}|${item.feature}`))]
  const scatterOption = {
    color: chartPalette,
    tooltip: { ...tooltipStyle, trigger: 'item' },
    grid: commonGrid,
    xAxis: { type: 'value', name: '舞台行动强度', ...axisStyle },
    yAxis: { type: 'value', name: '语言情感强度', ...axisStyle },
    series: [
      {
        type: 'scatter',
        symbolSize: (value: number[]) => value[2] * 2.6,
        data: data.characters.map((character) => [
          character.actionScore,
          character.emotionScore,
          character.appearanceCount,
          character.name,
          character.roleSubtype,
        ]),
        label: {
          show: true,
          formatter: (params: { data: (string | number)[] }) => String(params.data[3]),
          position: 'top',
          color: '#6b6259',
        },
      },
    ],
  }

  return (
    <div>
      <PageIntro
        eyebrow="Roles"
        title="角色特征、行当推断与时代变化"
        description="本页聚焦未标注角色的行当归属推断，以及角色性别、年龄、身份、性格与唱念做打提示如何映射到生、旦、净、丑及细分支。"
      />

      <div className="grid gap-4 xl:grid-cols-[1.55fr_1fr]">
        <ChartPanel
          title="角色特征 → 行当"
          subtitle="从身份、年龄、性格特征流向细分行当，展示推断规则与分布。"
          height={420}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            series: [
              {
                type: 'sankey',
                left: 18,
                right: 18,
                top: 24,
                bottom: 20,
                emphasis: { focus: 'adjacency' },
                nodeGap: 12,
                data: data.sankeyNodes,
                links: data.sankeyLinks,
                lineStyle: { color: 'gradient', curveness: 0.45 },
                label: { color: '#574f46', fontSize: 11 },
              },
            ],
          }}
        />

        <EvidencePanel
          title="角色推断证据"
          items={data.characters.slice(0, 6).map((character) => ({
            key: character.id,
            label: `${character.name} · ${character.roleSubtype} · 置信度 ${(character.confidence * 100).toFixed(0)}%`,
            value: character.evidence.join('；'),
          }))}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="时期 × 行当/特征热力图"
          subtitle="观察不同历史时期中角色画像与行当归属的典型对应关系。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            grid: { ...commonGrid, left: 90 },
            xAxis: {
              type: 'category',
              data: heatmapPeriods,
              ...axisStyle,
            },
            yAxis: {
              type: 'category',
              data: heatmapFeatures,
              ...axisStyle,
            },
            visualMap: {
              min: 0,
              max: 2,
              orient: 'horizontal',
              left: 'center',
              bottom: 0,
              inRange: { color: ['#f7efe2', '#d6b07c', '#8C1D18'] },
            },
            series: [
              {
                type: 'heatmap',
                data: data.heatmap.map((item) => [
                  heatmapPeriods.indexOf(item.period),
                  heatmapFeatures.indexOf(`${item.roleType}|${item.feature}`),
                  item.value,
                ]),
                label: { show: false },
              },
            ],
          }}
        />

        <ChartPanel
          title="行当演化时间线"
          subtitle="比较不同历史时期中各主类行当的出现频率。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            legend: { top: 0, textStyle: { color: '#6b6259' } },
            grid: commonGrid,
            xAxis: {
              type: 'category',
              data: [...new Set(data.timeline.map((item) => item.period))],
              ...axisStyle,
            },
            yAxis: { type: 'value', ...axisStyle },
            series: [...new Set(data.timeline.map((item) => item.roleType))].map((roleType) => ({
              name: roleType,
              type: 'line',
              smooth: true,
              data: [...new Set(data.timeline.map((item) => item.period))].map(
                (period) =>
                  data.timeline
                    .filter((item) => item.period === period && item.roleType === roleType)
                    .reduce((sum, item) => sum + item.value, 0),
              ),
            })),
          }}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <ChartPanel
          title="角色散点图"
          subtitle="横轴为行动强度，纵轴为情感强度，点大小代表出场频率。"
          option={scatterOption}
          height={380}
        />

        <Surface title="角色样本表" subtitle="用于验证原型中的行当推断、角色特征与证据绑定是否清晰。">
          <div className="max-h-[380px] overflow-auto rounded-2xl border border-stone-200">
            <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
              <thead className="bg-stone-50 text-stone-500">
                <tr>
                  <th className="px-4 py-3 font-medium">角色</th>
                  <th className="px-4 py-3 font-medium">身份</th>
                  <th className="px-4 py-3 font-medium">行当</th>
                  <th className="px-4 py-3 font-medium">置信度</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-200 bg-white/80">
                {data.characters.map((character) => (
                  <tr key={character.id}>
                    <td className="px-4 py-3 font-medium text-stone-900">{character.name}</td>
                    <td className="px-4 py-3 text-stone-600">{character.identity}</td>
                    <td className="px-4 py-3 text-stone-600">{character.roleSubtype}</td>
                    <td className="px-4 py-3 text-stone-600">{(character.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      </div>
    </div>
  )
}
