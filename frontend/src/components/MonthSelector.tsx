interface Props {
  month: string
  onChange: (month: string) => void
}

export default function MonthSelector({ month, onChange }: Props) {
  const [year, mo] = month.split('-').map(Number)
  const label = new Date(year, mo - 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })

  const prev = () => {
    const d = new Date(year, mo - 2)
    onChange(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }

  const next = () => {
    const d = new Date(year, mo)
    onChange(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }

  return (
    <div className="flex items-center gap-1">
      <button onClick={prev} className="w-8 h-8 border border-rule-strong rounded text-ink-light hover:border-accent hover:text-accent-deep hover:bg-accent-ghost transition-all flex items-center justify-center">{'\u2039'}</button>
      <span className="font-number text-xl px-4">{label}</span>
      <button onClick={next} className="w-8 h-8 border border-rule-strong rounded text-ink-light hover:border-accent hover:text-accent-deep hover:bg-accent-ghost transition-all flex items-center justify-center">{'\u203A'}</button>
    </div>
  )
}
