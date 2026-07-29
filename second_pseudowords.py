"""
Second Pseudoword Generator — orthographic "relatives" of existing pseudowords
================================================================================
For each (Word, Pseudoword) pair in the input CSV, generate a *second*
pseudoword that:
  - differs from the first pseudoword by exactly one letter (occasionally two,
    only if no valid one-letter neighbor exists)
  - is phonotactically plausible (its onset/rime are attested in CLEARPOND,
    the same check pseudowords.py uses for Wuggy candidates)
  - is not a real English word (checked against the CLEARPOND lexicon)
  - is not identical to the source Word, the first Pseudoword, or any other
    second pseudoword already chosen in this run

Among valid candidates, positions where the substituted letter keeps the same
category (vowel-for-vowel or consonant-for-consonant) are preferred, since
that tends to preserve syllable structure and produce a more plausible-
sounding "relative" of the original pseudoword.

USAGE
-----
    python second_pseudowords.py \\
        --input     data/two-pseudowords.csv \\
        --clearpond data/englishCPdatabase2/englishCPdatabase2.txt \\
        --output    data/two-pseudowords_expanded.csv \\
        --seed      42
"""

import argparse
import csv
from itertools import combinations, product

from pseudowords import (
    _VOWEL_LETTERS,
    build_orth_phono_maps,
    compute_otan_otaf,
    compute_ptaf_and_ptan,
    load_clearpond,
    phono_to_disc,
    pseudoword_to_phono,
)
import random

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

ORIGINAL_FIELDNAMES = [
    "Word", "Length (Ortho)", "Word_PTAN", "Word_PTAF", "Word_OTAN", "Word_OTAF",
    "Pseudoword", "Pseudoword Length (Ortho)", "Consonant_Pseudoword",
    "Consonant_Pseudoword Length (Ortho)", "Pseudoword_PTAN", "Pseudoword_PTAF",
    "Pseudoword_OTAN", "Pseudoword_OTAF", "PTAF_RelDiff_Pct", "OTAN_Diff",
    "OTAF_RelDiff_Pct", "Status", "Method",
]

NEW_FIELDNAMES = [
    "Pseudoword2", "Pseudoword2_EditDistance", "Pseudoword2_PTAN", "Pseudoword2_PTAF",
    "Pseudoword2_OTAN", "Pseudoword2_OTAF", "Pseudoword2_vs_Pseudoword_PTAF_RelDiff_Pct",
    "Status2",
]


def _category(ch: str) -> str:
    return "V" if ch in _VOWEL_LETTERS else "C"


def _is_readable(word: str) -> bool:
    """Reject three-in-a-row identical letters (unpronounceable clusters)."""
    return not any(word[i] == word[i + 1] == word[i + 2] for i in range(len(word) - 2))


def _n_letter_substitution_neighbors(word: str, n: int) -> set[str]:
    """All words obtainable by substituting letters at exactly n positions."""
    length = len(word)
    results = set()
    for positions in combinations(range(length), n):
        choice_lists = [[c for c in _ALPHABET if c != word[p]] for p in positions]
        for combo in product(*choice_lists):
            w = list(word)
            for p, c in zip(positions, combo):
                w[p] = c
            results.add("".join(w))
    return results


def _score(word: str, cand: str) -> int:
    """Higher = more changed positions preserve vowel/consonant category."""
    return sum(1 for a, b in zip(word, cand) if a != b and _category(a) == _category(b))


def choose_second_pseudoword(
    word: str,
    pseudoword: str,
    lexicon_words: set[str],
    used: set[str],
    onset_map: dict,
    rime_map: dict,
    rng: random.Random,
):
    """
    Returns (chosen_word, phono_tuple, n_letters_changed, status) where status
    is "MATCHED" (phonotactically valid pick) or "BEST_AVAILABLE" (fallback
    with no phonotactically valid candidate found at all).
    """
    exclude = lexicon_words | {word, pseudoword} | used

    for n in (1, 2):
        candidates = sorted(_n_letter_substitution_neighbors(pseudoword, n))
        valid = []
        for w in candidates:
            if w in exclude or not _is_readable(w):
                continue
            phono = pseudoword_to_phono(w, onset_map, rime_map)
            if phono is None:
                continue
            valid.append((w, phono))
        if valid:
            best_score = max(_score(pseudoword, w) for w, _ in valid)
            best = [vp for vp in valid if _score(pseudoword, vp[0]) == best_score]
            rng.shuffle(best)
            chosen_word, chosen_phono = best[0]
            return chosen_word, chosen_phono, n, "MATCHED"

    # Fallback: no phonotactically-attested neighbor exists at 1 or 2 edits.
    # Relax the phonotactic requirement but keep the not-a-real-word /
    # not-already-used / readability constraints.
    for n in (1, 2):
        candidates = sorted(_n_letter_substitution_neighbors(pseudoword, n))
        rng.shuffle(candidates)
        for w in candidates:
            if w in exclude or not _is_readable(w):
                continue
            return w, None, n, "BEST_AVAILABLE"

    return None, None, None, "NO_CANDIDATE"


