import { useState, useEffect } from 'react'
import type { Account, Category, KeywordMapping, EmailAccount } from '../types'
import {
  getEmailAccounts, deleteEmailAccount,
  getAccounts, createAccount, deleteAccount,
  getCategories, createCategory,
  getKeywordMappings, deleteKeywordMapping,
} from '../api/client'

const BANKS = ['Maybank', 'CIMB', 'Public Bank', 'Hong Leong', 'RHB', 'AmBank', 'AEON Credit', "Touch 'n Go"]
const ACCOUNT_TYPES = ['savings', 'current', 'credit_card', 'ewallet']

export default function Settings() {
  const [emails, setEmails] = useState<EmailAccount[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [mappings, setMappings] = useState<KeywordMapping[]>([])

  const [newAccount, setNewAccount] = useState({ name: '', bank: BANKS[0], type: ACCOUNT_TYPES[0] })
  const [newCategory, setNewCategory] = useState('')
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const connected = params.get('connected')
    if (connected) {
      setToast(`Connected ${connected}`)
      window.history.replaceState({}, '', window.location.pathname)
      const t = setTimeout(() => setToast(null), 4000)
      return () => clearTimeout(t)
    }
  }, [])

  const reload = () => {
    getEmailAccounts().then(setEmails).catch(() => setEmails([]))
    getAccounts().then(setAccounts).catch(() => setAccounts([]))
    getCategories().then(setCategories).catch(() => setCategories([]))
    getKeywordMappings().then(setMappings).catch(() => setMappings([]))
  }

  useEffect(() => { reload() }, [])

  const handleDisconnectEmail = async (id: number) => {
    await deleteEmailAccount(id)
    setEmails(prev => prev.filter(e => e.id !== id))
  }

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newAccount.name.trim()) return
    await createAccount(newAccount)
    setNewAccount({ name: '', bank: BANKS[0], type: ACCOUNT_TYPES[0] })
    getAccounts().then(setAccounts)
  }

  const handleDeleteAccount = async (id: number) => {
    await deleteAccount(id)
    setAccounts(prev => prev.filter(a => a.id !== id))
  }

  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newCategory.trim()) return
    await createCategory(newCategory.trim())
    setNewCategory('')
    getCategories().then(setCategories)
  }

  const handleDeleteMapping = async (id: number) => {
    await deleteKeywordMapping(id)
    setMappings(prev => prev.filter(m => m.id !== id))
  }

  return (
    <div>
      {toast && (
        <div className="fixed top-6 right-6 bg-accent-ink text-white px-4 py-3 rounded shadow-lg z-50 text-sm font-semibold">
          {toast}
        </div>
      )}
      {/* Header */}
      <div className="flex justify-between items-end mb-10 pb-3.5 border-b-2 border-ink animate-reveal">
        <span className="text-[28px] font-extrabold tracking-tight">Settings</span>
      </div>

      <div className="space-y-8">
        {/* Gmail Accounts */}
        <div className="ledger-card animate-reveal animate-reveal-1">
          <div className="ledger-card-header">Gmail Accounts</div>
          <div className="p-5">
            {emails.length === 0 && <div className="text-sm text-ink-whisper">No email accounts connected</div>}
            {emails.map(em => (
              <div key={em.id} className="flex items-center justify-between py-3 border-b border-rule last:border-b-0">
                <div>
                  <span className="text-sm font-semibold text-ink">{em.email}</span>
                  <span className="font-label text-xs text-ink-whisper ml-3">
                    {em.last_fetched_at ? `Last fetched: ${new Date(em.last_fetched_at).toLocaleDateString('en-MY')}` : 'Never fetched'}
                  </span>
                </div>
                <button onClick={() => handleDisconnectEmail(em.id)}
                  className="text-xs font-bold uppercase tracking-wide text-negative hover:bg-negative hover:text-white px-3 py-1.5 rounded border border-negative transition-colors">
                  Disconnect
                </button>
              </div>
            ))}
            <div className="pt-4 mt-2 border-t border-rule">
              <a href="http://localhost:8000/api/oauth/start"
                className="inline-block bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2 rounded hover:bg-accent-deep transition-colors">
                Connect Gmail
              </a>
              <span className="ml-3 text-xs text-ink-whisper">Opens Google consent — you can connect multiple accounts.</span>
            </div>
          </div>
        </div>

        {/* Bank Accounts */}
        <div className="ledger-card animate-reveal animate-reveal-2">
          <div className="ledger-card-header">Bank Accounts</div>
          <div className="p-5">
            {accounts.map(acc => (
              <div key={acc.id} className="flex items-center justify-between py-3 border-b border-rule last:border-b-0">
                <div className="flex items-center gap-4">
                  <span className="text-sm font-semibold text-ink">{acc.name}</span>
                  <span className="font-label text-xs text-ink-light">{acc.bank}</span>
                  <span className="font-label text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded-sm bg-cream-deep text-ink-light border border-rule">{acc.type}</span>
                </div>
                <button onClick={() => handleDeleteAccount(acc.id)}
                  className="text-xs font-bold uppercase tracking-wide text-negative hover:bg-negative hover:text-white px-3 py-1.5 rounded border border-negative transition-colors">
                  Delete
                </button>
              </div>
            ))}
            {accounts.length === 0 && <div className="text-sm text-ink-whisper mb-4">No accounts added</div>}

            <form onSubmit={handleAddAccount} className="flex gap-3 items-end mt-4 pt-4 border-t border-rule">
              <div className="flex-1">
                <label className="font-label text-xs text-ink-light block mb-1">Name</label>
                <input value={newAccount.name} onChange={e => setNewAccount(prev => ({ ...prev, name: e.target.value }))} placeholder="Account name"
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" />
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Bank</label>
                <select value={newAccount.bank} onChange={e => setNewAccount(prev => ({ ...prev, bank: e.target.value }))}
                  className="border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
                  {BANKS.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>
              <div>
                <label className="font-label text-xs text-ink-light block mb-1">Type</label>
                <select value={newAccount.type} onChange={e => setNewAccount(prev => ({ ...prev, type: e.target.value }))}
                  className="border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm">
                  {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
                </select>
              </div>
              <button type="submit" className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2 rounded hover:bg-accent-deep transition-colors">
                Add
              </button>
            </form>
          </div>
        </div>

        {/* Categories */}
        <div className="ledger-card animate-reveal animate-reveal-3">
          <div className="ledger-card-header">Categories</div>
          <div className="p-5">
            <div className="flex flex-wrap gap-2 mb-5">
              {categories.map(cat => (
                <span key={cat.id} className="text-sm font-medium px-3 py-1.5 rounded border border-rule-strong bg-paper text-ink-medium hover:border-accent transition-colors">
                  {cat.name}
                </span>
              ))}
              {categories.length === 0 && <span className="text-sm text-ink-whisper">No categories</span>}
            </div>
            <form onSubmit={handleAddCategory} className="flex gap-3 items-end pt-4 border-t border-rule">
              <div className="flex-1">
                <label className="font-label text-xs text-ink-light block mb-1">New Category</label>
                <input value={newCategory} onChange={e => setNewCategory(e.target.value)} placeholder="Category name"
                  className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" />
              </div>
              <button type="submit" className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2 rounded hover:bg-accent-deep transition-colors">
                Add
              </button>
            </form>
          </div>
        </div>

        {/* Keyword Mappings */}
        <div className="ledger-card animate-reveal animate-reveal-4">
          <div className="ledger-card-header">Keyword Mappings</div>
          <div>
            {mappings.length === 0 && <div className="px-6 py-8 text-sm text-ink-whisper text-center">No keyword mappings</div>}
            {mappings.map(m => (
              <div key={m.id} className="grid grid-cols-[1fr_160px_100px_auto] items-center px-6 py-3 border-b border-rule last:border-b-0 hover:bg-accent-ghost transition-colors">
                <span className="text-sm font-mono text-ink-medium">{m.keyword_pattern}</span>
                <span className="text-sm text-ink-light">{m.category_name ?? `#${m.category_id}`}</span>
                <span className="font-label text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded-sm bg-cream-deep text-ink-light border border-rule w-fit">{m.source}</span>
                <button onClick={() => handleDeleteMapping(m.id)}
                  className="text-xs font-bold uppercase tracking-wide text-negative hover:bg-negative hover:text-white px-3 py-1.5 rounded border border-negative transition-colors justify-self-end">
                  Delete
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
