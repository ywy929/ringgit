import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  const { pathname } = useLocation()
  const isDashboard = pathname === '/'

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className={`ml-[220px] flex-1 min-h-screen ${isDashboard ? 'ruled-bg' : ''}`}>
        <div className="max-w-[960px] mx-auto px-8 py-10">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
