import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Compass,
  FileText,
  LayoutDashboard,
  Layers,
  LogOut,
  Menu,
  Moon,
  Network,
  Sun,
  User,
  X,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { Button, cx } from './ui/primitives'
import Logo from './Logo'
import ProcessingTray from './ProcessingTray'

/**
 * Navigation is grouped by what the user is doing, not by which endpoint backs
 * it: one paper at a time (Library, Add paper) vs. the whole corpus (Explore,
 * Timeline, Discover).
 */
const NAV_SECTIONS = [
  {
    label: 'Papers',
    items: [
      { to: '/dashboard', label: 'Library', icon: LayoutDashboard, private: true },
      { to: '/', label: 'Add paper', icon: FileText, private: false },
      { to: '/batch', label: 'Batch', icon: Layers, private: false },
    ],
  },
  {
    label: 'Corpus',
    items: [
      { to: '/explore', label: 'Explore', icon: Network, private: true },
      { to: '/timeline', label: 'Timeline', icon: Compass, private: true },
      { to: '/discover', label: 'Discover', icon: Compass, private: true },
    ],
  },
]

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}

function NavItems({ onNavigate }) {
  const { isAuthenticated } = useAuth()

  return (
    <nav className="space-y-6">
      {NAV_SECTIONS.map((section) => {
        const items = section.items.filter((item) => !item.private || isAuthenticated)
        if (!items.length) return null

        return (
          <div key={section.label}>
            <p className="px-3 text-eyebrow font-medium uppercase text-ink-faint">
              {section.label}
            </p>
            <ul className="mt-2 space-y-0.5">
              {items.map(({ to, label, icon: Icon }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    end={to === '/'}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cx(
                        'flex items-center gap-2.5 rounded px-3 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-accent-soft text-accent'
                          : 'text-ink-muted hover:bg-surface-hover hover:text-ink',
                      )
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    {label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}

function AccountMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  // Close on outside click and on Escape — a menu that traps the user is a bug.
  useEffect(() => {
    if (!open) return

    const onPointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const handleLogout = async () => {
    setOpen(false)
    await logout()
    navigate('/login')
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface-sunk text-sm font-semibold text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
      >
        {user?.full_name?.[0]?.toUpperCase() ||
          user?.email?.[0]?.toUpperCase() || <User className="h-4 w-4" />}
      </button>

      {open && (
        <div
          role="menu"
          className="animate-fade absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
        >
          <div className="border-b border-line px-3 py-2.5">
            <p className="truncate text-sm font-medium text-ink">
              {user?.full_name || 'Signed in'}
            </p>
            <p className="truncate text-xs text-ink-muted">{user?.email}</p>
          </div>
          <Link
            to="/profile"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink"
          >
            <User className="h-4 w-4" />
            Profile
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-muted transition-colors hover:bg-surface-hover hover:text-danger"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

export default function Layout({ children }) {
  const { isAuthenticated } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  // A route change must dismiss the mobile drawer, or it covers the new page.
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  return (
    // Column layout so the footer is pushed to the bottom of the viewport on
    // short pages instead of floating halfway up with dead space beneath it.
    <div className="flex min-h-screen flex-col bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-ink"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-50 border-b border-line bg-canvas/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1400px] 2xl:max-w-[1700px] 3xl:max-w-[1900px] items-center gap-3 px-4 sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen((v) => !v)}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>

          <Link to="/" className="flex items-center gap-2">
            <Logo className="h-7 w-6 text-accent" type="icon" />
            <span className="text-base font-semibold tracking-tight text-ink">
              PaperMind
            </span>
          </Link>

          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            {isAuthenticated ? (
              <AccountMenu />
            ) : (
              <Button to="/login" size="sm">
                Sign in
              </Button>
            )}
          </div>
        </div>
      </header>

      {/* The 1400px cap left roughly a quarter of a 1920px display as empty
          gutter. It still holds on a laptop, where a wider measure would hurt;
          `2xl` (1536px and up) is where the extra width is real screen rather
          than an over-long line. */}
      <div className="mx-auto flex w-full max-w-[1400px] 2xl:max-w-[1700px] 3xl:max-w-[1900px] flex-1 gap-8 px-4 py-6 sm:px-6 lg:py-8">
        {/* Desktop rail. Sticks below the header so navigation is always to hand. */}
        <aside className="hidden w-52 shrink-0 lg:block">
          <div className="sticky top-20">
            <NavItems />
          </div>
        </aside>

        {/* Mobile drawer */}
        {mobileOpen && (
          <>
            <div
              className="fixed inset-0 top-14 z-30 bg-ink/20 lg:hidden"
              onClick={() => setMobileOpen(false)}
              aria-hidden="true"
            />
            <aside className="animate-fade fixed inset-y-14 left-0 z-40 w-64 overflow-y-auto border-r border-line bg-surface p-4 lg:hidden">
              <NavItems onNavigate={() => setMobileOpen(false)} />
            </aside>
          </>
        )}

        {/* `isolate` keeps page content in its own stacking context. Page roots
            carry a filling `animate-rise`, which Chrome treats as a permanent
            stacking context, and without this one of those could paint over the
            account menu dropping out of the header. */}
        <main id="main" className="isolate min-w-0 flex-1">
          {children}
        </main>
      </div>

      <footer className="border-t border-line py-6">
        <div className="mx-auto flex max-w-[1400px] 2xl:max-w-[1700px] 3xl:max-w-[1900px] flex-wrap items-center justify-between gap-2 px-4 text-xs text-ink-faint sm:px-6">
          <p>PaperMind. Structured reading for research papers.</p>
          <p className="font-mono tabular">v2.0.0</p>
        </div>
      </footer>

      {/* Renders on every route, including the public "/" — a paper queued
          from Home must stay visible while browsing anywhere else. Sits outside
          `<main>`'s `isolate` stacking context (see the comment on it above) so
          it's never painted over, and under the header's z-50 so it never
          covers the account menu. */}
      <ProcessingTray />
    </div>
  )
}
