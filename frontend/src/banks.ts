// Bank registry — single source of truth for the slug<->label mapping.
// Slugs match each backend parser's bank_id; labels are display-only.
export const BANKS: { value: string; label: string }[] = [
  { value: 'maybank', label: 'Maybank' },
  { value: 'cimb', label: 'CIMB' },
  { value: 'public_bank', label: 'Public Bank' },
  { value: 'hong_leong', label: 'Hong Leong' },
  { value: 'aeon', label: 'AEON Credit' },
  { value: 'tng', label: "Touch 'n Go" },
  { value: 'rhb', label: 'RHB' },
  { value: 'ambank', label: 'AmBank' },
]

const _LABEL: Record<string, string> = Object.fromEntries(BANKS.map(b => [b.value, b.label]))

export function bankLabel(slug: string | null | undefined): string {
  if (!slug) return ''
  return _LABEL[slug] ?? slug
}
