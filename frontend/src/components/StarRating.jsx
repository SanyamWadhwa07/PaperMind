import { useState } from 'react';
import { Star } from 'lucide-react';
import api from '../lib/api';
import { Eyebrow, Input, cx } from './ui/primitives';

/**
 * The reader's own mark on a paper, so it carries the annotation colour rather
 * than the brand accent — the accent belongs to actions the app initiates.
 */
export default function StarRating({ summaryId, initialRating = 0 }) {
  const [hover, setHover] = useState(0);
  const [rating, setRating] = useState(initialRating);
  const [comment, setComment] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const token = localStorage.getItem('token');

  const submit = async (stars) => {
    if (!token || loading) return;
    setLoading(true);
    try {
      await api.post(
        `/api/feedback/summary/${summaryId}`,
        { rating: stars, comment: comment || undefined, feedback_type: 'rating' },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setRating(stars);
      setSubmitted(true);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  const stars = [1, 2, 3, 4, 5];

  if (submitted) {
    return (
      <div className="flex items-center gap-2.5">
        <div className="flex gap-0.5">
          {stars.map((s) => (
            <Star
              key={s}
              size={15}
              className={
                s <= rating ? 'fill-annotate text-annotate' : 'text-ink-faint'
              }
              aria-hidden="true"
            />
          ))}
        </div>
        <span className="text-caption text-ink-muted">
          Rated {rating} of 5. Thank you.
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Eyebrow>Rate this summary</Eyebrow>
        <div className="flex gap-0.5" role="radiogroup" aria-label="Rate this summary">
          {stars.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={s === rating}
              aria-label={`${s} star${s > 1 ? 's' : ''}`}
              onMouseEnter={() => setHover(s)}
              onMouseLeave={() => setHover(0)}
              onFocus={() => setHover(s)}
              onBlur={() => setHover(0)}
              onClick={() => submit(s)}
              disabled={loading}
              className="rounded-sm p-0.5 transition-transform duration-fast ease-out hover:scale-110 disabled:opacity-50"
            >
              <Star
                size={18}
                className={cx(
                  'transition-colors duration-fast ease-out',
                  s <= (hover || rating)
                    ? 'fill-annotate text-annotate'
                    : 'text-ink-faint'
                )}
              />
            </button>
          ))}
        </div>
      </div>

      {(hover > 0 || rating > 0) && (
        <Input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value.slice(0, 300))}
          placeholder="Add a note (optional)"
          aria-label="Optional comment"
          className="h-9 max-w-md text-caption"
        />
      )}
    </div>
  );
}
