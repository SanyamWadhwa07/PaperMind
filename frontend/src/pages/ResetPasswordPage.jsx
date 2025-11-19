import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useToast } from '../contexts/ToastContext';
import { Lock, CheckCircle } from 'lucide-react';

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const toast = useToast();
  
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [accessToken, setAccessToken] = useState('');

  useEffect(() => {
    // Extract access_token from URL hash (Supabase redirects with #access_token=...)
    const hash = window.location.hash;
    const params = new URLSearchParams(hash.substring(1));
    const token = params.get('access_token');
    
    if (token) {
      setAccessToken(token);
    } else {
      toast.error('Invalid reset link');
      setTimeout(() => navigate('/forgot-password'), 2000);
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!password || !confirmPassword) {
      toast.error('Please fill in all fields');
      return;
    }

    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      const response = await fetch('http://localhost:5000/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          access_token: accessToken,
          new_password: password
        })
      });

      const data = await response.json();

      if (response.ok) {
        toast.success('Password reset successfully!');
        setTimeout(() => navigate('/login'), 2000);
      } else {
        toast.error(data.error || 'Failed to reset password');
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
            Reset Password
          </h2>
          <p className="mt-2 text-sm sm:text-base text-[#1B1B1B] dark:text-[#F5F5F5]">
            Enter your new password below
          </p>
        </div>

        <form className="card space-y-6" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              New Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
                placeholder="At least 8 characters"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Confirm Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
                placeholder="Confirm your password"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !accessToken}
            className="w-full btn-primary"
          >
            {loading ? 'Resetting...' : 'Reset Password'}
          </button>
        </form>
      </div>
    </div>
  );
}
