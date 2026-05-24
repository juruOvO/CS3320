import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function ThemesPage() {
  const { filters } = useFiltersStore()
  const { data, loading, error } = useAsyncData(() => apiClient.getThemes(filters), [filters])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '主题数据为空'} />

  return (
    <div>
      <PageIntro
        eyebrow="Themes"
        title="主题构成、组合方式与跨剧比较"
        description="本页从主题分类、主题共现和主题组合三个角度比较不同剧目之间的共性与差异，并观察代表性的组合模式。"
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="主题旭日图"
          subtitle="将核心主题组织为主题群组与细分主题两层结构。"
          height={380}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            series: [
              {
                type: 'sunburst',
                radius: [20, '92%'],
                sort: undefined,
                data: data.sunburst.children,
                label: { rotate: 'radial', color: '#4b423b' },
              },
            ],
          }}
        />

        <ChartPanel
          title="主题共现网络"
          subtitle="同剧中共同出现的主题会被连接起来，可观察稳定组合与语义邻近关系。"
          height={380}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            series: [
              {
                type: 'graph',
                layout: 'force',
                roam: true,
                force: { repulsion: 220, edgeLength: [60, 110] },
                label: { show: true, color: '#534942' },
                data: data.cooccurrenceNodes.map((node) => ({
                  ...node,
                  name: node.id,
                  symbolSize: Math.max(20, node.value * 2),
                })),
                links: data.cooccurrenceLinks.map((link) => ({
                  ...link,
                  lineStyle: { width: 1 + link.value },
                })),
              },
            ],
          }}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <ChartPanel
          title="不同剧类主题占比"
          subtitle="按剧类比较主题权重分布，便于总结各类剧目的典型主题偏向。"
          height={360}
          option={{
            color: chartPalette,
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            legend: { bottom: 0, textStyle: { color: '#6b6259' } },
            grid: commonGrid,
            xAxis: {
              type: 'category',
              data: [...new Set(data.genreDistribution.map((item) => item.genre))],
              ...axisStyle,
            },
            yAxis: { type: 'value', ...axisStyle },
            series: [...new Set(data.genreDistribution.map((item) => item.theme))].map((theme) => ({
              name: theme,
              type: 'bar',
              stack: 'theme',
              barMaxWidth: 36,
              data: [...new Set(data.genreDistribution.map((item) => item.genre))].map(
                (genre) =>
                  data.genreDistribution
                    .filter((item) => item.genre === genre && item.theme === theme)
                    .reduce((sum, item) => sum + item.value, 0),
              ),
            })),
          }}
        />

        <Surface title="主题组合模式" subtitle="用组合卡代替复杂的 UpSet 交互，便于原型阶段快速展示。">
          <div className="space-y-3">
            {data.combinations.map((item, index) => (
              <div key={`${item.combination.join('-')}-${index}`} className="rounded-2xl border border-stone-200 bg-white/80 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#8C1D18]">组合 {index + 1}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {item.combination.map((theme) => (
                    <span key={theme} className="rounded-full bg-stone-100 px-3 py-1 text-xs text-stone-600">
                      {theme}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Surface>
      </div>

      <Surface className="mt-4" title="剧目主题画像" subtitle="列出每部剧的高频主题，支持课堂答辩时快速对照说明。">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {data.playProfiles.map((profile) => (
            <div key={profile.playId} className="rounded-[24px] border border-stone-200 bg-white/80 p-4">
              <p className="font-medium text-stone-900">{profile.title}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {profile.topThemes.map((theme) => (
                  <span key={theme} className="rounded-full bg-[#8C1D18]/10 px-3 py-1 text-xs text-[#8C1D18]">
                    {theme}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Surface>
    </div>
  )
}
