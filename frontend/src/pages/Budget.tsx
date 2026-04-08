import { useState, useEffect } from 'react'
import type { Budget as BudgetType, DashboardSummary } from '../types'
import { getBudget, setBudget, getDashboard } from '../api/client'
import MonthSelector from '../components/MonthSelector'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, Legend, ResponsiveContainer } from 'recharts'

const currentMonth = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const fmt = (n: number) => `RM ${n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const getMonthLabel = (month: string) => {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1).toLocaleDateString('en-US', { month: 'short' })
}

const getPrevMonths = (month: string, count: number): string[] => {
  const [y, m] = month.split('-').map(Number)
  const months: string[] = []
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(y, m - 1 - i)
    months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  return months
}

interface TrendData {
  month: string
  label: string
  spending: number
  savings: number
}

export default function Budget() {
  const [month, setMonth] = useState(currentMonth())
  const [budget, setBudgetState] = useState<BudgetType | null>(null)
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [targetInput, setTargetInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [trendData, setTrendData] = useState<TrendData[]>([])

  useEffect(() => {
    getBudget(month).then(b => {
      setBudgetState(b)
      setTargetInput(b ? String(b.target_amount) : '')
    }).catch(() => setBudgetState(null))
    getDashboard(month).then(setDashboard).catch(() => setDashboard(null))
  }, [month])

  useEffect(() => {
    const months = getPrevMonths(month, 6)
    Promise.all(months.map(m => getDashboard(m).then(d => ({
      month: m,
      label: getMonthLabel(m),
      spending: d.total_spending,
      savings: d.savings,
    })).catch(() => ({
      month: m,
      label: getMonthLabel(m),
      spending: 0,
      savings: 0,
    })))).then(setTrendData)
  }, [month])

  const handleSave = async () => {
    const target = parseFloat(targetInput)
    if (isNaN(target) || target <= 0) return
    setSaving(true)
    try {
      const b = await setBudget(month, target)
      setBudgetState(b)
    } finally {
      setSaving(false)
    }
  }

  const spent = dashboard?.total_spending ?? 0
  const target = budget?.target_amount ?? 0
  const remaining = Math.max(target - spent, 0)
  const usedPct = target > 0 ? (spent / target) * 100 : 0

  const avgSavings = trendData.length > 0 ? trendData.reduce((s, d) => s + d.savings, 0) / trendData.length : 0
  const bestMonth = trendData.length > 0 ? trendData.reduce((best, d) => d.savings > best.savings ? d : best, trendData[0]) : null
  const worstMonth = trendData.length > 0 ? trendData.reduce((worst, d) => d.savings < worst.savings ? d : worst, trendData[0]) : null
  const totalSaved = trendData.reduce((s, d) => s + d.savings, 0)

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-end mb-10 pb-3.5 border-b-2 border-ink animate-reveal">
        <span className="text-[28px] font-extrabold tracking-tight">Budget</span>
        <MonthSelector month={month} onChange={setMonth} />
      </div>

      {/* Budget setting card */}
      <div className="ledger-card mb-8 animate-reveal animate-reveal-1">
        <div className="ledger-card-header">Budget Target</div>
        <div className="p-5 flex items-center gap-4">
          <span className="font-label text-sm text-ink-light">RM</span>
          <input type="number" step="100" value={targetInput} onChange={e => setTargetInput(e.target.value)} placeholder="Enter monthly budget..."
            className="flex-1 border border-rule rounded px-3 py-2 bg-paper text-ink font-number text-lg focus:border-accent focus:outline-none" />
          <button onClick={handleSave} disabled={saving}
            className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-6 py-2.5 rounded hover:bg-accent-deep transition-colors disabled:opacity-50">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Gauges */}
      {target > 0 && (
        <div className="grid grid-cols-3 gap-6 mb-9 animate-reveal animate-reveal-2">
          <div className="ledger-card p-6 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Spent</div>
            <div className="font-number text-[32px] leading-none tracking-tight text-negative">{fmt(spent)}</div>
          </div>
          <div className="ledger-card p-6 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Remaining</div>
            <div className={`font-number text-[32px] leading-none tracking-tight ${remaining > 0 ? 'text-positive' : 'text-negative'}`}>{fmt(remaining)}</div>
          </div>
          <div className="ledger-card p-6 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-2">Used</div>
            <div className={`font-number text-[32px] leading-none tracking-tight ${usedPct > 100 ? 'text-negative' : 'text-accent-deep'}`}>{usedPct.toFixed(1)}%</div>
          </div>
        </div>
      )}

      {/* Savings trend chart */}
      <div className="ledger-card mb-8 animate-reveal animate-reveal-3">
        <div className="ledger-card-header">6-Month Savings Trend</div>
        <div className="p-5">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={trendData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-rule)" />
              <XAxis dataKey="label" tick={{ fontSize: 12, fontFamily: 'var(--font-number)' }} />
              <YAxis tick={{ fontSize: 12, fontFamily: 'var(--font-number)' }} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip formatter={(value) => fmt(Number(value))} />
              <Legend />
              {target > 0 && <ReferenceLine y={target} stroke="var(--color-accent-deep)" strokeDasharray="6 3" label={{ value: 'Budget', position: 'right', fontSize: 11 }} />}
              <Bar dataKey="spending" name="Spending" fill="var(--color-negative)" stackId="a" radius={[0, 0, 0, 0]} />
              <Bar dataKey="savings" name="Savings" fill="var(--color-accent-deep)" stackId="a" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Summary stats */}
      {trendData.length > 0 && (
        <div className="grid grid-cols-4 gap-4 animate-reveal animate-reveal-4">
          <div className="ledger-card p-5 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-1.5">Avg Savings</div>
            <div className="font-number text-lg">{fmt(avgSavings)}</div>
          </div>
          <div className="ledger-card p-5 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-1.5">Best Month</div>
            <div className="font-number text-lg text-positive">{bestMonth?.label}</div>
            <div className="font-number text-sm text-ink-light">{bestMonth ? fmt(bestMonth.savings) : '-'}</div>
          </div>
          <div className="ledger-card p-5 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-1.5">Worst Month</div>
            <div className="font-number text-lg text-negative">{worstMonth?.label}</div>
            <div className="font-number text-sm text-ink-light">{worstMonth ? fmt(worstMonth.savings) : '-'}</div>
          </div>
          <div className="ledger-card p-5 text-center">
            <div className="font-label text-xs uppercase tracking-[1.5px] text-ink-light mb-1.5">Total Saved</div>
            <div className="font-number text-lg text-accent-deep">{fmt(totalSaved)}</div>
          </div>
        </div>
      )}
    </div>
  )
}
