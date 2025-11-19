import { Link, useNavigate } from 'react-router-dom'
import { BookOpen, Github, Moon, Sun, Menu, X, User, LogOut, LayoutDashboard } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import Logo from './Logo'

export default function Layout({ children }) {
  const { isAuthenticated, user, logout } = useAuth()
  const navigate = useNavigate()
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('darkMode')
    return saved ? JSON.parse(saved) : false
  })
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('darkMode', JSON.stringify(darkMode))
  }, [darkMode])

  const handleLogout = () => {
    logout()
    setProfileMenuOpen(false)
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#F9FBFA] via-[#E8F0EF] to-[#F9FBFA] dark:from-[#111312] dark:via-[#161817] dark:to-[#111312] transition-colors duration-300">
      {/* Header */}
      <header className="bg-[#EEF4F3]/80 dark:bg-[#1E2020]/80 backdrop-blur-xl border-b border-[#C4935F]/20 dark:border-[#D9A86C]/20 shadow-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-2 sm:gap-3 group">
              <div className="text-[#00988F] dark:text-[#00A7A0] transition-all group-hover:scale-110">
                <Logo className="w-10 h-12 sm:w-12 sm:h-14" type="icon" />
              </div>
              <div className="hidden sm:block">
                <h1 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
                  PaperMind
                </h1>
                <p className="text-xs sm:text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
                  AI-powered research paper intelligence
                </p>
              </div>
              <div className="sm:hidden">
                <h1 className="text-lg font-bold text-[#C4935F] dark:text-[#D9A86C]">
                  PaperMind
                </h1>
              </div>
            </Link>
            
            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center gap-4">
              <Link
                to="/"
                className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-[#00988F] dark:hover:text-[#00A7A0] font-medium transition-colors"
              >
                Home
              </Link>
              {isAuthenticated && (
                <Link
                  to="/dashboard"
                  className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-[#00988F] dark:hover:text-[#00A7A0] font-medium transition-colors"
                >
                  Dashboard
                </Link>
              )}
              <Link
                to="/batch"
                className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-[#00988F] dark:hover:text-[#00A7A0] font-medium transition-colors"
              >
                Batch Process
              </Link>
              
              <button
                onClick={() => setDarkMode(!darkMode)}
                className="p-2 rounded-lg bg-[#EEF4F3] dark:bg-[#1E2020] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-all border border-[#C4935F]/20 dark:border-[#D9A86C]/20"
                aria-label="Toggle dark mode"
              >
                {darkMode ? (
                  <Sun className="w-5 h-5 text-[#D9A86C]" />
                ) : (
                  <Moon className="w-5 h-5 text-[#00988F]" />
                )}
              </button>
              
              <a
                href="https://github.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#8F8F8F] dark:text-[#8F8F8F] hover:text-[#00988F] dark:hover:text-[#00A7A0] transition-colors"
              >
                <Github className="w-5 h-5" />
              </a>

              {/* Profile Menu */}
              {isAuthenticated ? (
                <div className="relative">
                  <button
                    onClick={() => setProfileMenuOpen(!profileMenuOpen)}
                    className="p-2 rounded-lg bg-gradient-to-br from-[#00988F] to-[#00A7A0] dark:from-[#00A7A0] dark:to-[#008F89] hover:shadow-lg transition-all"
                  >
                    <User className="w-5 h-5 text-white" />
                  </button>
                  {profileMenuOpen && (
                    <div className="absolute right-0 mt-2 w-48 bg-[#EEF4F3] dark:bg-[#1E2020] rounded-lg shadow-lg border border-[#C4935F]/20 dark:border-[#D9A86C]/20 py-2 z-50">
                      <div className="px-4 py-2 border-b border-[#C4935F]/20 dark:border-[#D9A86C]/20">
                        <p className="text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">{user?.email}</p>
                      </div>
                      <Link
                        to="/profile"
                        onClick={() => setProfileMenuOpen(false)}
                        className="flex items-center gap-2 px-4 py-2 text-sm text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-colors"
                      >
                        <User className="w-4 h-4" />
                        Profile
                      </Link>
                      <Link
                        to="/dashboard"
                        onClick={() => setProfileMenuOpen(false)}
                        className="flex items-center gap-2 px-4 py-2 text-sm text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-colors"
                      >
                        <LayoutDashboard className="w-4 h-4" />
                        Dashboard
                      </Link>
                      <button
                        onClick={handleLogout}
                        className="flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-colors"
                      >
                        <LogOut className="w-4 h-4" />
                        Logout
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <Link to="/login" className="btn-primary">
                  Login
                </Link>
              )}
            </nav>

            {/* Mobile Navigation */}
            <div className="md:hidden flex items-center gap-2">
              <button
                onClick={() => setDarkMode(!darkMode)}
                className="p-2 rounded-lg bg-[#EEF4F3] dark:bg-[#1E2020] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-all border border-[#C4935F]/20 dark:border-[#D9A86C]/20"
                aria-label="Toggle dark mode"
              >
                {darkMode ? (
                  <Sun className="w-4 h-4 text-[#D9A86C]" />
                ) : (
                  <Moon className="w-4 h-4 text-[#00988F]" />
                )}
              </button>
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="p-2 rounded-lg bg-[#EEF4F3] dark:bg-[#1E2020] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-all border border-[#C4935F]/20 dark:border-[#D9A86C]/20"
                aria-label="Toggle menu"
              >
                {mobileMenuOpen ? (
                  <X className="w-5 h-5 text-[#1B1B1B] dark:text-[#F5F5F5]" />
                ) : (
                  <Menu className="w-5 h-5 text-[#1B1B1B] dark:text-[#F5F5F5]" />
                )}
              </button>
            </div>
          </div>
        </div>
        
        {/* Mobile Menu Dropdown */}
        {mobileMenuOpen && (
          <div className="md:hidden border-t border-[#C4935F]/20 dark:border-[#D9A86C]/20 bg-[#EEF4F3] dark:bg-[#1E2020]">
            <div className="px-4 py-3 space-y-2">
              <Link
                to="/"
                onClick={() => setMobileMenuOpen(false)}
                className="block px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
              >
                Home
              </Link>
              {isAuthenticated && (
                <Link
                  to="/dashboard"
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
                >
                  Dashboard
                </Link>
              )}
              <Link
                to="/batch"
                onClick={() => setMobileMenuOpen(false)}
                className="block px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
              >
                Batch Process
              </Link>
              {isAuthenticated ? (
                <>
                  <Link
                    to="/profile"
                    onClick={() => setMobileMenuOpen(false)}
                    className="block px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
                  >
                    Profile
                  </Link>
                  <button
                    onClick={() => { handleLogout(); setMobileMenuOpen(false); }}
                    className="block w-full text-left px-4 py-2 text-red-600 dark:text-red-400 hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
                  >
                    Logout
                  </button>
                </>
              ) : (
                <Link
                  to="/login"
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
                >
                  Login
                </Link>
              )}
              <a
                href="https://github.com"
                target="_blank"
                rel="noopener noreferrer"
                className="block px-4 py-2 text-[#8F8F8F] dark:text-[#8F8F8F] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] rounded-lg font-medium transition-colors"
              >
                GitHub
              </a>
            </div>
          </div>
        )}
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-3 sm:px-4 md:px-6 lg:px-8 py-4 sm:py-6 md:py-8">
        {children}
      </main>

      {/* Footer */}
      <footer className="bg-[#EEF4F3]/50 dark:bg-[#1E2020]/60 backdrop-blur-sm border-t border-[#C4935F]/20 dark:border-[#D9A86C]/20 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-center text-[#1B1B1B] dark:text-[#F5F5F5] text-sm">
            Built with React, Flask, and LED Transformer 
          </p>
        </div>
      </footer>
    </div>
  )
}
