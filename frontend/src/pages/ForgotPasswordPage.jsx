import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useToast } from '../contexts/ToastContext';
import { Mail, ArrowLeft } from 'lucide-react';

export default function ForgotPasswordPage() {
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!email) {
      toast.error('Email is required');
      return;
    }

    setLoading(true);

    try {
      const response = await fetch('http://localhost:5000/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });

      const data = await response.json();

      if (response.ok) {
        setSent(true);
        toast.success('Password reset email sent! Check your inbox.');
      } else {
        toast.error(data.error || 'Failed to send reset email');
      }
    } catch (error) {
      toast.error('Network error. Please try again.');
    }

    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
            Forgot Password?
          </h2>
          <p className="mt-2 text-sm sm:text-base text-[#1B1B1B] dark:text-[#F5F5F5]">
            Enter your email to receive a password reset link
          </p>
        </div>

        {sent ? (
          <div className="card text-center space-y-4">
            <div className="w-16 h-16 bg-teal-100 dark:bg-teal-900/30 rounded-full flex items-center justify-center mx-auto">
              <Mail className="w-8 h-8 text-teal-600 dark:text-teal-400" />
            </div>
            <div>
              <h3 className="text-xl font-semibold text-[#C4935F] dark:text-[#D9A86C] mb-2">
                Check your email
              </h3>
              <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
                We've sent a password reset link to <span className="font-medium">{email}</span>
              </p>
            </div>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 text-teal-600 dark:text-teal-400 hover:underline"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to login
            </Link>
          </div>
        ) : (
          <form className="card space-y-6" onSubmit={handleSubmit}>
            <div>
              <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
                  placeholder="you@example.com"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full btn-primary"
            >
              {loading ? 'Sending...' : 'Send Reset Link'}
            </button>

            <div className="text-center">
              <Link
                to="/login"
                className="text-sm text-teal-600 dark:text-teal-400 hover:underline"
              >
                Remember your password? Log in
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
