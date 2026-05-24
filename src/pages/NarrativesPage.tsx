import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function NarrativesPage() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getNarratives(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '叙事结构数据为空'} />

  const scenes = [...new Set(data.tensionSeries.map((item) => item.scene))]

  return (
    <div>
      <PageIntro
        eyebrow="Narratives"
        title="叙事阶段、剧情起伏与结构模式"
        description="本页识别剧情关键阶段，刻画张力与节奏变化，并比较不同剧目在叙事模式上的差异。"
      />

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.35fr]">
        <Surface title="叙事阶段流程" subtitle="结合课程分析任务，将戏曲剧情阶段拆解为六个关键节点。">
          <div className="space-y-3">
            {data.stages.map((stage) => (
              <div key={stage.stage} className="rounded-2xl border border-stone-200 bg-white/80 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#8C1D18]">{stage.order + 1}</p>
                <p className="mt-2 font-medium text-stone-900">{stage.stage}</p>
                <p className="mt-1 text-sm leading-6 text-stone-600">{stage.description}</p>
              </div>
            ))}
          </div>
        </Surface>

        <ChartPanel
          title="剧情张力曲线"
          subtitle="以场次为横轴，同时比较冲突张力、动作强度与情感强度。"
          height={430}
          option={{
            color: ['#8C1D18', '#A67C52', '#3A6B6F'],
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            legend: { top: 0, textStyle: { color: '#6b6259' } },
            grid: commonGrid,
            xAxis: { type: 'category', data: scenes, ...axisStyle },
            yAxis: { type: 'value', ...axisStyle },
            series: [
              {
                name: '张力',
                type: 'line',
                smooth: true,
                data: scenes.map(
                  (scene) =>
                    data.tensionSeries
                      .filter((item) => item.scene === scene)
                      .reduce((sum, item) => sum + item.tension, 0) /
                    Math.max(data.tensionSeries.filter((item) => item.scene === scene).length, 1),
                ),
              },
              {
                name: '动作',
                type: 'line',
                smooth: true,
                data: scenes.map(
                  (scene) =>
                    data.tensionSeries
                      .filter((item) => item.scene === scene)
                      .reduce((sum, item) => sum + item.action, 0) /
                    Math.max(data.tensionSeries.filter((item) => item.scene === scene).length, 1),
                ),
              },
              {
                name: '情感',
                type: 'line',
                smooth: true,
                data: scenes.map(
                  (scene) =>
                    data.tensionSeries
                      .filter((item) => item.scene === scene)
                      .reduce((sum, item) => sum + item.emotion, 0) /
                    Math.max(data.tensionSeries.filter((item) => item.scene === scene).length, 1),
                ),
              },
            ],
          }}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="表演形式分布"
          subtitle="唱、念、做、打在不同阶段中的占比有助于理解节奏配置。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            legend: { bottom: 0, textStyle: { color: '#6b6259' } },
            grid: commonGrid,
            xAxis: {
              type: 'category',
              data: [...new Set(data.performanceDistribution.map((item) => item.stage))],
              ...axisStyle,
            },
            yAxis: { type: 'value', ...axisStyle },
            series: [...new Set(data.performanceDistribution.map((item) => item.form))].map((form) => ({
              name: form,
              type: 'bar',
              stack: 'forms',
              barMaxWidth: 36,
              data: [...new Set(data.performanceDistribution.map((item) => item.stage))].map(
                (stage) =>
                  data.performanceDistribution
                    .filter((item) => item.stage === stage && item.form === form)
                    .reduce((sum, item) => sum + item.value, 0),
              ),
            })),
          }}
        />

        <ChartPanel
          title="叙事模式聚类"
          subtitle="每个点是一部剧，位置近似表示结构模式相近。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            grid: commonGrid,
            xAxis: { type: 'value', name: '结构推进性', ...axisStyle },
            yAxis: { type: 'value', name: '情感抒情性', ...axisStyle },
            series: [
              {
                type: 'scatter',
                data: data.patternClusters.map((item) => [item.x, item.y, item.title, item.pattern]),
                symbolSize: 18,
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

      <Surface className="mt-4" title="关键转折点" subtitle="为每个剧目列出叙事转折或高潮节点，方便与文本证据对应。">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.turningPoints.map((point) => (
            <div key={`${point.playId}-${point.scene}-${point.label}`} className="rounded-[24px] border border-stone-200 bg-white/80 p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8C1D18]">{point.scene}</p>
              <p className="mt-2 font-medium text-stone-900">{point.label}</p>
              <p className="mt-2 text-sm leading-6 text-stone-600">{point.description}</p>
            </div>
          ))}
        </div>
      </Surface>
    </div>
  )
}
