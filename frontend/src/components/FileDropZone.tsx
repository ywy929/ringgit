import { useState, useCallback } from 'react'

interface Props {
  onFiles: (files: File[]) => void
}

export default function FileDropZone({ onFiles }: Props) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files).filter(f => f.type === 'application/pdf')
    if (files.length > 0) onFiles(files)
  }, [onFiles])

  const handleClick = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.pdf'
    input.multiple = true
    input.onchange = () => { if (input.files) onFiles(Array.from(input.files)) }
    input.click()
  }

  return (
    <div onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }} onDragLeave={() => setIsDragging(false)} onDrop={handleDrop} onClick={handleClick}
      className={`border-2 border-dashed rounded p-12 text-center cursor-pointer transition-all ${isDragging ? 'border-accent-deep bg-accent-ghost' : 'border-accent bg-paper hover:bg-accent-ghost'}`}>
      <div className="text-4xl mb-4 text-accent">{'\u21EA'}</div>
      <div className="text-lg font-bold mb-2">Drop PDF statements here</div>
      <div className="text-sm text-ink-light mb-5">Bank statements, credit card statements, or e-wallet exports</div>
      <button className="bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-7 py-2.5 rounded hover:bg-accent-deep transition-colors">Browse Files</button>
      <div className="font-label text-xs text-ink-whisper mt-4">Supports: Maybank, CIMB, Public Bank, Hong Leong, Touch 'n Go, AEON Credit</div>
    </div>
  )
}
