import { NavLink, Outlet } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
  icon: string
}

interface NavSection {
  heading?: string
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { to: '/', label: 'Overview', icon: '~' },
      { to: '/conversation', label: 'Chat', icon: '>' },
    ],
  },
  {
    heading: 'Operate',
    items: [
      { to: '/tasks', label: 'Tasks', icon: '#' },
      { to: '/agents', label: 'Agents', icon: '@' },
      { to: '/costs', label: 'Costs', icon: '$' },
    ],
  },
  {
    heading: 'Govern',
    items: [
      { to: '/health', label: 'Health', icon: '+' },
      { to: '/controls', label: 'Controls', icon: '%' },
      { to: '/messages', label: 'Messages', icon: '&' },
    ],
  },
  {
    heading: 'Reference',
    items: [
      { to: '/strategy', label: 'Strategy', icon: '!' },
      { to: '/timeline', label: 'Timeline', icon: '|' },
    ],
  },
]

export default function Layout() {
  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <nav className="w-52 bg-[#1e293b] border-r border-[#334155] flex flex-col shrink-0">
        <div className="p-4 border-b border-[#334155]">
          <h1 className="text-lg font-bold text-[#38bdf8] tracking-wide">agent-os</h1>
          <p className="text-xs text-[#64748b] mt-0.5">Dashboard</p>
        </div>
        <div className="flex-1 py-2">
          {NAV_SECTIONS.map((section, si) => (
            <div key={si}>
              {section.heading && (
                <div className="text-[10px] text-[#475569] uppercase tracking-wider px-4 pt-4 pb-1">
                  {section.heading}
                </div>
              )}
              {section.items.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      isActive
                        ? 'bg-[#334155] text-[#38bdf8] border-r-2 border-[#38bdf8]'
                        : 'text-[#94a3b8] hover:text-[#f1f5f9] hover:bg-[#334155]/50'
                    }`
                  }
                >
                  <span className="font-mono text-xs w-4 text-center opacity-60">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </div>
        <div className="p-3 border-t border-[#334155] text-[10px] text-[#475569]">
          agent-os
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
