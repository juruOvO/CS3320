import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Surface({
  title,
  subtitle,
  action,
  className,
  children,
}: {
  title?: string
  subtitle?: string
  action?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section
      className={cn(
        'rounded-[28px] border border-amber-200/60 bg-[rgba(255,251,242,0.86)] p-5 shadow-[0_20px_60px_rgba(53,32,17,0.08)] backdrop-blur',
        className,
      )}
    >
      {(title || subtitle || action) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h3 className="text-lg font-semibold tracking-wide text-stone-900">{title}</h3>}
            {subtitle && <p className="mt-1 text-sm leading-6 text-stone-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function StatCard({
  label,
  value,
  detail,
}: {
  label: string
  value: string | number
  detail?: string
}) {
  return (
    <Surface className="min-h-[128px]">
      <p className="text-xs uppercase tracking-[0.25em] text-stone-500">{label}</p>
      <div className="mt-4 flex items-end gap-3">
        <span className="font-serif text-4xl text-stone-950">{value}</span>
      </div>
      {detail && <p className="mt-4 text-sm text-stone-500">{detail}</p>}
    </Surface>
  )
}

export function LoadingSurface() {
  return (
    <div className="grid min-h-[240px] place-items-center rounded-[28px] border border-amber-200/70 bg-white/70 p-6">
      <div className="flex items-center gap-3 text-sm text-stone-500">
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#8C1D18]" />
        正在生成可视分析视图...
      </div>
    </div>
  )
}

export function ErrorSurface({ message }: { message: string }) {
  return (
    <Surface title="加载失败" subtitle="请检查本地 Mock 数据或接口配置。">
      <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{message}</p>
    </Surface>
  )
}
