import { Link, useLocation } from 'react-router-dom'

export default function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const nav = [
    { path: '/', label: 'Dashboard' },
    { path: '/taxonomy', label: 'Taxonomy & Config' },
    { path: '/execution', label: 'Execution History' },
    { path: '/evaluation', label: 'Evaluation' },
  ]
  return (
    <div className="app">
      <aside className="sidebar">
        <h2 className="logo">Mailgine</h2>
        <nav>
          {nav.map(({ path, label }) => (
            <Link
              key={path}
              to={path}
              className={loc.pathname === path ? 'nav-link active' : 'nav-link'}
            >
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main">{children}</main>
    </div>
  )
}
