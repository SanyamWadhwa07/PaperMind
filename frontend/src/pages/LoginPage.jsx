import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Mail, Lock, AlertCircle } from 'lucide-react'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const toast = useToast()
  
  const [formData, setFormData] = useState({
    email: '',
    password: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const from = location.state?.from?.pathname || '/dashboard'

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    })
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!formData.email || !formData.password) {
      setError('Email and password are required')
      return
    }

    setLoading(true)

    const result = await login(formData.email, formData.password)

    if (result.success) {
      toast.success('Logged in successfully!')
      navigate(from, { replace: true })
    } else {
      setError(result.error)
      toast.error(result.error || 'Login failed')
    }

    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        {/* Header */}
        <div className="text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
            Welcome Back to PaperMind
          </h2>
          <p className="mt-2 text-sm sm:text-base text-[#1B1B1B] dark:text-[#F5F5F5]">
            Log in to continue exploring research
          </p>
        </div>

        {/* Login Form */}
        <form className="card mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
          )}

          <div className="space-y-4">
            {/* Email */}
            <div>
              <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
                <input
                  type="email"
                  name="email"
                  value={formData.email}
                  onChange={handleChange}
                  className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
                  placeholder="you@example.com"
                  required
                  autoFocus
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
                <input
                  type="password"
                  name="password"
                  value={formData.password}
                  onChange={handleChange}
                  className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
                  placeholder="••••••••"
                  required
                />
              </div>
              <div className="text-right">
                <Link to="/forgot-password" className="text-sm text-[#00988F] dark:text-[#00A7A0] hover:underline">
                  Forgot password?
                </Link>
              </div>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full justify-center py-3 text-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <div className="animate-spin rounded-full h-5 w-5 border-2 border-white border-t-transparent"></div>
                Logging in...
              </>
            ) : (
              'Log In'
            )}
          </button>

          {/* Signup Link */}
          <p className="text-center text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
            Don't have an account?{' '}
            <Link to="/signup" className="font-medium text-[#00988F] dark:text-[#00A7A0] hover:underline">
              Sign up
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
