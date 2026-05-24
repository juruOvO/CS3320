import { Surface } from './Surface'

export function EvidencePanel({
  title = '证据片段',
  items,
}: {
  title?: string
  items: Array<{ key: string; label: string; value: string }>
}) {
  return (
    <Surface title={title} subtitle="展示当前筛选视图下最具代表性的文本与推断依据。">
      <div className="space-y-3">
        {items.map((item) => (
          <article key={item.key} className="rounded-2xl border border-stone-200 bg-white/80 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#8C1D18]">{item.label}</p>
            <p className="mt-2 text-sm leading-6 text-stone-700">{item.value}</p>
          </article>
        ))}
      </div>
    </Surface>
  )
}
