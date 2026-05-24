import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function RelationsPage() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getRelations(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '关系网络数据为空'} />

  const adjacencyLabels = [...new Set(data.adjacency.flatMap((item) => [item.source, item.target]))]

  return (
    <div>
      <PageIntro
        eyebrow="Relations"
        title="角色关系网络与不同剧类的结构特征"
        description="本页通过力导向网络、邻接矩阵、网络指标与关系演化时间轴，比较历史戏、家庭戏、公案戏等剧类的关系组织方式。"
      />

      <ChartPanel
        title="力导向角色关系网络"
        subtitle="节点大小代表中心性，节点颜色代表行当，边宽代表互动强度。"
        height={480}
        option={{
          color: chartPalette,
          tooltip: tooltipStyle,
          series: [
            {
              type: 'graph',
              layout: 'force',
              roam: true,
              draggable: true,
              force: { repulsion: 200, edgeLength: [90, 160] },
              label: { show: true, color: '#433b34' },
              lineStyle: { opacity: 0.7, width: 2, color: '#b38d68' },
              data: data.nodes.map((node) => ({
                ...node,
                symbolSize: node.size,
                category: node.roleType,
                itemStyle: {
                  color:
                    node.roleType === '旦'
                      ? '#8C1D18'
                      : node.roleType === '生'
                        ? '#3A6B6F'
                        : node.roleType === '净'
                          ? '#A67C52'
                          : '#C58A2F',
                },
              })),
              links: data.links.map((link) => ({
                source: link.source,
                target: link.target,
                value: link.weight,
                lineStyle: { width: Math.max(link.weight, 2) / 1.8 },
              })),
            },
          ],
        }}
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="关系邻接矩阵"
          subtitle="适合观察高密度关系的整体分布与局部团簇。"
          height={360}
          option={{
            tooltip: tooltipStyle,
            grid: { ...commonGrid, left: 90 },
            xAxis: { type: 'category', data: adjacencyLabels, ...axisStyle },
            yAxis: { type: 'category', data: adjacencyLabels, ...axisStyle },
            visualMap: {
              min: 0,
              max: 10,
              orient: 'horizontal',
              left: 'center',
              bottom: 0,
              inRange: { color: ['#f8efe1', '#d8b27f', '#8C1D18'] },
            },
            series: [
              {
                type: 'heatmap',
                data: data.adjacency.map((item) => [
                  adjacencyLabels.indexOf(item.source),
                  adjacencyLabels.indexOf(item.target),
                  item.value,
                ]),
              },
            ],
          }}
        />

        <ChartPanel
          title="剧类网络指标对比"
          subtitle="用雷达图比较密度、平均度、聚类系数、中心化与模块度。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            legend: { bottom: 0, textStyle: { color: '#6b6259' } },
            radar: {
              indicator: [
                { name: '密度', max: 1 },
                { name: '平均度', max: 2.5 },
                { name: '聚类系数', max: 1 },
                { name: '中心化', max: 1 },
                { name: '模块度', max: 1 },
              ],
              splitLine: { lineStyle: { color: '#eadbc3' } },
              axisLine: { lineStyle: { color: '#d6c2a2' } },
            },
            series: [
              {
                type: 'radar',
                data: data.metrics.map((metric) => ({
                  name: metric.genre,
                  value: [
                    metric.density,
                    metric.avgDegree,
                    metric.clustering,
                    metric.centralization,
                    metric.modularity,
                  ],
                })),
              },
            ],
          }}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <ChartPanel
          title="关系演化时间轴"
          subtitle="将关键场次与关系类型绑定，观察冲突、亲属、审判等关系如何随剧情变化。"
          height={340}
          option={{
            color: chartPalette,
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            legend: { bottom: 0, textStyle: { color: '#6b6259' } },
            grid: commonGrid,
            xAxis: {
              type: 'category',
              data: [...new Set(data.relationTrend.map((item) => item.scene))],
              ...axisStyle,
            },
            yAxis: { type: 'value', ...axisStyle },
            series: [...new Set(data.relationTrend.map((item) => item.relationType))].map((relationType) => ({
              name: relationType,
              type: 'line',
              smooth: true,
              data: [...new Set(data.relationTrend.map((item) => item.scene))].map(
                (scene) =>
                  data.relationTrend
                    .filter((item) => item.scene === scene && item.relationType === relationType)
                    .reduce((sum, item) => sum + item.value, 0),
              ),
            })),
          }}
        />

        <Surface title="结构观察" subtitle="用于课堂展示时快速口头说明不同剧类的关系网络差异。">
          <div className="space-y-3 text-sm leading-7 text-stone-600">
            <div className="rounded-2xl border border-stone-200 bg-white/80 p-4">
              <p className="font-medium text-stone-900">历史戏</p>
              <p className="mt-2">角色关系更中心化，通常围绕忠臣、权臣或君主形成“中心辐射型”结构。</p>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white/80 p-4">
              <p className="font-medium text-stone-900">家庭戏</p>
              <p className="mt-2">亲缘与婚姻关系更密，网络团簇感强，冲突多在家庭单元内部累积。</p>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white/80 p-4">
              <p className="font-medium text-stone-900">公案戏</p>
              <p className="mt-2">受害者、施害者与裁断者常形成链式或多层级结构，并在公堂阶段集中收束。</p>
            </div>
          </div>
        </Surface>
      </div>
    </div>
  )
}
