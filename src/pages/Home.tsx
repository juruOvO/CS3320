import { Link } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function Home() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getOverview(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '总览数据为空'} />

  const periodGenreOption = {
    color: chartPalette,
    tooltip: { ...tooltipStyle, trigger: 'axis' },
    legend: { bottom: 0, textStyle: { color: '#6b6259' } },
    grid: commonGrid,
    xAxis: {
      type: 'category',
      ...axisStyle,
      data: [...new Set(data.periodGenreDistribution.map((item) => item.period))],
    },
    yAxis: { type: 'value', ...axisStyle },
    series: [...new Set(data.periodGenreDistribution.map((item) => item.genre))].map((genre) => ({
      name: genre,
      type: 'bar',
      stack: 'total',
      barMaxWidth: 42,
      data: [...new Set(data.periodGenreDistribution.map((item) => item.period))].map(
        (period) =>
          data.periodGenreDistribution
            .filter((item) => item.period === period && item.genre === genre)
            .reduce((sum, item) => sum + item.value, 0),
      ),
    })),
  }

  const roleOption = {
    color: chartPalette,
    tooltip: tooltipStyle,
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        label: { color: '#6b6259' },
        data: data.roleDistribution.map((item) => ({ name: item.roleType, value: item.value })),
      },
    ],
  }

  const themeOption = {
    color: chartPalette,
    tooltip: tooltipStyle,
    grid: commonGrid,
    xAxis: { type: 'value', ...axisStyle },
    yAxis: {
      type: 'category',
      ...axisStyle,
      data: data.topThemes.map((item) => item.theme),
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: data.topThemes.map((item) => item.value),
        label: { show: true, position: 'right', color: '#6b6259' },
      },
    ],
  }

  const patternOption = {
    color: ['#3A6B6F'],
    tooltip: tooltipStyle,
    grid: commonGrid,
    xAxis: {
      type: 'category',
      ...axisStyle,
      data: data.narrativePatterns.map((item) => item.pattern),
      axisLabel: { color: '#6b6259', interval: 0, rotate: 20 },
    },
    yAxis: { type: 'value', ...axisStyle },
    series: [{ type: 'bar', barMaxWidth: 34, data: data.narrativePatterns.map((item) => item.value) }],
  }

  return (
    <div>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <ChartPanel
          title="时期 × 剧类分布"
          subtitle="观察不同时期样本分布以及课程样本构成。"
          option={periodGenreOption}
          height={350}
        />
        <ChartPanel
          title="行当总体分布"
          subtitle="汇总当前样本中的主要行当与细分支。"
          option={roleOption}
          height={350}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel title="热门主题" subtitle="按权重汇总最常见的核心主题。" option={themeOption} />
        <ChartPanel title="叙事模式占比" subtitle="用于快速比较不同剧目采用的结构策略。" option={patternOption} />
      </div>

      <Surface className="mt-4" title="剧目清单" subtitle="点击进入单剧详情页，查看角色、主题与叙事的证据联动。">
        <div className="overflow-hidden rounded-2xl border border-stone-200">
          <table className="min-w-full divide-y divide-stone-200 text-left text-sm">
            <thead className="bg-stone-50 text-stone-500">
              <tr>
                <th className="px-4 py-3 font-medium">剧目</th>
                <th className="px-4 py-3 font-medium">时期</th>
                <th className="px-4 py-3 font-medium">剧类</th>
                <th className="px-4 py-3 font-medium">场次</th>
                <th className="px-4 py-3 font-medium">查看</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-200 bg-white/80">
              {data.playList.map((play) => (
                <tr key={play.id}>
                  <td className="px-4 py-3 font-medium text-stone-900">{play.title}</td>
                  <td className="px-4 py-3 text-stone-600">{play.period}</td>
                  <td className="px-4 py-3 text-stone-600">{play.genre}</td>
                  <td className="px-4 py-3 text-stone-600">{play.sceneCount}</td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/plays/${play.id}`}
                      className="rounded-full border border-[#8C1D18]/20 px-3 py-1 text-xs text-[#8C1D18] transition hover:bg-[#8C1D18] hover:text-white"
                    >
                      进入详情
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
    </div>
  )
}
