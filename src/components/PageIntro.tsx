export function PageIntro({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="mb-6">
      <p className="text-xs uppercase tracking-[0.28em] text-[#8C1D18]">{eyebrow}</p>
      <h2 className="mt-2 font-serif text-3xl text-stone-950">{title}</h2>
      <p className="mt-3 max-w-4xl text-sm leading-7 text-stone-600">{description}</p>
    </div>
  )
}
