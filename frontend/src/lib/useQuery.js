/**
 * `useQuery` — the one way a page reads from the API.
 *
 * Backed by the shared store in `query.js`, so the result survives unmount and
 * navigating away and back is instant instead of re-running the request.
 *
 *   const { data, error, loading, refetch } = useQuery(
 *     ['corpus', tab],
 *     () => http.get(ENDPOINT[tab]),
 *   )
 *
 * `loading` is true only when there is nothing to show. A stale-but-present
 * value renders immediately while it refreshes underneath — use `refreshing`
 * for the quiet indicator that goes with that, not `loading`, or the page will
 * flash a skeleton over data the reader is already looking at.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

import {
  DEFAULT_TTL,
  fetchQuery,
  isStale,
  peek,
  queryKey,
  subscribe,
} from './query'

export function useQuery(key, fetcher, { ttl = DEFAULT_TTL, enabled = true } = {}) {
  const k = key == null ? null : queryKey(key)
  const [refreshing, setRefreshing] = useState(false)

  // The fetcher is nearly always an inline arrow, so it is a new function every
  // render. Holding it in a ref keeps it out of the effect's dependencies —
  // otherwise the effect re-runs on every render and refetches forever.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  // `getSnapshot` has to return a stable reference or React re-renders in a
  // loop. Entry objects are replaced wholesale on write and never mutated, so
  // the entry itself is that reference.
  const entry = useSyncExternalStore(
    useCallback((cb) => (k ? subscribe(k, cb) : () => {}), [k]),
    useCallback(() => (k ? peek(k) : undefined), [k]),
    useCallback(() => undefined, []),
  )

  const run = useCallback(
    async (force) => {
      if (!k || !enabled) return
      setRefreshing(true)
      try {
        await fetchQuery(k, () => fetcherRef.current(), { ttl, force })
      } catch {
        // The error is on the cached entry; `error` below surfaces it. Swallowed
        // here so a failed background refresh is not an unhandled rejection.
      } finally {
        setRefreshing(false)
      }
    },
    [k, enabled, ttl],
  )

  useEffect(() => {
    if (!k || !enabled) return
    // Fresh cache hit: nothing to do, the value is already rendered above.
    if (!isStale(peek(k), ttl)) return
    run(false)
  }, [k, enabled, ttl, run])

  const refetch = useCallback(() => run(true), [run])

  return {
    data: entry?.data,
    error: entry?.error ?? null,
    // Only a true cold start. A stale hit is not a loading state.
    loading: enabled && !!k && entry === undefined,
    refreshing,
    refetch,
  }
}

export default useQuery
