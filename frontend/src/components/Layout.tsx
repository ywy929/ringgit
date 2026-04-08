import { Outlet } from 'react-router-dom'

export default function Layout() {
  return (
    <div className="min-h-screen">
      <main className="max-w-[960px] mx-auto px-8 py-10">
        <Outlet />
      </main>
    </div>
  )
}
