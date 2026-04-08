import { useState, useEffect } from 'react'
import type { Category } from '../types'
import { getCategories, updateTransactionCategory } from '../api/client'

interface Props {
  transactionId: number
  categoryId: number | null
  categoryName: string | null
  onUpdate?: () => void
}

export default function CategoryBadge({ transactionId, categoryId, categoryName, onUpdate }: Props) {
  const [editing, setEditing] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])

  useEffect(() => {
    if (editing && categories.length === 0) {
      getCategories().then(setCategories)
    }
  }, [editing])

  const handleSelect = async (catId: number) => {
    await updateTransactionCategory(transactionId, catId)
    setEditing(false)
    onUpdate?.()
  }

  const isUncategorized = categoryName === 'Uncategorized'
  const isTransfer = categoryName === 'Internal Transfer'

  if (editing) {
    return (
      <select autoFocus className="text-sm border border-accent rounded px-2 py-1 bg-paper" style={{ fontFamily: 'var(--font-display)' }}
        value={categoryId ?? ''} onChange={(e) => handleSelect(Number(e.target.value))} onBlur={() => setEditing(false)}>
        {categories.map(c => (<option key={c.id} value={c.id}>{c.name}</option>))}
      </select>
    )
  }

  return (
    <button onClick={() => !isTransfer && setEditing(true)} disabled={isTransfer}
      className={`text-sm font-medium px-2.5 py-1 rounded border transition-all ${isUncategorized ? 'border-dotted border-rule-strong text-ink-whisper hover:border-accent hover:bg-accent-ghost' : isTransfer ? 'border-rule text-ink-whisper cursor-default' : 'border-dashed border-rule-strong text-ink-medium hover:border-accent hover:bg-accent-ghost hover:text-accent-ink'}`}>
      {categoryName ?? 'Uncategorized'}
    </button>
  )
}
