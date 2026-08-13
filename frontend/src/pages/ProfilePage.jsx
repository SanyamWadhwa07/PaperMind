import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import AvatarUpload from '../components/AvatarUpload'
import { Mail, Edit2, Save, X, BookMarked, Plus, Trash2 } from 'lucide-react'
import { papers, queue } from '../lib/api'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  Eyebrow,
  Field,
  Input,
  Metric,
  Skeleton,
  Textarea,
  cx,
} from '../components/ui/primitives'

const EXPERTISE_LEVELS = ['student', 'researcher', 'expert']
const FOCUS_PRESETS = ['NLP', 'Computer Vision', 'Reinforcement Learning', 'Graph Neural Networks', 'Generative Models', 'Robotics', 'Multimodal', 'Healthcare AI', 'Time Series']

const QUEUE_TONE = { read: 'success', reading: 'accent' }

export default function ProfilePage() {
  const { user, updateProfile } = useAuth()
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
      setStats(await papers.dashboardStats().then((d) => d.stats))
    } catch (error) {
      // Stats are supplementary; the profile form still works without them.
      console.error('Could not load profile stats:', error.message)
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
      const data = await queue.list()
      setReadingQueue(Array.isArray(data) ? data : data?.items || [])
    } catch {
      // The queue is an optional panel; a failure here should not block the page.
    }
  }

  const removeFromQueue = async (queueId) => {
    try {
      await queue.remove(queueId)
      setReadingQueue(q => q.filter(item => item.id !== queueId))
      toast.success('Removed from your reading queue')
    } catch (error) {
      toast.error(error.message || 'Could not remove that item')
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
      <div className="mx-auto max-w-3xl space-y-6">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="animate-rise mx-auto max-w-3xl space-y-8">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Account</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Profile</h1>
        <p className="mt-2 text-sm text-ink-muted">
          What PaperMind knows about you, and what it uses to rank papers.
        </p>
      </header>

      {message.text &&
        (message.type === 'error' ? (
          <ErrorState title="Could not save" message={message.text} />
        ) : (
          <div className="rounded-lg border border-success/30 bg-success-soft px-5 py-3">
            <p className="text-sm text-success">{message.text}</p>
          </div>
        ))}

      <Card>
        <CardBody className="space-y-8">
          <div className="flex flex-col items-start gap-5 sm:flex-row sm:items-center">
            <AvatarUpload
              currentAvatar={formData.avatar_url}
              onAvatarUpdate={handleAvatarUpdate}
            />

            <div className="min-w-0 flex-1">
              <h2 className="truncate text-lg font-semibold text-ink">
                {user.full_name || 'Unnamed researcher'}
              </h2>
              <p className="mt-0.5 flex items-center gap-1.5 truncate text-sm text-ink-muted">
                <Mail className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {user.email}
              </p>
              <p className="mt-2 font-mono tabular text-code text-ink-faint">
                Member since{' '}
                {new Date(user.created_at).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}
              </p>
            </div>

            {!editing ? (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                <Edit2 className="h-4 w-4" aria-hidden="true" />
                Edit
              </Button>
            ) : (
              <div className="flex gap-2">
                <Button onClick={handleSubmit} loading={loading}>
                  <Save className="h-4 w-4" aria-hidden="true" />
                  Save
                </Button>
                <Button variant="secondary" onClick={handleCancel}>
                  <X className="h-4 w-4" aria-hidden="true" />
                  Cancel
                </Button>
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit} className="space-y-5 border-t border-line pt-8">
            <Field label="Full name" htmlFor="full_name">
              <Input
                id="full_name"
                type="text"
                name="full_name"
                value={formData.full_name}
                onChange={handleChange}
                disabled={!editing}
                placeholder="Your full name"
              />
            </Field>

            <Field label="Bio" htmlFor="bio">
              <Textarea
                id="bio"
                name="bio"
                value={formData.bio}
                onChange={handleChange}
                disabled={!editing}
                rows={4}
                className="resize-none"
                placeholder="What do you work on?"
              />
            </Field>

            <Field
              label="Research focus"
              hint={editing ? 'Press Enter to add your own, or pick from below.' : undefined}
            >
              <div className="flex flex-wrap gap-1.5">
                {(formData.research_focus || []).map((tag) => (
                  <Badge key={tag} tone="accent">
                    {tag}
                    {editing && (
                      <button
                        type="button"
                        onClick={() => removeFocusTag(tag)}
                        className="-mr-1 ml-0.5 rounded-full p-0.5 hover:text-danger"
                        aria-label={`Remove ${tag}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </Badge>
                ))}
                {formData.research_focus?.length === 0 && !editing && (
                  <span className="text-sm text-ink-faint">Nothing set yet</span>
                )}
              </div>
            </Field>

            {editing && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <Input
                    type="text"
                    value={focusInput}
                    onChange={(e) => setFocusInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addFocusTag(focusInput)
                      }
                    }}
                    placeholder="Add a focus area"
                    aria-label="Add a research focus area"
                  />
                  <Button
                    type="button"
                    size="icon"
                    onClick={() => addFocusTag(focusInput)}
                    aria-label="Add focus area"
                    className="h-11 w-11 shrink-0"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {FOCUS_PRESETS.filter((p) => !formData.research_focus.includes(p)).map(
                    (p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => addFocusTag(p)}
                        className="rounded-full border border-line px-2.5 py-1 text-eyebrow font-semibold uppercase text-ink-faint transition-colors duration-fast ease-out hover:border-accent hover:text-accent"
                      >
                        + {p}
                      </button>
                    ),
                  )}
                </div>
              </div>
            )}

            <Field label="Expertise level">
              <div className="flex flex-wrap gap-2">
                {EXPERTISE_LEVELS.map((level) => (
                  <label
                    key={level}
                    className={cx(
                      'rounded border px-3.5 py-2 text-sm capitalize',
                      'transition-colors duration-fast ease-out',
                      formData.expertise_level === level
                        ? 'border-accent bg-accent-soft text-accent'
                        : 'border-line text-ink-muted',
                      editing ? 'cursor-pointer hover:border-line-strong' : 'cursor-default',
                    )}
                  >
                    <input
                      type="radio"
                      name="expertise_level"
                      value={level}
                      checked={formData.expertise_level === level}
                      onChange={(e) =>
                        editing &&
                        setFormData((prev) => ({
                          ...prev,
                          expertise_level: e.target.value,
                        }))
                      }
                      disabled={!editing}
                      className="sr-only"
                    />
                    {level}
                  </label>
                ))}
              </div>
            </Field>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Reading queue"
          description="Papers waiting for your attention, ranked by priority."
          action={<BookMarked className="h-4 w-4 text-ink-faint" aria-hidden="true" />}
        />
        <CardBody>
          {readingQueue.length === 0 ? (
            <p className="text-sm text-ink-faint">
              Nothing queued. Add papers from any summary page.
            </p>
          ) : (
            <>
              <ul className="divide-y divide-line">
                {readingQueue.slice(0, 8).map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 py-3 first:pt-0">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-serif text-sm text-ink">
                        {item.summaries?.paper_title || item.summary_id}
                      </p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <Badge tone={QUEUE_TONE[item.status] || 'neutral'}>
                          {item.status}
                        </Badge>
                        <span className="font-mono tabular text-code text-ink-faint">
                          priority {Math.round((item.priority_score || 0) * 100)}%
                        </span>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => removeFromQueue(item.id)}
                      aria-label="Remove from queue"
                      className="hover:text-danger"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </li>
                ))}
              </ul>
              {readingQueue.length > 8 && (
                <p className="mt-3 font-mono tabular text-code text-ink-faint">
                  +{readingQueue.length - 8} more queued
                </p>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {stats && (
        <Card>
          <CardHeader title="Activity" />
          <div className="grid grid-cols-2 md:grid-cols-4">
            {[
              { label: 'Papers', value: stats.total_summaries || 0 },
              { label: 'Avg. run', value: `${stats.avg_processing_time?.toFixed(1) || 0}s` },
              {
                label: 'Words read',
                value: (stats.total_words_processed || 0).toLocaleString(),
              },
              { label: 'Active days', value: stats.active_days || 0 },
            ].map(({ label, value }, i) => (
              <div
                key={label}
                className={cx(
                  'border-line p-5',
                  i % 2 === 1 && 'border-l',
                  i < 2 && 'border-b md:border-b-0',
                  'md:border-l md:first:border-l-0',
                )}
              >
                <Metric label={label} value={value} />
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
