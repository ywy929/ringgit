const styles: Record<string, string> = {
  recurring: 'bg-accent-wash text-accent-deep',
  cash: 'bg-amber text-white',
  transfer: 'bg-cream-deep text-ink-light border border-rule',
}

export default function TransactionBadge({ type }: { type: 'recurring' | 'cash' | 'transfer' }) {
  return (
    <span className={`font-label text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded-sm ml-2 inline-block ${styles[type]}`}>
      {type}
    </span>
  )
}
