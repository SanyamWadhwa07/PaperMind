"""Figure-extraction audit against each paper's own captions. No LLM key needed.

Ground truth is every caption label found line by line in the PDF's text layer
("Figure 3:", "Fig. 3.", "Figure 3.1:", "Figure G.1:", Springer "Fig. 3 Overview"),
with the first page it appears on. A rendered figure counts as found only when its
label and page both match. Line-level matching is independent of the block-level
caption detector under test, but it is not a hand label: an in-text line that
happens to start "Fig. 6 (middle) shows" is a false positive, and figures that are
typeset text (no vector ink, no bitmap) are counted but cannot be rendered.

    python evals/figure_audit.py <dir of arXiv PDFs> [ids ...]
    python evals/figure_audit.py <dir> --extractor <other pdf_extractor.py>   # A/B
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402

GT_RE = re.compile(r"^\s*(?:Figure|Fig\.?)\s*((?:[A-Z]\.?)?\d+(?:\.\d+)*)(?!\.?\d)(?:\s*[:.|]|\s+[A-Z(])")


def load_extractor(path: str | None):
    if not path:
        from core.pipeline import pdf_extractor
        return pdf_extractor
    spec = importlib.util.spec_from_file_location("core.pipeline._audited", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ground_truth(pdf: str) -> dict[str, int]:
    labels: dict[str, int] = {}
    with fitz.open(pdf) as doc:
        for page_index, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    m = GT_RE.match("".join(span["text"] for span in line["spans"]))
                    if m:
                        labels.setdefault(m.group(1), page_index + 1)
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("papers", type=Path)
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--extractor", help="audit another pdf_extractor.py instead")
    args = parser.parse_args()

    px = load_extractor(args.extractor)
    ids = args.ids or sorted(p.stem for p in args.papers.glob("*.pdf"))
    total_gt = total_found = complete = 0
    with tempfile.TemporaryDirectory() as tmp:
        for pid in ids:
            pdf = str(args.papers / f"{pid}.pdf")
            figures = px._extract_figures(pdf, Path(tmp) / pid)
            gt = ground_truth(pdf)
            got = {f.figure_number.replace("Figure ", ""): f.page_number
                   for f in figures if f.figure_number}
            found = sum(1 for label, page in gt.items() if got.get(label) == page)
            total_gt, total_found = total_gt + len(gt), total_found + found
            complete += found == len(gt)
            print(json.dumps({
                "id": pid, "captions": len(gt), "found": found,
                "missing": sorted(set(gt) - set(got)),
                "wrong_page": sorted(l for l in gt if l in got and got[l] != gt[l]),
                "unnumbered": sum(1 for f in figures if not f.figure_number),
            }))
    print(f"found {total_found}/{total_gt} = {total_found / max(total_gt, 1):.3f}; "
          f"complete papers {complete}/{len(ids)}")


if __name__ == "__main__":
    main()
