import { useState, useEffect } from 'react'
import MonthSelector from '../components/MonthSelector'
import { getDashboard } from '../api/client'
import type { DashboardSummary } from '../types'

const currentMonth = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const fmt = (n: number) => `RM ${n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const BAR_COLORS = ['var(--color-accent-deep)', 'var(--color-accent)', '#9eb8a8', '#c4a97a', '#b0988a', 'var(--color-ink-whisper)']

export default function Dashboard() {
  const [month, setMonth] = useState(currentMonth())
  const [data, setData] = useState<DashboardSummary | null>(null)

  useEffect(() => { getDashboard(month).then(setData).catch(() => setData(null)) }, [month])

  if (!data) return <div className="animate-pulse text-ink-light p-8">Loading...</div>

  const maxCatAmount = data.categories.length > 0 ? data.categories[0].amount : 1

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-end mb-10 pb-3.5 border-b-2 border-ink animate-reveal">
        <span className="text-[28px] font-extrabold tracking-tight">Dashboard</span>
        <MonthSelector month={month} onChange={setMonth} />
      </div>

      {/* Headlines */}
      <div className="grid grid-cols-3 gap-0 mb-9 animate-reveal animate-reveal-1">
        <div className="py-6">
          <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Income</div>
          <div className="font-number text-[40px] leading-none tracking-tight text-positive">{fmt(data.total_income)}</div>
        </div>
        <div className="py-6 pl-8 relative">
          <div className="absolute left-0 top-4 bottom-4 w-px bg-rule-strong" />
          <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Spending</div>
          <div className="font-number text-[40px] leading-none tracking-tight text-negative">{fmt(data.total_spending)}</div>
        </div>
        <div className="py-6 pl-8 relative">
          <div className="absolute left-0 top-4 bottom-4 w-px bg-rule-strong" />
          <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Savings</div>
          <div className="font-number text-[40px] leading-none tracking-tight text-accent-deep">{fmt(data.savings)}</div>
          <div className="text-sm text-ink-light mt-2.5"><em className="font-number text-ink-medium">{data.savings_pct.toFixed(1)}%</em> of income</div>
        </div>
      </div>

      {/* Budget ruler */}
      {data.budget_target && (
        <div className="mb-9 animate-reveal animate-reveal-2">
          <div className="flex justify-between items-baseline mb-3">
            <span className="text-sm font-bold text-ink-medium uppercase tracking-wide">Monthly Budget</span>
            <span className="font-number text-lg">{fmt(data.total_spending)} <span className="text-ink-whisper text-sm" style={{ fontFamily: 'var(--font-display)' }}>of</span> {fmt(data.budget_target)}</span>
          </div>
          <div className="relative h-7 bg-cream-deep border border-rule rounded-sm overflow-hidden">
            <div className="absolute top-0 left-0 h-full bg-accent rounded-sm" style={{ width: `${Math.min(data.budget_used_pct ?? 0, 100)}%`, borderRight: '2px solid var(--color-accent-deep)' }} />
          </div>
          <div className="flex justify-between mt-2.5">
            <span className="text-sm font-semibold text-positive">{fmt(Math.max(data.budget_target - data.total_spending, 0))} remaining</span>
            <span className="font-label text-sm text-ink-light">{data.budget_used_pct?.toFixed(1)}%</span>
          </div>
        </div>
      )}

      {/* Two columns */}
      <div className="grid grid-cols-[3fr_2fr] gap-6 animate-reveal animate-reveal-3">
        {/* Category ledger */}
        <div className="ledger-card">
          <div className="ledger-card-header flex justify-between items-baseline">
            <span>Spending by Category</span>
          </div>
          <div>
            {data.categories.map((cat, i) => (
              <div key={cat.category_id} className="grid grid-cols-[32px_1fr_120px_90px] items-center px-6 py-3.5 border-b border-rule last:border-b-0 hover:bg-accent-ghost transition-colors">
                <span className="font-label text-xs text-ink-whisper">{String(i + 1).padStart(2, '0')}</span>
                <span className="text-sm font-semibold text-ink-medium">{cat.category_name}</span>
                <div className="px-3"><div className="h-2 bg-cream-deep rounded-sm overflow-hidden"><div className="h-full rounded-sm" style={{ width: `${(cat.amount / maxCatAmount) * 100}%`, background: BAR_COLORS[Math.min(i, BAR_COLORS.length - 1)] }} /></div></div>
                <span className="font-number text-[17px] text-right">{fmt(cat.amount)}</span>
              </div>
            ))}
            {data.categories.length === 0 && <div className="px-6 py-8 text-sm text-ink-whisper text-center">No spending data</div>}
          </div>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-5">
          {/* Cash tracker */}
          <div className="ledger-card">
            <div className="ledger-card-header flex justify-between items-center">
              <span>Cash Tracker</span>
            </div>
            <div className="p-5">
              <div className="flex justify-between py-2.5"><span className="text-sm text-ink-light">ATM Withdrawn</span><span className="font-number text-[17px] text-negative">{fmt(data.cash_withdrawn)}</span></div>
              <div className="flex justify-between py-2.5 border-t border-rule"><span className="text-sm text-ink-light">Cash Logged</span><span className="font-number text-[17px] text-positive">{fmt(data.cash_logged)}</span></div>
              <div className="border-t border-dashed border-accent my-1" />
              <div className="flex justify-between py-2.5"><span className="text-sm text-ink-light">Untracked</span><span className="font-number text-[17px] text-amber font-semibold">{fmt(data.cash_untracked)}</span></div>
            </div>
          </div>

          {/* Transfers */}
          <div className="ledger-card">
            <div className="ledger-card-header">Internal Transfers</div>
            <div className="p-5">
              {data.internal_transfers.map((t, i) => (
                <div key={i} className={`flex justify-between py-2.5 text-sm ${i > 0 ? 'border-t border-rule' : ''}`}>
                  <span className="text-ink-light">{t.from_account} <span className="font-label text-xs text-accent-deep mx-1">{'\u2192'}</span> {t.to_account}</span>
                  <span className="font-number text-[15px]">{fmt(t.amount)}</span>
                </div>
              ))}
              {data.internal_transfers.length === 0 && <div className="text-sm text-ink-whisper">No internal transfers</div>}
            </div>
            <div className="px-5 py-3 border-t border-rule font-label text-xs text-ink-whisper">// excluded from totals</div>
          </div>
        </div>
      </div>
    </div>
  )
}
