import { useState } from 'react'
import type { UploadResult } from '../types'
import { uploadStatement } from '../api/client'
import FileDropZone from '../components/FileDropZone'
import { bankLabel } from '../banks'

const statusStyles: Record<string, string> = {
  done: 'bg-positive text-white',
  duplicate: 'bg-amber text-white',
  failed: 'bg-negative text-white',
}

export default function Upload() {
  const [password, setPassword] = useState('')
  const [results, setResults] = useState<UploadResult[]>([])
  const [uploading, setUploading] = useState(false)

  const handleFiles = async (files: File[]) => {
    setUploading(true)
    for (const file of files) {
      try {
        const result = await uploadStatement(file, password || undefined)
        setResults(prev => [...prev, result])
      } catch {
        setResults(prev => [...prev, {
          filename: file.name,
          bank: 'Unknown',
          transactions_imported: 0,
          duplicates_skipped: 0,
          status: 'failed' as const,
          message: 'Upload failed',
        }])
      }
    }
    setUploading(false)
  }

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-end mb-10 pb-3.5 border-b-2 border-ink animate-reveal">
        <span className="text-[28px] font-extrabold tracking-tight">Upload Statements</span>
      </div>

      {/* Drop zone */}
      <div className="max-w-2xl mx-auto animate-reveal animate-reveal-1">
        <FileDropZone onFiles={handleFiles} />

        {/* Password input */}
        <div className="mt-5">
          <label className="font-label text-xs text-ink-light block mb-1.5">PDF Password (if encrypted)</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Leave blank if not password-protected"
            className="w-full border border-rule rounded px-3 py-2 bg-paper text-ink focus:border-accent focus:outline-none text-sm" />
        </div>

        {/* Uploading indicator */}
        {uploading && (
          <div className="mt-6 text-center text-sm text-ink-light animate-pulse">Processing files...</div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div className="mt-8 space-y-3 animate-reveal">
            <h2 className="text-sm font-bold text-ink-medium uppercase tracking-wide mb-4">Results</h2>
            {results.map((r, i) => (
              <div key={i} className="ledger-card">
                <div className="p-5 flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-sm font-semibold text-ink">{r.filename}</span>
                      <span className={`font-label text-[9px] uppercase tracking-wide px-2 py-0.5 rounded-sm ${statusStyles[r.status]}`}>
                        {r.status}
                      </span>
                    </div>
                    <div className="flex gap-4 text-sm text-ink-light">
                      <span>Bank: <strong className="text-ink-medium">{bankLabel(r.bank)}</strong></span>
                      <span>Imported: <strong className="font-number text-positive">{r.transactions_imported}</strong></span>
                      {r.duplicates_skipped > 0 && (
                        <span>Duplicates: <strong className="font-number text-amber">{r.duplicates_skipped}</strong></span>
                      )}
                    </div>
                    {r.message && <div className="text-xs text-ink-whisper mt-1">{r.message}</div>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
