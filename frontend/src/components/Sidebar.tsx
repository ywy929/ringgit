import { NavLink } from 'react-router-dom'

const navItems = [
  { section: 'Overview', items: [
    { to: '/', label: 'Dashboard', icon: '\u25A0' },
    { to: '/transactions', label: 'Transactions', icon: '\u2630' },
  ]},
  { section: 'Manage', items: [
    { to: '/upload', label: 'Upload', icon: '\u2191' },
    { to: '/budget', label: 'Budget', icon: '\u25C9' },
  ]},
  { section: 'System', items: [
    { to: '/settings', label: 'Settings', icon: '\u2699' },
  ]},
]

export default function Sidebar() {
  return (
    <nav className="w-[220px] min-h-screen bg-paper border-r border-rule fixed left-0 top-0 bottom-0 flex flex-col z-10" style={{ boxShadow: '2px 0 12px rgba(26,24,22,0.04)' }}>
      <div className="px-6 pb-7 pt-8 border-b-2 border-ink mb-6">
        <h1 className="text-2xl font-extrabold tracking-tight">Ringgit</h1>
        <div className="font-label text-[11px] text-ink-light mt-1">Personal Finance Ledger</div>
      </div>
      {navItems.map(section => (
        <div key={section.section} className="px-4 mb-6">
          <div className="font-label text-[10px] uppercase tracking-[1.5px] text-ink-whisper px-2 mb-2">{section.section}</div>
          {section.items.map(item => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}
              className={({ isActive }) => `flex items-center gap-2.5 px-3 py-2.5 rounded-md text-sm font-medium mb-0.5 transition-all ${isActive ? 'bg-accent-ghost text-accent-ink font-semibold border-l-[3px] border-accent pl-[9px]' : 'text-ink-light hover:bg-cream hover:text-ink-medium'}`}>
              <span className="text-base w-[22px] text-center">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="flex-1" />
      <div className="px-6 py-4 border-t border-rule mx-4">
        <div className="font-label text-[11px] text-ink-whisper">v1.0 — ringgit</div>
      </div>
    </nav>
  )
}
