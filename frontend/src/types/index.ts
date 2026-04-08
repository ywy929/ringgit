export interface Account {
  id: number
  name: string
  bank: string
  type: string
}

export interface Category {
  id: number
  name: string
  is_default: boolean
}

export interface KeywordMapping {
  id: number
  keyword_pattern: string
  category_id: number
  category_name: string | null
  source: string
}

export interface Transaction {
  id: number
  date: string
  description: string
  amount: number
  type: 'debit' | 'credit'
  category_id: number | null
  category_name: string | null
  account_id: number
  account_name: string | null
  bank: string | null
  is_recurring: boolean
  is_cash_withdrawal: boolean
  is_internal_transfer: boolean
  linked_transfer_id: number | null
}

export interface Budget {
  id: number
  month: string
  target_amount: number
}

export interface CategorySpending {
  category_id: number
  category_name: string
  amount: number
}

export interface TransferSummary {
  from_account: string
  to_account: string
  amount: number
}

export interface DashboardSummary {
  month: string
  total_income: number
  total_spending: number
  savings: number
  savings_pct: number
  budget_target: number | null
  budget_used_pct: number | null
  cash_withdrawn: number
  cash_logged: number
  cash_untracked: number
  categories: CategorySpending[]
  internal_transfers: TransferSummary[]
}

export interface UploadResult {
  filename: string
  bank: string
  transactions_imported: number
  duplicates_skipped: number
  status: 'done' | 'duplicate' | 'failed'
  message: string | null
}

export interface EmailAccount {
  id: number
  email: string
  last_fetched_at: string | null
}

export interface FetchResult {
  email: string
  statements_found: number
  statements_processed: UploadResult[]
}
