"""Render the CV stored in a saved run log, without running the pipeline.

    python tools/render_run_pdf.py                              # newest *.json run in the project folder
    python tools/render_run_pdf.py 20260928_163903_Applied_AI_Engineer.json
    python tools/render_run_pdf.py run.json -o out.pdf

Dev tool: reads the log, validates its final_cv and writes the PDF next to it.
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the repo root
sys.path.insert(0, str(PROJECT_DIR))  # so `jobfit` imports when this file is run directly

from jobfit.models import FinalCV
from jobfit.render_cv import render_cv_pdf


def latest_run() -> Path:
    runs = sorted(PROJECT_DIR.glob("[0-9]*_*.json"))
    if not runs:
        sys.exit("No saved run (*.json) found in the project folder; pass one as an argument.")
    return runs[-1]


def load_final_cv(path: Path) -> FinalCV:
    run = json.loads(path.read_text(encoding="utf-8"))
    cv = run.get("final_cv")
    if not cv:
        sys.exit(f"{path.name} has no final_cv (was it a 'recommend' run?).")

    # Older logs stored education as {id, course_name, ...}; the current model calls it degree.
    for edu in cv.get("education", []):
        if "degree" not in edu and "course_name" in edu:
            edu["degree"] = edu.pop("course_name")
    return FinalCV.model_validate(cv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the final_cv of a saved run log to PDF.")
    parser.add_argument("run", nargs="?", type=Path, help="saved run JSON (default: newest in project folder)")
    parser.add_argument("-o", "--output", type=Path, help="output PDF path (default: <run>_cv.pdf)")
    args = parser.parse_args()

    run_path = args.run or latest_run()
    cv = load_final_cv(run_path)
    output = args.output or run_path.with_name(f"{run_path.stem}_cv.pdf")
    output.write_bytes(render_cv_pdf(cv))

    print(f"Run:     {run_path.name}")
    print(f"CV for:  {cv.name or '(no name)'}")
    print(f"Content: {len(cv.skills)} skills, {len(cv.experience)} experience, {len(cv.projects)} projects, "
          f"{len(cv.education)} education, {len(cv.courses)} courses")
    print(f"PDF:     {output}")


if __name__ == "__main__":
    main()