def run(input_path: str, clearpond_path: str, output_path: str, seed: int) -> None:
    rng = random.Random(seed)

    (lexicon, phono_to_words, all_phones,
     consonants, vowels, words_by_length) = load_clearpond(clearpond_path)
    lexicon_words = set(lexicon.keys())

    print("Building onset/rime phoneme lookup tables …")
    onset_map, rime_map = build_orth_phono_maps(lexicon, vowels)

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    used_second_pseudowords: set[str] = set()
    output_rows = []
    n_matched = 0
    n_best_available = 0
    n_no_candidate = 0

    for row in rows:
        word = (row.get("Word") or "").strip().lower()
        pseudoword = (row.get("Pseudoword") or "").strip().lower()
        if not word or not pseudoword:
            continue  # skip blank / summary rows (means, t-test, …)

        pw2, phono2, n_changed, status2 = choose_second_pseudoword(
            word, pseudoword, lexicon_words, used_second_pseudowords,
            onset_map, rime_map, rng,
        )

        out_row = {k: row.get(k, "") for k in ORIGINAL_FIELDNAMES}

        if pw2 is None:
            n_no_candidate += 1
            out_row.update({k: "" for k in NEW_FIELDNAMES})
            out_row["Status2"] = "NO_CANDIDATE"
            print(f"  ✗ {word:12s} {pseudoword:10s} → NO CANDIDATE FOUND")
            output_rows.append(out_row)
            continue

        assert n_changed is not None
        used_second_pseudowords.add(pw2)

        pw1_ptaf = float(row.get("Pseudoword_PTAF") or 0.0)

        if phono2 is not None:
            ptaf_sum, ptan = compute_ptaf_and_ptan(phono2, phono_to_words, all_phones)
            ptaf2 = ptaf_sum / ptan if ptan > 0 else 0.0
            otan2, otaf_sum2 = compute_otan_otaf(pw2, lexicon)
            otaf2 = otaf_sum2 / otan2 if otan2 > 0 else 0.0
            reldiff = (abs(ptaf2 - pw1_ptaf) / pw1_ptaf * 100) if pw1_ptaf > 0 else ""
            disc_str = phono_to_disc(phono2)
        else:
            ptan, ptaf2, otan2, otaf2, reldiff = "", "", "", "", ""
            disc_str = "no phonotactic match"

        out_row.update({
            "Pseudoword2": pw2,
            "Pseudoword2_EditDistance": n_changed,
            "Pseudoword2_PTAN": ptan,
            "Pseudoword2_PTAF": round(ptaf2, 4) if ptaf2 != "" else "",
            "Pseudoword2_OTAN": otan2,
            "Pseudoword2_OTAF": round(otaf2, 4) if otaf2 != "" else "",
            "Pseudoword2_vs_Pseudoword_PTAF_RelDiff_Pct": round(reldiff, 2) if reldiff != "" else "",
            "Status2": status2,
        })
        output_rows.append(out_row)

        if status2 == "MATCHED":
            n_matched += 1
        else:
            n_best_available += 1

        marker = "✓" if status2 == "MATCHED" else "~"
        print(f"  {marker} {word:12s} {pseudoword:10s} → {pw2:10s} "
              f"[{disc_str}]  ({n_changed} letter{'s' if n_changed > 1 else ''} changed)")

    fieldnames = ORIGINAL_FIELDNAMES + NEW_FIELDNAMES
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    total = len(output_rows)
    print(f"\nDone. {total} pairs → {output_path}")
    print(f"  {n_matched} MATCHED (phonotactically valid)")
    print(f"  {n_best_available} BEST_AVAILABLE (no phonotactic match, used relaxed fallback)")
    print(f"  {n_no_candidate} NO_CANDIDATE (should not normally happen)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a second, closely-related pseudoword for each existing pseudoword."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--clearpond", required=True)
    parser.add_argument("--output", default="two-pseudowords_expanded.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run(args.input, args.clearpond, args.output, args.seed)
