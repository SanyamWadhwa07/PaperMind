import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import AvatarUpload from '../components/AvatarUpload'
import { User, Mail, Calendar, Edit2, Save, X, AlertCircle, CheckCircle, BookMarked, Plus, Trash2 } from 'lucide-react'
import axios from 'axios'

const EXPERTISE_LEVELS = ['student', 'researcher', 'expert']
const FOCUS_PRESETS = ['NLP', 'Computer Vision', 'Reinforcement Learning', 'Graph Neural Networks', 'Generative Models', 'Robotics', 'Multimodal', 'Healthcare AI', 'Time Series']

export default function ProfilePage() {
  const { user, updateProfile, token } = useAuth()
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [formData, setFormData] = useState({
    full_name: '',
    bio: '',
    avatar_url: '',
    research_focus: [],
    expertise_level: 'researcher',
  })
  const [focusInput, setFocusInput] = useState('')
  const [message, setMessage] = useState({ type: '', text: '' })
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState(null)
  const [readingQueue, setReadingQueue] = useState([])

  useEffect(() => {
    if (user) {
      setFormData({
        full_name: user.full_name || '',
        bio: user.bio || '',
        avatar_url: user.avatar_url || '',
        research_focus: user.research_focus || [],
        expertise_level: user.expertise_level || 'researcher',
      })
      fetchStats()
      fetchReadingQueue()
    }
  }, [user])

  const fetchStats = async () => {
    try {
      const response = await fetch('http://localhost:5000/api/auth/me', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await response.json()
      setStats(data.stats)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    })
  }

  const handleAvatarUpdate = (avatarUrl) => {
    setFormData({
      ...formData,
      avatar_url: avatarUrl
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setMessage({ type: '', text: '' })

    const result = await updateProfile(formData)

    if (result.success) {
      setMessage({ type: 'success', text: 'Profile updated successfully!' })
      toast.success('Profile updated successfully!')
      setEditing(false)
    } else {
      setMessage({ type: 'error', text: result.error })
      toast.error(result.error || 'Failed to update profile')
    }

    setLoading(false)
  }

  const fetchReadingQueue = async () => {
    try {
      const res = await axios.get('/api/queue', {
        headers: { Authorization: `Bearer ${token}` },
      })
      setReadingQueue(res.data || [])
    } catch {
      // ignore
    }
  }

  const removeFromQueue = async (queueId) => {
    try {
      await axios.delete(`/api/queue/${queueId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      setReadingQueue(q => q.filter(item => item.id !== queueId))
      toast.success('Removed from reading queue.')
    } catch (e) {
      toast.error('Failed to remove: ' + (e.response?.data?.detail || e.message))
    }
  }

  const addFocusTag = (tag) => {
    const trimmed = tag.trim()
    if (!trimmed || formData.research_focus.includes(trimmed)) return
    setFormData(prev => ({ ...prev, research_focus: [...prev.research_focus, trimmed] }))
    setFocusInput('')
  }

  const removeFocusTag = (tag) => {
    setFormData(prev => ({ ...prev, research_focus: prev.research_focus.filter(t => t !== tag) }))
  }

  const handleCancel = () => {
    setFormData({
      full_name: user.full_name || '',
      bio: user.bio || '',
      avatar_url: user.avatar_url || '',
      research_focus: user.research_focus || [],
      expertise_level: user.expertise_level || 'researcher',
    })
    setEditing(false)
    setMessage({ type: '', text: '' })
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-[#00988F] border-t-transparent"></div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 sm:space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
          Profile
        </h1>
        <p className="mt-2 text-sm sm:text-base text-[#1B1B1B] dark:text-[#F5F5F5]">
          Manage your account information and preferences
        </p>
      </div>

      {/* Messages */}
      {message.text && (
        <div className={`${
          message.type === 'success' 
            ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' 
            : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
        } border rounded-lg p-4 flex items-start gap-3`}>
          {message.type === 'success' ? (
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
          )}
          <p className={`text-sm ${
            message.type === 'success' 
              ? 'text-green-600 dark:text-green-400' 
              : 'text-red-600 dark:text-red-400'
          }`}>
            {message.text}
          </p>
        </div>
      )}

      {/* Profile Card */}
      <div className="card">
        <div className="flex flex-col items-center gap-6 mb-8">
          <AvatarUpload 
            currentAvatar={formData.avatar_url}
            onAvatarUpdate={handleAvatarUpdate}
          />
        </div>

        <div className="flex flex-col sm:flex-row items-start justify-between gap-4 mb-6">
          <div className="flex items-center gap-4">
            <div>
              <h2 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
                {user.full_name || 'User'}
              </h2>
              <p className="text-sm text-[#8F8F8F] break-all">{user.email}</p>
            </div>
          </div>
          
          {!editing ? (
            <button
              onClick={() => setEditing(true)}
              className="btn-primary w-full sm:w-auto justify-center"
            >
              <Edit2 className="w-4 h-4" />
              Edit Profile
            </button>
          ) : (
            <div className="flex gap-2 w-full sm:w-auto">
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="btn-primary flex-1 sm:flex-initial justify-center disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                Save
              </button>
              <button
                onClick={handleCancel}
                className="btn-secondary flex-1 sm:flex-initial justify-center"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
            </div>
          )}
        </div>

        {/* Profile Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Full Name
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
              <input
                type="text"
                name="full_name"
                value={formData.full_name}
                onChange={handleChange}
                disabled={!editing}
                className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5] disabled:opacity-60"
                placeholder="Your full name"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Email
            </label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
              <input
                type="email"
                value={user.email}
                disabled
                className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg text-[#1B1B1B] dark:text-[#F5F5F5] opacity-60 cursor-not-allowed"
              />
            </div>
            <p className="mt-1 text-xs text-[#8F8F8F]">Email cannot be changed</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Bio
            </label>
            <textarea
              name="bio"
              value={formData.bio}
              onChange={handleChange}
              disabled={!editing}
              rows={4}
              className="w-full px-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5] disabled:opacity-60 resize-none"
              placeholder="Tell us about yourself..."
            />
          </div>

          {/* Research Focus */}
          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Research Focus Areas
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {(formData.research_focus || []).map(tag => (
                <span key={tag} className="flex items-center gap-1 px-2 py-0.5 bg-[#00988F]/10 border border-[#00988F]/30 rounded-full text-xs text-[#00988F]">
                  {tag}
                  {editing && (
                    <button onClick={() => removeFocusTag(tag)} className="hover:text-red-500">
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </span>
              ))}
              {formData.research_focus?.length === 0 && !editing && (
                <span className="text-xs text-[#8F8F8F]">No focus areas set</span>
              )}
            </div>
            {editing && (
              <>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={focusInput}
                    onChange={e => setFocusInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addFocusTag(focusInput) } }}
                    placeholder="Type a focus area and press Enter"
                    className="flex-1 px-3 py-1.5 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#00988F]"
                  />
                  <button type="button" onClick={() => addFocusTag(focusInput)} className="px-3 py-1.5 bg-[#00988F] text-white rounded-lg text-sm">
                    <Plus className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {FOCUS_PRESETS.filter(p => !formData.research_focus.includes(p)).map(p => (
                    <button key={p} type="button" onClick={() => addFocusTag(p)}
                      className="px-2 py-0.5 text-xs border border-slate-300 dark:border-slate-600 rounded-full text-slate-500 hover:border-[#00988F] hover:text-[#00988F]">
                      + {p}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Expertise Level */}
          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Expertise Level
            </label>
            <div className="flex gap-3">
              {EXPERTISE_LEVELS.map(level => (
                <label key={level} className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                  formData.expertise_level === level
                    ? 'border-[#00988F] bg-[#00988F]/10 text-[#00988F]'
                    : 'border-slate-200 dark:border-slate-600 text-slate-500'
                } ${!editing ? 'cursor-default' : ''}`}>
                  <input
                    type="radio"
                    name="expertise_level"
                    value={level}
                    checked={formData.expertise_level === level}
                    onChange={e => editing && setFormData(prev => ({ ...prev, expertise_level: e.target.value }))}
                    disabled={!editing}
                    className="sr-only"
                  />
                  <span className="text-sm capitalize">{level}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              Member Since
            </label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
              <input
                type="text"
                value={new Date(user.created_at).toLocaleDateString('en-US', { 
                  year: 'numeric', 
                  month: 'long', 
                  day: 'numeric' 
                })}
                disabled
                className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg text-[#1B1B1B] dark:text-[#F5F5F5] opacity-60 cursor-not-allowed"
              />
            </div>
          </div>
        </form>
      </div>

      {/* Reading Queue Card */}
      <div className="card">
        <h3 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-4 flex items-center gap-2">
          <BookMarked className="w-5 h-5" /> Reading Queue
        </h3>
        {readingQueue.length === 0 ? (
          <p className="text-sm text-[#8F8F8F]">No papers in your queue. Add them from any paper's page.</p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-700">
            {readingQueue.slice(0, 8).map(item => (
              <li key={item.id} className="flex items-center justify-between py-2 gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] truncate">
                    {item.summaries?.paper_title || item.summary_id}
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      item.status === 'read' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : item.status === 'reading' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                        : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400'
                    }`}>
                      {item.status}
                    </span>
                    <span className="text-xs text-[#8F8F8F]">priority {Math.round((item.priority_score || 0) * 100)}%</span>
                  </div>
                </div>
                <button
                  onClick={() => removeFromQueue(item.id)}
                  className="p-1.5 text-slate-400 hover:text-red-500 transition-colors"
                  title="Remove from queue"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {readingQueue.length > 8 && (
          <p className="text-xs text-[#8F8F8F] mt-2">+{readingQueue.length - 8} more papers in queue</p>
        )}
      </div>

      {/* Stats Card */}
      {stats && (
        <div className="card">
          <h3 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-4">
            Activity Stats
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs sm:text-sm text-[#8F8F8F]">Total Summaries</p>
              <p className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats.total_summaries || 0}
              </p>
            </div>
            <div>
              <p className="text-xs sm:text-sm text-[#8F8F8F]">Avg Time</p>
              <p className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats.avg_processing_time?.toFixed(1) || 0}s
              </p>
            </div>
            <div>
              <p className="text-xs sm:text-sm text-[#8F8F8F]">Words Processed</p>
              <p className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {(stats.total_words_processed || 0).toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-xs sm:text-sm text-[#8F8F8F]">Active Days</p>
              <p className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats.active_days || 0}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
