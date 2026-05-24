import { Maximize2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { Surface } from './Surface'

export function ChartPanel({
  title,
  subtitle,
  option,
  height = 320,
}: {
  title: string
  subtitle?: string
  option: Record<string, unknown>
  height?: number
}) {
  const [isExpanded, setIsExpanded] = useState(false)

  useEffect(() => {
    if (!isExpanded) return undefined

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsExpanded(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isExpanded])

  return (
    <>
      <Surface
        title={title}
        subtitle={subtitle}
        className="overflow-hidden"
        action={
          <button
            type="button"
            onClick={() => setIsExpanded(true)}
            className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white/80 px-3 py-2 text-xs text-stone-600 transition hover:border-[#8C1D18] hover:text-[#8C1D18]"
            aria-label={`放大查看${title}`}
          >
            <Maximize2 className="h-3.5 w-3.5" />
            放大查看
          </button>
        }
      >
        <ReactECharts option={option} style={{ height }} opts={{ renderer: 'canvas' }} />
      </Surface>

      {isExpanded && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-[rgba(24,18,15,0.58)] p-4 backdrop-blur-sm"
          onClick={() => setIsExpanded(false)}
          role="dialog"
          aria-modal="true"
          aria-label={`${title}放大视图`}
        >
          <div
            className="w-full max-w-[1400px] rounded-[32px] border border-amber-200/70 bg-[rgba(255,250,242,0.98)] p-5 shadow-[0_30px_100px_rgba(20,12,8,0.28)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-semibold text-stone-950">{title}</h3>
                {subtitle && <p className="mt-2 text-sm leading-6 text-stone-500">{subtitle}</p>}
              </div>
              <button
                type="button"
                onClick={() => setIsExpanded(false)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-stone-200 bg-white text-stone-500 transition hover:border-[#8C1D18] hover:text-[#8C1D18]"
                aria-label="关闭放大视图"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <ReactECharts option={option} style={{ height: '72vh', minHeight: 540 }} opts={{ renderer: 'canvas' }} />
          </div>
        </div>
      )}
    </>
  )
}
