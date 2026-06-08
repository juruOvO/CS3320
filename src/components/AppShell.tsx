import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { apiClient } from '@/api/client'
import type { GlobalFilters } from '@/api/types'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value?: string
  options: Array<{ label: string; value: string }>
  onChange: (value: string) => void
}) {
  return (
    <label className="flex min-w-[150px] flex-col gap-2">
      <span className="text-xs uppercase tracking-[0.24em] text-stone-500">{label}</span>
      <select
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-2xl border border-amber-200 bg-white/90 px-4 py-3 text-sm text-stone-700 outline-none transition focus:border-[#8C1D18] focus:ring-2 focus:ring-[#8C1D18]/10"
      >
        <option value="">全部</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const { filters, resetFilters, setFilter, setFilters } = useFiltersStore()
  const { data } = useAsyncData(() => apiClient.getFilterOptions(filters), [filters])

  useEffect(() => {
    if (!data) return

    const invalidFilters: Partial<GlobalFilters> = {}
    if (filters.period && !data.periods.includes(filters.period)) invalidFilters.period = undefined
    if (filters.genre && !data.genres.includes(filters.genre)) invalidFilters.genre = undefined
    if (filters.playId && !data.plays.some((play) => play.id === filters.playId)) invalidFilters.playId = undefined
    if (filters.roleType && !data.roleTypes.includes(filters.roleType)) invalidFilters.roleType = undefined
    if (filters.theme && !data.themes.includes(filters.theme)) invalidFilters.theme = undefined
    if (filters.narrativePattern && !data.narrativePatterns.includes(filters.narrativePattern)) {
      invalidFilters.narrativePattern = undefined
    }

    if (Object.keys(invalidFilters).length > 0) {
      setFilters(invalidFilters)
    }
  }, [data, filters, setFilters])

  const activeFilters = [
    filters.period,
    filters.genre,
    filters.playId && data?.plays.find((play) => play.id === filters.playId)?.title,
    filters.roleType,
    filters.theme,
    filters.narrativePattern,
  ].filter(Boolean)

  return (
    <div className="min-h-screen bg-[#f4ecdd] text-stone-800">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top,_rgba(140,29,24,0.08),_transparent_38%),radial-gradient(circle_at_bottom_right,_rgba(58,107,111,0.08),_transparent_28%)]" />
      <div className="relative mx-auto min-h-screen max-w-[1760px] px-4 py-4 lg:px-6">
        <main className="relative">
          <header className="rounded-[32px] border border-amber-200/70 bg-[rgba(255,249,241,0.88)] p-5 shadow-[0_20px_60px_rgba(53,32,17,0.08)] backdrop-blur">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-[#8C1D18]">Single Page Linked Dashboard</p>
                <h2 className="mt-2 font-serif text-3xl text-stone-950">戏曲文本分析看板</h2>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {activeFilters.length > 0 ? (
                  activeFilters.map((item) => (
                    <span
                      key={String(item)}
                      className="rounded-full border border-[#8C1D18]/20 bg-[#8C1D18]/8 px-3 py-1 text-xs text-[#8C1D18]"
                    >
                      {item}
                    </span>
                  ))
                ) : (
                  <span className="rounded-full border border-stone-200 bg-white px-3 py-1 text-xs text-stone-500">
                    当前为全量样本视图
                  </span>
                )}
                <button
                  type="button"
                  onClick={resetFilters}
                  className="rounded-full border border-stone-300 px-4 py-2 text-xs text-stone-600 transition hover:border-[#8C1D18] hover:text-[#8C1D18]"
                >
                  重置筛选
                </button>
              </div>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-6">
              <SelectField
                label="时期"
                value={filters.period}
                options={data?.periods.map((value) => ({ label: value, value })) ?? []}
                onChange={(value) => setFilter('period', value || undefined)}
              />
              <SelectField
                label="剧类"
                value={filters.genre}
                options={data?.genres.map((value) => ({ label: value, value })) ?? []}
                onChange={(value) => setFilter('genre', value || undefined)}
              />
              <SelectField
                label="剧目"
                value={filters.playId}
                options={data?.plays.map((play) => ({ label: play.title, value: play.id })) ?? []}
                onChange={(value) => setFilter('playId', value || undefined)}
              />
              <SelectField
                label="行当"
                value={filters.roleType}
                options={data?.roleTypes.map((value) => ({ label: value, value })) ?? []}
                onChange={(value) => setFilter('roleType', value || undefined)}
              />
              <SelectField
                label="主题"
                value={filters.theme}
                options={data?.themes.map((value) => ({ label: value, value })) ?? []}
                onChange={(value) => setFilter('theme', value || undefined)}
              />
              <SelectField
                label="叙事模式"
                value={filters.narrativePattern}
                options={data?.narrativePatterns.map((value) => ({ label: value, value })) ?? []}
                onChange={(value) => setFilter('narrativePattern', value || undefined)}
              />
            </div>
          </header>

          <div className="py-6">{children}</div>
        </main>
      </div>
    </div>
  )
}
