import { Link, useLocation } from 'react-router-dom'

export default function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const nav = [
    { path: '/', label: 'Inbox', icon: '📬' },
    { path: '/taxonomy', label: 'Settings', icon: '⚙️' },
    { path: '/execution', label: 'Activity Log', icon: '📋' },
    { path: '/evaluation', label: 'Evaluation', icon: '📊' },
  ]
  return (
    <div className="app">
      <aside className="sidebar">
        <h2 className="logo">Mailgine</h2>
        <p className="logo-sub">Intelligent Email Assistant</p>
        <nav>
          {nav.map(({ path, label, icon }) => (
            <Link
              key={path}
              to={path}
              className={loc.pathname === path ? 'nav-link active' : 'nav-link'}
            >
              <span className="nav-icon">{icon}</span>
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main">{children}</main>
    </div>
  )
}
