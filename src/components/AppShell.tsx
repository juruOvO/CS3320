import { LayoutDashboard, Link2, Network, ScrollText, Shapes, Theater, UsersRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFiltersStore } from '@/store/useFiltersStore'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: '总览', icon: LayoutDashboard },
  { to: '/roles', label: '角色与行当', icon: UsersRound },
  { to: '/relations', label: '关系网络', icon: Network },
  { to: '/themes', label: '主题分析', icon: Theater },
  { to: '/narratives', label: '叙事结构', icon: ScrollText },
  { to: '/associations', label: '关联分析', icon: Link2 },
]

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
  const location = useLocation()
  const { filters, resetFilters, setFilter } = useFiltersStore()
  const { data } = useAsyncData(() => apiClient.getFilterOptions(), [])

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
      <div className="relative mx-auto flex min-h-screen max-w-[1720px] gap-6 px-4 py-4 lg:px-6">
        <aside className="sticky top-4 hidden h-[calc(100vh-2rem)] w-[260px] flex-col justify-between rounded-[32px] border border-amber-200/70 bg-[rgba(39,28,22,0.94)] p-5 text-stone-100 shadow-[0_20px_60px_rgba(30,18,13,0.35)] lg:flex">
          <div>
            <div className="flex items-center gap-3">
              <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#8C1D18] text-white">
                <Shapes className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-lg font-semibold tracking-wide">戏曲剧本多维分析平台</h1>
              </div>
            </div>
            <nav className="mt-8 space-y-2">
              {navItems.map((item) => {
                const Icon = item.icon
                const active = location.pathname === item.to
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={cn(
                      'flex items-center gap-3 rounded-2xl px-4 py-3 text-sm transition',
                      active
                        ? 'bg-white text-stone-900 shadow-lg'
                        : 'text-stone-300 hover:bg-white/10 hover:text-white',
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </nav>
          </div>
          <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.24em] text-amber-100/60">原型说明</p>
            <p className="mt-3 text-sm leading-6 text-stone-300">默认使用mock数据驱动，不代表最终结果</p>
          </div>
        </aside>

        <main className="relative flex-1">
          <header className="rounded-[32px] border border-amber-200/70 bg-[rgba(255,249,241,0.88)] p-5 shadow-[0_20px_60px_rgba(53,32,17,0.08)] backdrop-blur">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-[#8C1D18]">Prototype / Frontend Only</p>
                <h2 className="mt-2 font-serif text-3xl text-stone-950">戏曲文本可视化系统</h2>
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
