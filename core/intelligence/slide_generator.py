"""Slide deck generator — converts paper analysis to a 5-slide HTML presentation."""

import json
import structlog
from core.llm.json_parse import parse_json_object
import re
from typing import Any, Dict, Optional

logger = structlog.get_logger(__name__)

SLIDE_SYSTEM = """You are a presentation designer. Convert the paper into exactly 5 slides.
Return ONLY JSON (no markdown, no extra text):
{
  "slides": [
    {"title": "...", "content": "...", "notes": "..."},
    ...
  ]
}
Slide 1: Title + one-line core contribution
Slide 2: Problem & motivation (why it matters)
Slide 3: Method overview (key idea in plain language)
Slide 4: Key results (include numbers/metrics)
Slide 5: Conclusions & future work"""


async def generate_slides(
    summary_id: str,
    user_id: str,
    supabase_client: Any,
    llm_config: Optional[Dict] = None,
) -> str:
    """Returns a self-contained HTML string for the slide deck."""
    from core.llm.llm_interface import get_llm

    # Fetch paper data
    try:
        resp = (
            supabase_client.table("summaries")
            .select("paper_title, paper_authors, summary_data")
            .eq("id", summary_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        paper = resp.data or {}
    except Exception as e:
        logger.error("slide_fetch_error", exc_info=e)
        paper = {}

    sd = paper.get("summary_data") or {}
    title = paper.get("paper_title", "Research Paper")
    authors = ", ".join((paper.get("paper_authors") or [])[:4])
    # The persisted record has one summary under `summaries.main` (see
    # core/graph/adapter.py), not the `simple`/`technical` split this used to read —
    # both of those were always "". `methods_detail` is the closest thing to a
    # technical summary the pipeline actually writes.
    simple_summary = (sd.get("summaries") or {}).get("main", "")[:600]
    technical_summary = sd.get("methods_detail", "")[:600]
    results = sd.get("results") or {}
    results_text = json.dumps({
        "summary": results.get("summary", "")[:200],
        "metrics": (results.get("metrics") or [])[:5],
    })[:600]

    prompt = (
        f"Title: {title}\nAuthors: {authors}\n"
        f"Simple summary: {simple_summary}\n"
        f"Technical details: {technical_summary}\n"
        f"Key results: {results_text}\n\n"
        "Generate 5 slides."
    )

    llm = get_llm(llm_config)
    raw = await llm.generate(prompt, system_prompt=SLIDE_SYSTEM, max_tokens=2048)

    slide_data = _parse_slides(raw, title, authors)
    return _render_html(slide_data, title, authors)


def _parse_slides(raw: str, title: str, authors: str) -> list:
    slides = parse_json_object(raw).get("slides")
    if slides:
        return slides
    # Fallback: split on numbered sections
    return [
        {"title": title, "content": authors, "notes": ""},
        {"title": "Problem", "content": "See paper for details.", "notes": ""},
        {"title": "Method", "content": "Novel approach proposed.", "notes": ""},
        {"title": "Results", "content": "Improved over baselines.", "notes": ""},
        {"title": "Conclusions", "content": "Future work directions identified.", "notes": ""},
    ]


def _render_html(slides: list, title: str, authors: str) -> str:
    slides_html = ""
    for i, slide in enumerate(slides[:5]):
        slide_title = slide.get("title", f"Slide {i+1}")
        content = slide.get("content", "").replace("\n", "<br>")
        num = i + 1
        slides_html += f"""
        <div class="slide" id="slide-{num}" style="display:{'block' if num == 1 else 'none'}">
          <div class="slide-number">{num} / {min(len(slides), 5)}</div>
          <h2 class="slide-title">{slide_title}</h2>
          <div class="slide-content">{content}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
<style>
  body {{ background:#1e1b4b; font-family:'Segoe UI',sans-serif; display:flex; flex-direction:column; align-items:center; min-height:100vh; padding:2rem; }}
  .deck {{ width:100%; max-width:860px; }}
  .slide {{ background:white; border-radius:12px; padding:3rem; min-height:480px; position:relative; box-shadow:0 20px 60px rgba(0,0,0,.4); }}
  .slide-number {{ position:absolute; top:1rem; right:1.5rem; color:#6b7280; font-size:.85rem; }}
  .slide-title {{ font-size:2rem; font-weight:700; color:#1e1b4b; margin-bottom:1.5rem; border-bottom:3px solid #6366f1; padding-bottom:.75rem; }}
  .slide-content {{ font-size:1.1rem; color:#374151; line-height:1.8; }}
  .controls {{ margin-top:1.5rem; display:flex; gap:1rem; }}
  .btn {{ padding:.6rem 1.6rem; border-radius:8px; border:none; cursor:pointer; font-size:1rem; font-weight:600; }}
  .btn-prev {{ background:#4f46e5; color:white; }}
  .btn-next {{ background:#6366f1; color:white; }}
  .btn:disabled {{ opacity:.4; cursor:not-allowed; }}
  .header {{ color:white; text-align:center; margin-bottom:1.5rem; }}
  .header h1 {{ font-size:1.4rem; font-weight:700; }}
  .header p {{ font-size:.9rem; opacity:.7; }}
</style>
</head>
<body>
<div class="deck">
  <div class="header">
    <h1>{title}</h1>
    <p>{authors}</p>
  </div>
  {slides_html}
  <div class="controls">
    <button class="btn btn-prev" id="prev" onclick="navigate(-1)" disabled>&#8592; Prev</button>
    <button class="btn btn-next" id="next" onclick="navigate(1)">Next &#8594;</button>
  </div>
</div>
<script>
  var current = 1, total = {min(len(slides), 5)};
  function navigate(dir) {{
    document.getElementById('slide-'+current).style.display='none';
    current += dir;
    document.getElementById('slide-'+current).style.display='block';
    document.getElementById('prev').disabled = current === 1;
    document.getElementById('next').disabled = current === total;
  }}
</script>
</body>
</html>"""
