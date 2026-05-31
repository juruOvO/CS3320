import { Link, useParams } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { ChartPanel } from '@/components/ChartPanel'
import { EvidencePanel } from '@/components/EvidencePanel'
import { PageIntro } from '@/components/PageIntro'
import { ErrorSurface, LoadingSurface, Surface } from '@/components/Surface'
import { useAsyncData } from '@/hooks/useAsyncData'
import { axisStyle, chartPalette, commonGrid, tooltipStyle } from '@/utils/chartTheme'

export default function PlayDetailPage() {
  const { playId = 'zuoloushaxi' } = useParams()
  const { data, loading, error } = useAsyncData(() => apiClient.getPlayDetail(playId), [playId])

  if (loading) return <LoadingSurface />
  if (error || !data) return <ErrorSurface message={error ?? '剧目详情为空'} />

  return (
    <div>
      <PageIntro
        eyebrow="Play Detail"
        title={`${data.play.title} · 单剧结构深读`}
        description={data.play.summary}
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-white px-4 py-2 text-sm text-stone-600 shadow-sm">{data.play.period}</span>
        <span className="rounded-full bg-white px-4 py-2 text-sm text-stone-600 shadow-sm">{data.play.genre}</span>
        <span className="rounded-full bg-white px-4 py-2 text-sm text-stone-600 shadow-sm">{data.play.authorEra}</span>
        <span className="rounded-full bg-white px-4 py-2 text-sm text-stone-600 shadow-sm">{data.play.sceneCount} 场</span>
        <Link
          to="/"
          className="rounded-full border border-[#8C1D18]/20 px-4 py-2 text-sm text-[#8C1D18] transition hover:bg-[#8C1D18] hover:text-white"
        >
          返回分析中枢
        </Link>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr]">
        <Surface title="角色清单" subtitle="用于单剧深读时核对角色、行当和关系提示。">
          <div className="grid gap-3 md:grid-cols-2">
            {data.characters.map((character) => (
              <div key={character.id} className="rounded-[24px] border border-stone-200 bg-white/80 p-4">
                <p className="font-medium text-stone-900">{character.name}</p>
                <p className="mt-1 text-sm text-stone-500">{character.identity}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full bg-[#8C1D18]/10 px-3 py-1 text-xs text-[#8C1D18]">{character.roleSubtype}</span>
                  <span className="rounded-full bg-stone-100 px-3 py-1 text-xs text-stone-600">{character.relationHint}</span>
                </div>
              </div>
            ))}
          </div>
        </Surface>

        <EvidencePanel
          title="单剧证据片段"
          items={data.evidence.map((item) => ({
            key: item.id,
            label: `${item.type}${item.speaker ? ` · ${item.speaker}` : ''}`,
            value: item.text,
          }))}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="主题权重"
          subtitle="展示该剧最核心的主题构成。"
          height={320}
          option={{
            color: chartPalette,
            tooltip: tooltipStyle,
            grid: commonGrid,
            xAxis: { type: 'value', ...axisStyle },
            yAxis: { type: 'category', data: data.themes.map((item) => item.theme), ...axisStyle },
            series: [{ type: 'bar', barWidth: 18, data: data.themes.map((item) => item.weight) }],
          }}
        />

        <ChartPanel
          title="叙事张力"
          subtitle="单剧内部的起伏节奏可以在这里快速查看。"
          height={320}
          option={{
            color: ['#8C1D18'],
            tooltip: { ...tooltipStyle, trigger: 'axis' },
            grid: commonGrid,
            xAxis: { type: 'category', data: data.narrative.map((item) => item.scene), ...axisStyle },
            yAxis: { type: 'value', ...axisStyle },
            series: [{ type: 'line', smooth: true, areaStyle: { opacity: 0.18 }, data: data.narrative.map((item) => item.tension) }],
          }}
        />
      </div>
    </div>
  )
}
