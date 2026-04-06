"""
Analyze Mailgine user evaluation survey results.

Usage:
  1. Export Google Sheet as CSV → save as survey_results.csv in this folder
  2. Run: python analyze_survey.py
  3. Copy the output into your thesis or give it to Claude
"""

import csv
import sys
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).parent / "survey_results.csv"

LIKERT_COLUMNS = {
    "B1": "The interface appeared clear and easy to navigate",
    "B2": "I could understand the system's features without additional explanation",
    "B3": "The layout of the inbox is well organized",
    "B4": "I would feel confident using this system after a brief introduction",
    "B5": "The system appears suitable for non-technical users",
    "C1": "The email categories are intuitive and meaningful",
    "C2": "The automatic classification appeared to assign correct categories",
    "C3": "Automatic categorization would help me find emails faster",
    "D1": "The email summaries appeared accurate and captured key information",
    "D2": "The extracted fields looked correct and would save time",
    "D3": "The draft replies appeared professional and contextually appropriate",
    "D4": "Having different actions per category is a valuable feature",
    "E1": "This system would reduce the time I spend managing emails",
    "E2": "This system would improve my ability to find important information",
    "E3": "This system would help me respond to emails faster",
    "E4": "I could see this system being useful in a team environment",
    "E5": "I would be interested in using this system for my own email",
}

SECTIONS = {
    "B — Interface & Ease of Use": ["B1", "B2", "B3", "B4", "B5"],
    "C — Classification Quality": ["C1", "C2", "C3"],
    "D — Artifact Quality": ["D1", "D2", "D3", "D4"],
    "E — Perceived Usefulness": ["E1", "E2", "E3", "E4", "E5"],
}

BACKGROUND_COLS = {
    "A1": "Emails per day",
    "A2": "Time on email",
    "A3": "Professional context",
}


def mean(vals):
    return sum(vals) / len(vals) if vals else 0


def std(vals):
    if len(vals) < 2:
        return 0
    m = mean(vals)
    return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def find_column(headers, code):
    code_lower = code.lower()
    for h in headers:
        h_clean = h.strip().lower()
        if (
            h_clean.startswith(code_lower + " ")
            or h_clean.startswith(code_lower + "–")
            or h_clean.startswith(code_lower + " –")
            or h_clean == code_lower
        ):
            return h
    for h in headers:
        if code_lower in h.strip().lower().replace("–", "-").replace("—", "-"):
            return h
    return None


def main():
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found.")
        print("Export your Google Sheet as CSV and save it as 'survey_results.csv'")
        sys.exit(1)

    rows = load_csv(CSV_PATH)
    headers = list(rows[0].keys()) if rows else []
    n = len(rows)
    print(f"{'=' * 70}")
    print(f"MAILGINE USER EVALUATION — SURVEY RESULTS (n={n})")
    print(f"{'=' * 70}\n")

    # --- Background ---
    print("SECTION A: RESPONDENT BACKGROUND\n")
    for code, label in BACKGROUND_COLS.items():
        col = find_column(headers, code)
        if not col:
            print(f"  {code} ({label}): column not found")
            continue
        counts = Counter(row[col].strip() for row in rows if row[col].strip())
        print(f"  {code} — {label}:")
        for val, cnt in counts.most_common():
            pct = cnt / n * 100
            print(f"    {val}: {cnt} ({pct:.0f}%)")
        print()

    # --- Likert per question ---
    print(f"\n{'=' * 70}")
    print("LIKERT SCALE RESULTS (1 = Strongly Disagree → 5 = Strongly Agree)\n")

    all_section_means = {}

    for section_name, codes in SECTIONS.items():
        print(f"\n{section_name}")
        print(f"{'-' * len(section_name)}")
        section_vals = []
        for code in codes:
            col = find_column(headers, code)
            if not col:
                print(f"  {code}: column not found in CSV (looked for '{code}')")
                continue
            vals = []
            for row in rows:
                try:
                    v = int(row[col].strip())
                    vals.append(v)
                except (ValueError, KeyError):
                    pass
            if not vals:
                print(f"  {code}: no numeric data")
                continue
            section_vals.extend(vals)
            m = mean(vals)
            s = std(vals)
            md = median(vals)
            dist = Counter(vals)
            bar = " ".join(f"{k}:{dist.get(k, 0)}" for k in range(1, 6))
            print(
                f"  {code}  M={m:.2f}  SD={s:.2f}  Md={md:.1f}  ({bar})  n={len(vals)}"
            )
            print(f"       {LIKERT_COLUMNS.get(code, '')}")

        if section_vals:
            sm = mean(section_vals)
            ss = std(section_vals)
            all_section_means[section_name] = (sm, ss, len(section_vals))
            print(f"  >> Section average: M={sm:.2f}, SD={ss:.2f}")

    # --- Overall summary ---
    print(f"\n\n{'=' * 70}")
    print("SUMMARY TABLE (for thesis)\n")
    print(f"{'Section':<35} {'Mean':>6} {'SD':>6} {'n':>5}")
    print(f"{'-' * 35} {'-' * 6} {'-' * 6} {'-' * 5}")
    for sec, (m, s, cnt) in all_section_means.items():
        print(f"{sec:<35} {m:>6.2f} {s:>6.2f} {cnt:>5}")

    all_vals = []
    for sec, (m, s, cnt) in all_section_means.items():
        all_vals.extend([m] * cnt)
    if all_vals:
        overall = mean(all_vals)
        print(f"\n  Overall Likert average: {overall:.2f} / 5.00")

    # --- Open-ended ---
    print(f"\n\n{'=' * 70}")
    print("OPEN-ENDED RESPONSES\n")
    for code, label in [
        ("F1", "Most useful feature"),
        ("F2", "What to improve/add"),
        ("F3", "Additional comments"),
    ]:
        col = find_column(headers, code)
        if not col:
            print(f"  {code} ({label}): column not found")
            continue
        print(f"  {code} — {label}:")
        for i, row in enumerate(rows, 1):
            val = row[col].strip() if row.get(col) else ""
            if val:
                print(f'    R{i}: "{val}"')
        print()

    # --- Thesis-ready markdown table ---
    print(f"\n{'=' * 70}")
    print("THESIS-READY MARKDOWN TABLE\n")
    print("| Code | Statement | M | SD | Md |")
    print("|------|-----------|---|----|----|")
    for section_name, codes in SECTIONS.items():
        for code in codes:
            col = find_column(headers, code)
            if not col:
                continue
            vals = []
            for row in rows:
                try:
                    vals.append(int(row[col].strip()))
                except (ValueError, KeyError):
                    pass
            if vals:
                m = mean(vals)
                s = std(vals)
                md = median(vals)
                stmt = LIKERT_COLUMNS.get(code, "")
                print(f"| {code} | {stmt} | {m:.2f} | {s:.2f} | {md:.1f} |")
        print(
            f"| | **{section_name}** | **{all_section_means.get(section_name, (0,0,0))[0]:.2f}** | **{all_section_means.get(section_name, (0,0,0))[1]:.2f}** | |"
        )

    print(f"\nn = {n} respondents")


if __name__ == "__main__":
    main()
