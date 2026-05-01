import { useState, useEffect, useCallback } from 'react'
import type { Transaction, Account, Category } from '../types'
import { getTransactions, getAccounts, getCategories, createTransaction } from '../api/client'
import CategoryBadge from '../components/CategoryBadge'
import TransactionBadge from '../components/TransactionBadge'
import MonthSelector from '../components/MonthSelector'
import { bankLabel } from '../banks'

const currentMonth = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const fmt = (n: number) => `RM ${Math.abs(n).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const formatDate = (dateStr: string) => {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-MY', { weekday: 'short', day: 'numeric', month: 'short' })
}

interface Filters {
  month: string
  search: string
  account_id?: number
  category_id?: number
  type?: string
  page: number
}

const PAGE_SIZE = 50

export default function Transactions() {
  const [filters, setFilters] = useState<Filters>({ month: currentMonth(), search: '', page: 1 })
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ account_id: 0, date: '', description: '', amount: '', type: 'debit', category_id: 0 })
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(() => {
    getTransactions({
      month: filters.month,
      search: filters.search || undefined,
      account_id: filters.account_id,
      category_id: filters.category_id,
      type: filters.type,
      page: filters.page,
    }).then(setTransactions).catch(() => setTransactions([]))
  }, [filters])

  useEffect(() => { load() }, [load])
  useEffect(() => { getAccounts().then(setAccounts); getCategories().then(setCategories) }, [])

  const grouped = transactions.reduce<Record<string, Transaction[]>>((acc, tx) => {
    ;(acc[tx.date] ??= []).push(tx)
    return acc
  }, {})
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a))

  const updateFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters(prev => ({ ...prev, [key]: value, page: key === 'page' ? (value as number) : 1 }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.account_id || !formData.date || !formData.description || !formData.amount) return
    setSubmitting(true)
    try {
      await createTransaction({
        account_id: formData.account_id,
        date: formData.date,
        description: formData.description,
        amount: parseFloat(formData.amount),
        type: formData.type,
        category_id: formData.category_id || undefined,
      })
      setFormData({ account_id: 0, date: '', description: '', amount: '', type: 'debit', category_id: 0 })
      setShowForm(false)
      load()
    } finally {
      setSubmitting(false)
    }
  }

  const amountClass = (tx: Transaction) => {
    if (tx.is_internal_transfer) return 'text-accent-deep'
    return tx.type === 'debit' ? 'text-negative' : 'text-positive'
  }

  const banks = [...new Set(accounts.map(a => a.bank))].sort()

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-end mb-8 pb-3.5 border-b-2 border-ink animate-reveal">
        <div className="flex items-baseline gap-3">
          <span className="text-[28px] font-extrabold tracking-tight">Transactions</span>
          <span className="font-label text-sm text-ink-whisper">{transactions.length} records</span>
        </div>
        <MonthSelector month={filters.month} onChange={(m) => updateFilter('month', m)} />
      </div>

      {/* Manual entry banner */}
      <div className="mb-6 animate-reveal animate-reveal-1">
        {!showForm ? (
          <button onClick={() => setShowForm(true)} className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2.5 rounded hover:bg-accent-deep transition-colors">
            + Add Transaction
          </button>
        ) : (
          <div className="ledger-card">
            <div className="ledger-card-header flex justify-between items-center">
              <span>New Transaction</span>
              <button onClick={() => setShowForm(false)} className="text-ink-light hover:text-ink text-sm">Cancel</button>
            </div>
            <form onSubmit={handleSubmit} className="p-5 grid grid-cols-[1fr_1fr_2fr_1fr_1fr_1fr_auto] gap-3 items-end">
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Account</label>
                <select value={formData.account_id} onChange={e => setFormData(prev => ({ ...prev, account_id: Number(e.target.value) }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
                  <option value={0}>Select...</option>
                  {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Date</label>
                <input type="date" value={formData.date} onChange={e => setFormData(prev => ({ ...prev, date: e.target.value }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" />
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Description</label>
                <input value={formData.description} onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" placeholder="What was this for?" />
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Amount</label>
                <input type="number" step="0.01" value={formData.amount} onChange={e => setFormData(prev => ({ ...prev, amount: e.target.value }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm font-number" placeholder="0.00" />
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Type</label>
                <select value={formData.type} onChange={e => setFormData(prev => ({ ...prev, type: e.target.value }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                </select>
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Category</label>
                <select value={formData.category_id} onChange={e => setFormData(prev => ({ ...prev, category_id: Number(e.target.value) }))}
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
                  <option value={0}>Auto</option>
                  {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <button type="submit" disabled={submitting}
                className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2 rounded hover:bg-accent-deep transition-colors disabled:opacity-50">
                {submitting ? 'Saving...' : 'Save'}
              </button>
            </form>
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div className="flex gap-3 mb-6 animate-reveal animate-reveal-2">
        <input value={filters.search} onChange={e => updateFilter('search', e.target.value)} placeholder="Search descriptions..."
          className="flex-1 border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" />
        <select value={filters.account_id ?? ''} onChange={e => updateFilter('account_id', e.target.value ? Number(e.target.value) : undefined)}
          className="border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
          <option value="">All Banks</option>
          {banks.map(b => <option key={b} value="">{bankLabel(b)}</option>)}
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select value={filters.category_id ?? ''} onChange={e => updateFilter('category_id', e.target.value ? Number(e.target.value) : undefined)}
          className="border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
          <option value="">All Categories</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filters.type ?? ''} onChange={e => updateFilter('type', e.target.value || undefined)}
          className="border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
          <option value="">All Types</option>
          <option value="debit">Debit</option>
          <option value="credit">Credit</option>
        </select>
      </div>

      {/* Transaction table */}
      <div className="ledger-card animate-reveal animate-reveal-3">
        {sortedDates.map(date => (
          <div key={date}>
            <div className="px-6 py-2.5 bg-cream-deep border-b border-rule">
              <span className="font-label text-xs uppercase tracking-[1.5px] text-ink-light">{formatDate(date)}</span>
            </div>
            {grouped[date].map(tx => (
              <div key={tx.id} className="grid grid-cols-[100px_1fr_160px_140px_120px] items-center px-6 py-3 border-b border-rule hover:bg-accent-ghost transition-colors">
                <span className="font-number text-sm text-ink-light">{tx.date}</span>
                <div className="flex items-center gap-1">
                  <span className="text-sm text-ink-medium truncate">{tx.description}</span>
                  {tx.is_recurring && <TransactionBadge type="recurring" />}
                  {tx.is_cash_withdrawal && <TransactionBadge type="cash" />}
                  {tx.is_internal_transfer && <TransactionBadge type="transfer" />}
                </div>
                <CategoryBadge transactionId={tx.id} categoryId={tx.category_id} categoryName={tx.category_name} onUpdate={load} />
                <span className="font-label text-xs text-ink-whisper truncate">{tx.account_name ?? bankLabel(tx.bank)}</span>
                <span className={`font-number text-[17px] text-right ${amountClass(tx)}`}>
                  {tx.type === 'debit' ? '-' : '+'}{fmt(tx.amount)}
                </span>
              </div>
            ))}
          </div>
        ))}
        {transactions.length === 0 && (
          <div className="px-6 py-12 text-center text-sm text-ink-whisper">No transactions found</div>
        )}
      </div>

      {/* Pagination */}
      {transactions.length > 0 && (
        <div className="flex justify-center gap-2 mt-6 animate-reveal">
          <button onClick={() => updateFilter('page', Math.max(1, filters.page - 1))} disabled={filters.page <= 1}
            className="border border-rule-strong rounded px-4 py-2 text-sm hover:border-accent hover:bg-accent-ghost transition-all disabled:opacity-30">
            Previous
          </button>
          <span className="font-number text-sm px-4 py-2 text-ink-light">Page {filters.page}</span>
          <button onClick={() => updateFilter('page', filters.page + 1)} disabled={transactions.length < PAGE_SIZE}
            className="border border-rule-strong rounded px-4 py-2 text-sm hover:border-accent hover:bg-accent-ghost transition-all disabled:opacity-30">
            Next
          </button>
        </div>
      )}
    </div>
  )
}
