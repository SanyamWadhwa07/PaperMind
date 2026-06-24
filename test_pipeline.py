"""Quick pipeline smoke test — runs the full agent pipeline on a real PDF and prints quality metrics."""
import asyncio
import json
import os
import sys

# UTF-8 console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Make sure we load .env
from pathlib import Path
env_file = Path(__file__).parent / 'backend' / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent))

from core.agent_integration import AgentPaperProcessor


async def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/attention.pdf'

    config = {
        'llm_backend': os.environ.get('PAPERMIND_LLM_BACKEND', 'groq'),
        'llm_model': os.environ.get('PAPERMIND_LLM_MODEL', 'qwen/qwen3-32b'),
        'llm_max_tokens': 2048,
        'llm_temperature': 0.4,
        'experience_enabled': False,
    }

    print(f"Processing: {pdf_path}")
    print(f"LLM: {config['llm_backend']} / {config['llm_model']}")
    print("-" * 60)

    processor = AgentPaperProcessor(config=config)
    result = await processor.process_paper(pdf_path)

    # ── Debug agent errors ──
    raw_entities = result.get('_raw_entities', {})
    if not result.get('datasets') and not result.get('models'):
        print("[DEBUG] entities empty — agent_result entities:", result.get('models'), result.get('datasets'))

    # ── Summary ──
    summaries = result.get('summaries', {})
    main_summary = summaries.get('main', '')
    words = len(main_summary.split()) if main_summary else 0

    print(f"\n=== SUMMARY ({words} words) ===")
    print(main_summary[:1500] if main_summary else "(EMPTY)")

    # ── Think-tag check ──
    has_think = '<think>' in main_summary.lower()
    print(f"\nThink tags present: {has_think}")

    # ── Structured fields ──
    key_findings = result.get('key_findings', [])
    limitations  = result.get('limitations', [])
    future_work  = result.get('future_work', [])
    datasets     = result.get('datasets', [])
    models       = result.get('models', [])
    metrics      = result.get('metrics', [])
    figures      = result.get('figures', [])

    print(f"\n=== KEY FINDINGS ({len(key_findings)}) ===")
    for i, f in enumerate(key_findings, 1):
        print(f"  {i}. {f}")

    print(f"\n=== LIMITATIONS ({len(limitations)}) ===")
    for i, l in enumerate(limitations, 1):
        print(f"  {i}. {l}")

    print(f"\n=== FUTURE WORK ({len(future_work)}) ===")
    for i, fw in enumerate(future_work, 1):
        print(f"  {i}. {fw}")

    print(f"\n=== ENTITIES ===")
    print(f"  Datasets  ({len(datasets)}): {datasets[:5]}")
    print(f"  Models    ({len(models)}):   {models[:5]}")
    print(f"  Metrics   ({len(metrics)}):  {metrics[:5]}")
    print(f"  Figures   ({len(figures)}):  {len(figures)} extracted")

    # ── Pass/Fail verdict ──
    print("\n" + "=" * 60)
    checks = {
        "Summary >= 200 words":       words >= 200,
        "No <think> tags":            not has_think,
        "key_findings non-empty":     len(key_findings) > 0,
        "limitations non-empty":      len(limitations) > 0,
        "datasets or models found":   len(datasets) > 0 or len(models) > 0,
    }
    for label, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")

    all_pass = all(checks.values())
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
