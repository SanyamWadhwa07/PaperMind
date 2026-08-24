-- Every peer review generated before this fix was written from a title and an author
-- list alone: core/intelligence/peer_review_agent.py read summary_data.summaries.simple,
-- summary_data.sections.methodology and summary_data.results.table_results, none of
-- which the pipeline ever persists (see backend/routes/process_paper.py's
-- _build_summary_record). So `Key results: []` was sent to the model on every paper —
-- which reads as "this paper reports no results" — and a model told to be a rigorous
-- NeurIPS/ICML reviewer, given nothing else, invented weaknesses to fill the request.
--
-- The prompt now reads the fields the pipeline actually writes and requires a strengths
-- list before concerns. But `/api/intelligence/peer-review/{id}` caches its result
-- forever with no TTL, so fixing the prompt does nothing for a paper already reviewed —
-- it would stay rejected indefinitely. There is no way to distinguish a review generated
-- under the old bug from one that isn't, so every existing row is discarded rather than
-- guessed at. The route now accepts ?force=true to regenerate on request.
--
-- Run this in the Supabase SQL editor.

DELETE FROM paper_intelligence WHERE analysis_type = 'peer_review';
