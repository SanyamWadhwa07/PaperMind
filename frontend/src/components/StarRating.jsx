import { useState } from 'react';
import { Star } from 'lucide-react';
import axios from 'axios';

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
      await axios.post(
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

  if (submitted) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <div className="flex">
          {[1, 2, 3, 4, 5].map((s) => (
            <Star
              key={s}
              size={16}
              className={s <= rating ? 'text-yellow-400 fill-yellow-400' : 'text-slate-600'}
            />
          ))}
        </div>
        <span>Thanks for your feedback!</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((s) => (
          <button
            key={s}
            onMouseEnter={() => setHover(s)}
            onMouseLeave={() => setHover(0)}
            onClick={() => submit(s)}
            disabled={loading}
            className="transition-transform hover:scale-110 disabled:opacity-50"
          >
            <Star
              size={20}
              className={
                s <= (hover || rating)
                  ? 'text-yellow-400 fill-yellow-400'
                  : 'text-slate-500'
              }
            />
          </button>
        ))}
        <span className="text-xs text-slate-500 ml-2">Rate this summary</span>
      </div>

      {(hover > 0 || rating > 0) && !submitted && (
        <div className="flex gap-2">
          <input
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value.slice(0, 300))}
            placeholder="Optional comment…"
            className="flex-1 text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
          />
        </div>
      )}
    </div>
  );
}
