import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function AssociationsPage() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getAssociations(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '关联分析数据为空'} />

  const relationFeatures = [...new Set(data.matrix.map((item) => item.relationFeature))]
  const targetFeatures = [...new Set(data.matrix.map((item) => item.targetFeature))]

  return (
    <div>
      <PageIntro
        eyebrow="Associations"
        title="角色关系、主题结构与叙事方式的关联机制"
        description="本页将三类分析结果放在同一个结构中观察，寻找稳定的模式链条，例如某类关系网络如何推动特定主题并进一步塑造叙事策略。"
      />

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <ChartPanel
          title="关系类型 → 主题 → 叙事模式"
          subtitle="三段式桑基图用于展示综合结构中的主要流向。"
          height={420}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            series: [
              {
                type: 'sankey',
                top: 20,
                bottom: 12,
                left: 18,
                right: 18,
                nodeGap: 14,
                label: { color: '#564b44', fontSize: 11 },
                data: data.sankeyNodes,
                links: data.sankeyLinks,
                lineStyle: { color: 'gradient', opacity: 0.42, curveness: 0.45 },
              },
            ],
          }}
        />

        <Surface title="规则发现" subtitle="将关联关系总结为便于答辩表达的规则卡片。">
          <div className="space-y-3">
            {data.rules.map((rule) => (
              <div key={rule.id} className="rounded-[24px] border border-stone-200 bg-white/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-stone-900">{rule.title}</p>
                  <span className="rounded-full bg-[#8C1D18]/10 px-3 py-1 text-xs text-[#8C1D18]">
                    {(rule.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="mt-3 text-sm leading-6 text-stone-600">{rule.description}</p>
                <p className="mt-3 text-xs text-stone-500">样本：{rule.samples.join('、')}</p>
              </div>
            ))}
          </div>
        </Surface>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="关联矩阵热力图"
          subtitle="同时观察关系结构特征与主题/叙事指标的配对强度。"
          height={360}
          option={{
            tooltip: tooltipStyle,
            grid: { ...commonGrid, left: 100 },
            xAxis: { type: 'category', data: targetFeatures, ...axisStyle },
            yAxis: { type: 'category', data: relationFeatures, ...axisStyle },
            visualMap: {
              min: 0,
              max: 2,
              orient: 'horizontal',
              left: 'center',
              bottom: 0,
              inRange: { color: ['#f8efe1', '#d5ac76', '#8C1D18'] },
            },
            series: [
              {
                type: 'heatmap',
                data: data.matrix.map((item) => [
                  targetFeatures.indexOf(item.targetFeature),
                  relationFeatures.indexOf(item.relationFeature),
                  item.value,
                ]),
              },
            ],
          }}
        />

        <ChartPanel
          title="剧目结构聚类"
          subtitle="每个点是一部剧，可看出不同剧类在综合结构上的分布。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            grid: commonGrid,
            xAxis: { type: 'value', name: '关系复杂度', ...axisStyle },
            yAxis: { type: 'value', name: '主题-叙事耦合度', ...axisStyle },
            series: [
              {
                type: 'scatter',
                symbolSize: 18,
                data: data.clusters.map((item) => [item.x, item.y, item.title, item.pattern]),
                label: {
                  show: true,
                  formatter: (params: { data: unknown[] }) => String(params.data[2]),
                  position: 'top',
                  color: '#6b6259',
                },
              },
            ],
          }}
        />
      </div>
    </div>
  )
}
