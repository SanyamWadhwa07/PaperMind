/**
 * A small read-through cache for GET-shaped API calls.
 *
 * Every page used to fetch in a `useEffect` and hold the result in its own
 * `useState`. That state dies with the component, so moving from Timeline to
 * Explore and back re-ran both requests and showed both spinners again — the
 * data had not changed, only the route had. Pages that did try to cache (
 * Explore's `graphData`, Summary's `intelligence`) cached into component state,
 * which has the same problem and gave four slightly different hand-rolled
 * implementations of it.
 *
 * This is the shared version: one module-level store, so a result outlives the
 * component that asked for it.
 *
 *   - **LRU with a hard cap.** A long session touching a hundred papers should
 *     not grow an unbounded map of every response it has ever seen. Entries
 *     that something is currently rendering are never evicted.
 *   - **TTL.** Cached data is served immediately and, once past its TTL,
 *     refreshed in the background — the reader sees the old value instantly and
 *     it updates in place, rather than watching a spinner for a value that was
 *     probably still correct.
 *   - **In-flight de-duplication.** Two components mounting on the same key in
 *     the same tick share one request. This also absorbs React 18 StrictMode's
 *     double effect invocation in development, which otherwise doubles every
 *     request on every page.
 *
 * Writes go through `invalidate()`. Anything that changes server state must
 * call it, or the UI will keep serving the value from before the change.
 */

/** Enough for a deep session; small enough to stay a cache, not a leak. */
const MAX_ENTRIES = 64

/** Most of this data is a corpus-wide aggregate that changes when the user
 *  processes a paper — which invalidates explicitly — so the TTL only has to
 *  cover edits made in another tab. */
export const DEFAULT_TTL = 5 * 60 * 1000

/** key -> { data, error, at } — `at` is when it was written. */
const store = new Map()

/** key -> Promise, for the duration of one request. */
const inflight = new Map()

/** key -> Set<callback>, so a write reaches every mounted reader of that key. */
const listeners = new Map()

/** Stable cache keys from arrays: ['graph', id] -> 'graph|id'. */
export function queryKey(key) {
  return Array.isArray(key) ? key.filter((p) => p != null).join('|') : String(key)
}

function notify(key) {
  const subs = listeners.get(key)
  if (subs) for (const fn of subs) fn()
}

/** Move a key to the most-recent end of the Map's insertion order. */
function touch(key) {
  const entry = store.get(key)
  if (entry !== undefined) {
    store.delete(key)
    store.set(key, entry)
  }
  return entry
}

function evictIfNeeded() {
  if (store.size <= MAX_ENTRIES) return
  for (const key of store.keys()) {
    // Never evict something on screen — dropping it would blank a mounted view
    // and trigger an immediate refetch, which is the opposite of the point.
    if (listeners.get(key)?.size) continue
    store.delete(key)
    if (store.size <= MAX_ENTRIES) return
  }
}

function write(key, entry) {
  store.delete(key)
  store.set(key, entry)
  evictIfNeeded()
  notify(key)
}

export function subscribe(key, callback) {
  let subs = listeners.get(key)
  if (!subs) {
    subs = new Set()
    listeners.set(key, subs)
  }
  subs.add(callback)
  return () => {
    subs.delete(callback)
    if (subs.size === 0) listeners.delete(key)
  }
}

/** The cached entry, or undefined. Reading counts as use for LRU purposes. */
export function peek(key) {
  return touch(key)
}

export function isStale(entry, ttl = DEFAULT_TTL) {
  return !entry || Date.now() - entry.at > ttl
}

/**
 * Resolve a key, from cache when it is fresh and from the network otherwise.
 *
 * Rejections are cached too. A failed request that is not remembered gets
 * retried by every render that reads it, so a 500 on a corpus graph turns into
 * a request loop for as long as the page is open.
 */
export async function fetchQuery(key, fetcher, { ttl = DEFAULT_TTL, force = false } = {}) {
  const k = queryKey(key)

  if (!force) {
    const entry = touch(k)
    if (entry && !isStale(entry, ttl)) {
      if (entry.error) throw entry.error
      return entry.data
    }
  }

  const pending = inflight.get(k)
  if (pending) return pending

  const promise = (async () => {
    try {
      const data = await fetcher()
      write(k, { data, error: null, at: Date.now() })
      return data
    } catch (error) {
      write(k, { data: undefined, error, at: Date.now() })
      throw error
    } finally {
      inflight.delete(k)
    }
  })()

  inflight.set(k, promise)
  return promise
}

/**
 * Drop cached entries so the next read refetches.
 *
 * With no argument it clears everything — what logout needs, so the next user
 * never sees the previous one's library. A string prefix-matches, which is why
 * keys are built as `scope|id`: processing a paper can invalidate `corpus` and
 * `summaries` without naming every variant.
 */
export function invalidate(prefix) {
  const match = prefix == null ? null : queryKey(prefix)
  for (const key of [...store.keys()]) {
    if (match === null || key === match || key.startsWith(`${match}|`)) {
      store.delete(key)
      notify(key)
    }
  }
  // Drop in-flight requests too: one started before the change would otherwise
  // resolve afterwards and write the pre-change value back into the cache.
  for (const key of [...inflight.keys()]) {
    if (match === null || key === match || key.startsWith(`${match}|`)) {
      inflight.delete(key)
    }
  }
}

/** Seed the cache from data already in hand — e.g. the row a list just fetched,
 *  so opening it does not refetch what the list already had. */
export function prime(key, data) {
  write(queryKey(key), { data, error: null, at: Date.now() })
}
