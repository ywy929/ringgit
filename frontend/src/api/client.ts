import axios from 'axios'
import type {
  Account, Budget, Category, DashboardSummary, EmailAccount,
  FetchResult, KeywordMapping, Transaction, UploadResult,
} from '../types'

const api = axios.create({ baseURL: '/api' })

export const getDashboard = (month: string) =>
  api.get<DashboardSummary>('/dashboard', { params: { month } }).then(r => r.data)

export const getTransactions = (params: {
  month?: string; category_id?: number; account_id?: number;
  type?: string; search?: string; page?: number;
}) => api.get<Transaction[]>('/transactions', { params }).then(r => r.data)

export const updateTransactionCategory = (txId: number, categoryId: number) =>
  api.patch(`/transactions/${txId}/category`, { category_id: categoryId }).then(r => r.data)

export const createTransaction = (data: {
  account_id: number; date: string; description: string;
  amount: number; type: string; category_id?: number;
}) => api.post<Transaction>('/transactions', data).then(r => r.data)

export const uploadStatement = (file: File, password?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  return api.post<UploadResult>('/upload', form).then(r => r.data)
}

export const getAccounts = () =>
  api.get<Account[]>('/accounts').then(r => r.data)

export const createAccount = (data: { name: string; bank: string; type: string }) =>
  api.post<Account>('/accounts', data).then(r => r.data)

export const deleteAccount = (id: number) =>
  api.delete(`/accounts/${id}`).then(r => r.data)

export const getBudget = (month: string) =>
  api.get<Budget | null>(`/budgets/${month}`).then(r => r.data)

export const setBudget = (month: string, targetAmount: number) =>
  api.put<Budget>('/budgets', { month, target_amount: targetAmount }).then(r => r.data)

export const getCategories = () =>
  api.get<Category[]>('/categories').then(r => r.data)

export const createCategory = (name: string) =>
  api.post<Category>('/categories', { name }).then(r => r.data)

export const renameCategory = (id: number, name: string) =>
  api.patch(`/categories/${id}`, { name }).then(r => r.data)

export const getKeywordMappings = () =>
  api.get<KeywordMapping[]>('/keyword-mappings').then(r => r.data)

export const deleteKeywordMapping = (id: number) =>
  api.delete(`/keyword-mappings/${id}`).then(r => r.data)

export const getEmailAccounts = () =>
  api.get<EmailAccount[]>('/email-accounts').then(r => r.data)

export const fetchEmails = () =>
  api.post<FetchResult[]>('/email-accounts/fetch').then(r => r.data)

export const deleteEmailAccount = (id: number) =>
  api.delete(`/email-accounts/${id}`).then(r => r.data)
