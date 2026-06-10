"""
Pseudoword Generator — PTAF Matched (Wuggy + CLEARPOND version)
===============================================================
For each real word in your input CSV this script generates a pseudoword that:
  - Looks like a plausible English word (Wuggy subsyllabic generator)
  - Has the same number of phonemes as the real word
  - Has a PTAF (computed against the English lexicon) within TOLERANCE of
    the real word's PTAF

Pipeline
--------
1. Load the CLEARPOND English database and build:
     • lexicon            word → {phono, freq, eptaf}
     • phono_to_words     phono_tuple → [(word, freq)]
     • onset/rime maps    orthographic onset/rime → most common phoneme onset/rime

2. Use Wuggy (orthographic_english plugin) to generate N readable pseudoword
   candidates per real word.  Wuggy guarantees English-like letter patterns.

3. For each candidate, approximate its phoneme sequence by looking up its
   orthographic onset and rime in the CLEARPOND-derived maps.

4. Compute PTAF for that phoneme sequence against CLEARPOND neighbors.

5. Pick the candidate with PTAF closest to the target; accept if within
   TOLERANCE.

USAGE
-----
    python pseudowords.py \\
        --input    your_words.csv \\
        --clearpond data/englishCPdatabase2/englishCPdatabase2.txt \\
        --output   results.csv

    Optional flags:
        --tolerance   0.10     # relative PTAF tolerance (default 10%)
        --candidates  30       # Wuggy candidates per word (default 30)
        --seed        42       # random seed (only affects fallback generator)
"""

import argparse
import csv
import os
import random
import sys
from collections import Counter, defaultdict

from rich.console import Console
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TaskProgressColumn,
    TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)

_console = Console()

_WITTY_STATUSES = [
    "consulting the phoneme oracle",
    "rearranging subsyllables",
    "asking Wuggy nicely",
    "tickling the lexicon",
    "negotiating with consonants",
    "borrowing neighboring letters",
    "interrogating CLEARPOND",
    "computing phonological neighborhoods",
    "searching for lookalikes",
    "measuring phonemic distances",
    "reshuffling the onset",
    "polishing the rime",
    "checking for real words",
    "auditing the vowels",
    "wrangling phonotactics",
    "doing linguistic gymnastics",
    "summoning pseudolinguistic entities",
    "pretending this is a real word",
    "bribing the consonants",
    "defying the lexicon",
]


# ═══════════════════════════════════════════════════════════════════════════
# 1.  PHONEME TOKENISATION  (CLEARPOND DISC format)
#     Dots are phoneme separators; multi-char tokens are single phonemes.
#       "s.t.oU.n" → ('s','t','oU','n')
#       "tS.Er"    → ('tS','Er')
# ═══════════════════════════════════════════════════════════════════════════

def tokenize(phono_str):
    return tuple(t for t in phono_str.strip().split(".") if t)


def phono_to_disc(phono_tuple):
    return ".".join(phono_tuple)


# ═══════════════════════════════════════════════════════════════════════════
# 2.  LOAD CLEARPOND DATABASE
# ═══════════════════════════════════════════════════════════════════════════

_CONSONANT_PHONES = frozenset([
    "p", "b", "t", "d", "k", "g",
    "f", "v", "s", "z", "h",
    "S", "Z", "T", "D",
    "tS", "dZ",
    "m", "n", "N", "l", "r", "r0", "w", "j",
    "x",
])
_VOWEL_PHONES = frozenset([
    "I", "I0", "E", "1", "V", "U", "5", "3",
    "i", "u", "A", "O", "o", "a", "e",
    "eI", "aI", "oU", "aU", "OI", "56", "36",
    "or", "Ar", "ir", "Er", "Ur", "A7",
])


def load_clearpond(path):
    """
    Returns lexicon, phono_to_words, all_phones, consonants, vowels, words_by_length.
    """
    print(f"[1/5] Loading CLEARPOND database: {path}")

    lexicon         = {}
    phono_to_words  = defaultdict(list)
    all_phones      = set()
    words_by_length = defaultdict(list)

    headers_path = os.path.join(os.path.dirname(os.path.abspath(path)),
                                "clearpondHeaders_EN.txt")
    if os.path.exists(headers_path):
        with open(headers_path, "rb") as hf:
            fieldnames = hf.read().decode("latin-1").split("\r")
    else:
        fieldnames = None

    with open(path, newline="", encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter="\t", fieldnames=fieldnames)
        header = fieldnames if fieldnames else (reader.fieldnames or [])

        for col in ("Word", "Phono", "Frequency", "ePTAF"):
            if col not in header:
                sys.exit(f"ERROR: column '{col}' not found. Found: {header}")

        for row in reader:
            word      = row["Word"].strip().lower()
            phono_raw = row["Phono"].strip()
            if not word or not phono_raw:
                continue

            phono = tokenize(phono_raw)

            try:
                freq  = float(row["Frequency"])
            except (ValueError, TypeError):
                freq  = 0.0
            try:
                eptaf = float(row["ePTAF"])
            except (ValueError, TypeError):
                eptaf = 0.0

            lexicon[word] = {"phono": phono, "freq": freq, "eptaf": eptaf}
            phono_to_words[phono].append((word, freq))
            all_phones.update(phono)
            words_by_length[len(phono)].append(phono)

    n_words = len(lexicon)
    print(f"    Loaded {n_words:,} words | {len(all_phones)} phoneme tokens")
    if n_words == 0:
        sys.exit("ERROR: No words loaded. Check file path and delimiter.")

    consonants = _CONSONANT_PHONES & all_phones
    vowels     = _VOWEL_PHONES     & all_phones
    return lexicon, phono_to_words, all_phones, consonants, vowels, words_by_length


# ═══════════════════════════════════════════════════════════════════════════
# 3.  ONSET / RIME PHONEME LOOKUP TABLES
#     Built from CLEARPOND so we can convert Wuggy's orthographic pseudowords
#     into approximate phoneme sequences for PTAF computation.
# ═══════════════════════════════════════════════════════════════════════════

_VOWEL_LETTERS = frozenset("aeiou")


def _split_orth(word):
    """Split a word into its orthographic onset and rime at the first vowel."""
    for i, c in enumerate(word):
        if c in _VOWEL_LETTERS:
            return word[:i], word[i:]
    return word, ""


def _split_phono(phono, vowel_phones):
    """Split a phoneme tuple into onset (pre-nucleus) and rime (vowel onward)."""
    for i, ph in enumerate(phono):
        if ph in vowel_phones:
            return phono[:i], phono[i:]
    return phono, ()


def build_orth_phono_maps(lexicon, vowel_phones):
    """
    Returns:
        onset_map  : str → most-common phoneme onset tuple
        rime_map   : str → most-common phoneme rime tuple
    """
    onset_counter = defaultdict(Counter)
    rime_counter  = defaultdict(Counter)

    for word, entry in lexicon.items():
        phono          = entry["phono"]
        orth_onset, orth_rime  = _split_orth(word)
        phono_onset, phono_rime = _split_phono(phono, vowel_phones)
        onset_counter[orth_onset][phono_onset] += 1
        rime_counter[orth_rime][phono_rime]    += 1

    onset_map = {k: v.most_common(1)[0][0] for k, v in onset_counter.items()}
    rime_map  = {k: v.most_common(1)[0][0] for k, v in rime_counter.items()}
    return onset_map, rime_map


def pseudoword_to_phono(pseudoword, onset_map, rime_map, fallback_phono, vowel_phones):
    """
    Approximate the phoneme sequence for an orthographic pseudoword.

    Onset: exact lookup in onset_map; fall back to source word's onset.
    Rime:  exact lookup in rime_map; fall back to source word's rime.

    The fallback is intentional: Wuggy pseudowords often have rimes not in
    CLEARPOND (e.g. "igric"), and falling back to the source word's rime
    keeps the phoneme count and neighborhood structure plausible.
    """
    orth_onset, orth_rime = _split_orth(pseudoword)

    phono_onset = onset_map.get(orth_onset)
    if phono_onset is None:
        phono_onset, _ = _split_phono(fallback_phono, vowel_phones)

    phono_rime = rime_map.get(orth_rime)
    if phono_rime is None:
        _, phono_rime = _split_phono(fallback_phono, vowel_phones)

    return phono_onset + phono_rime


# ═══════════════════════════════════════════════════════════════════════════
# 4.  WUGGY CANDIDATE GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def load_wuggy():
    """Load the Wuggy orthographic English generator (downloads plugin if needed)."""
    try:
        from wuggy import WuggyGenerator
    except ImportError:
        sys.exit(
            "ERROR: wuggy is not installed.\n"
            "Create a virtualenv and run: pip install wuggy"
        )
    g = WuggyGenerator()
    try:
        g.load("orthographic_english")
    except Exception:
        print("    Wuggy plugin not found locally — downloading …")
        g.download_language_plugin("orthographic_english")
        g.load("orthographic_english")
    return g


def wuggy_candidates(word, wuggy_gen, n_candidates, lexicon_words):
    """
    Generate up to n_candidates Wuggy pseudowords for word.
    Returns a list of orthographic pseudoword strings.
    Returns None if word is not in Wuggy's lexicon.
    """
    try:
        results = wuggy_gen.generate_classic(
            [word],
            ncandidates_per_sequence=n_candidates,
            max_search_time_per_sequence=30,
        )
    except Exception:
        return None   # word not in Wuggy lexicon

    candidates = []
    for r in results:
        pw = r.get("pseudoword", "")
        if pw and pw not in lexicon_words:
            candidates.append(pw)
    return candidates if candidates else None


# ═══════════════════════════════════════════════════════════════════════════
# 5.  FALLBACK CANDIDATE GENERATION  (mutation of real-word phoneme templates)
#     Used when Wuggy cannot handle a word.
# ═══════════════════════════════════════════════════════════════════════════

_DISC_TO_GRAPHEME = {
    "p": "p",  "b": "b",  "t": "t",  "d": "d",  "k": "k",  "g": "g",
    "f": "f",  "v": "v",  "s": "s",  "z": "z",  "h": "h",
    "S": "sh", "Z": "zh", "T": "th", "D": "th",
    "tS": "ch", "dZ": "j",
    "m": "m",  "n": "n",  "N": "ng", "l": "l",
    "r": "r",  "r0": "r", "w": "w",  "j": "y",
    "x": "kh",
    "I": "i",  "I0": "i", "E": "e",  "1": "a",
    "V": "u",  "U": "u",  "5": "e",  "3": "ur",
    "i": "ee", "u": "oo", "A": "a",  "O": "or",
    "o": "o",  "a": "a",
    "eI": "ay", "aI": "igh", "oU": "ow", "aU": "ow",
    "OI": "oy", "56": "ow",  "36": "ur",
    "or": "or", "Ar": "ar", "ir": "eer", "Er": "air", "Ur": "ure",
    "A7": "eer",
}


def disc_to_spelling(phono_tuple):
    return "".join(_DISC_TO_GRAPHEME.get(ph, ph) for ph in phono_tuple)


def fallback_candidates(target_len, all_phones, consonants, vowels,
                        n_candidates, lexicon_phonos, words_by_length, rng):
    """Mutate real-word phoneme templates to produce non-lexical phoneme sequences."""
    consonants_l = sorted(consonants)
    vowels_l     = sorted(vowels)
    templates    = words_by_length.get(target_len, [])
    if not templates:
        for delta in (1, -1, 2, -2):
            templates = words_by_length.get(target_len + delta, [])
            if templates:
                break

    seen       = set()
    candidates = []
    attempts   = 0

    while len(candidates) < n_candidates and attempts < n_candidates * 20:
        attempts += 1
        if templates:
            seq = list(rng.choice(templates))
            for pos in rng.sample(range(len(seq)), min(3, len(seq))):
                ph = seq[pos]
                if ph in consonants:
                    pool = [c for c in consonants_l if c != ph]
                elif ph in vowels:
                    pool = [v for v in vowels_l   if v != ph]
                else:
                    pool = [p for p in sorted(all_phones) if p != ph]
                if pool:
                    seq[pos] = rng.choice(pool)
            seq = tuple(seq)
        else:
            seq = tuple(rng.choices(sorted(all_phones), k=target_len))

        if seq in seen or seq in lexicon_phonos:
            continue
        seen.add(seq)
        candidates.append(seq)

    return candidates


# ═══════════════════════════════════════════════════════════════════════════
# 6.  PTAF COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════

def compute_ptaf(phono_tuple, phono_to_words, all_phones):
    """Sum CLEARPOND frequencies of all phonological neighbors (sub/del/add)."""
    total = 0.0
    seen  = set()
    n     = len(phono_tuple)

    for i in range(n):
        orig = phono_tuple[i]
        for ph in all_phones:
            if ph == orig:
                continue
            c = phono_tuple[:i] + (ph,) + phono_tuple[i+1:]
            if c not in seen:
                seen.add(c)
                for _, freq in phono_to_words.get(c, []):
                    total += freq

    for i in range(n):
        c = phono_tuple[:i] + phono_tuple[i+1:]
        if c not in seen:
            seen.add(c)
            for _, freq in phono_to_words.get(c, []):
                total += freq

    for i in range(n + 1):
        for ph in all_phones:
            c = phono_tuple[:i] + (ph,) + phono_tuple[i:]
            if c not in seen:
                seen.add(c)
                for _, freq in phono_to_words.get(c, []):
                    total += freq

    return total


# ═══════════════════════════════════════════════════════════════════════════
# 7.  LOAD INPUT WORDS
# ═══════════════════════════════════════════════════════════════════════════

def load_input(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            word = row.get("Word", "").strip().lower()
            if not word:
                continue
            try:
                ptaf = float(row.get("Word_PTAF", 0))
            except (ValueError, TypeError):
                ptaf = 0.0
            rows.append({"word": word, "target_ptaf": ptaf})
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# 8.  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def run(input_path, clearpond_path, output_path, tolerance, n_candidates, seed):
    rng = random.Random(seed)

    (lexicon, phono_to_words, all_phones,
     consonants, vowels, words_by_length) = load_clearpond(clearpond_path)

    lexicon_phonos = frozenset(v["phono"] for v in lexicon.values())
    lexicon_words  = set(lexicon.keys())

    print("[2/5] Building onset/rime phoneme lookup tables …")
    onset_map, rime_map = build_orth_phono_maps(lexicon, vowels)
    print(f"    {len(onset_map)} onsets | {len(rime_map)} rimes")

    print("[3/5] Loading Wuggy orthographic_english …")
    wuggy_gen = load_wuggy()
    print("    Wuggy ready.")

    input_words = load_input(input_path)

    print(f"\n[4/5] Verifying real-word PTAFs against CLEARPOND …")
    for entry in input_words:
        w = entry["word"]
        if w in lexicon:
            db    = lexicon[w]["eptaf"]
            inp   = entry["target_ptaf"]
            diff  = abs(db - inp) / max(inp, 1e-9) * 100
            flag  = "" if diff < 1 else f"  ⚠ DB has {db:.4f} ({diff:.1f}% off)"
            print(f"    {w:15s}  input={inp:.4f}  db={db:.4f}{flag}")
        else:
            print(f"    {w:15s}  ⚠ NOT FOUND in CLEARPOND")

    print(f"\n[5/5] Generating & scoring pseudowords …")
    print(f"      Tolerance={tolerance*100:.0f}%  |  Wuggy candidates={n_candidates}  |  Seed={seed}\n")

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=_console,
        transient=False,
    ) as progress:
        task = progress.add_task("starting…", total=len(input_words))

        for i, entry in enumerate(input_words):
            word        = entry["word"]
            target_ptaf = entry["target_ptaf"]
            phono_len   = len(lexicon[word]["phono"]) if word in lexicon else len(word)
            source_phono = lexicon[word]["phono"]     if word in lexicon else ()

            status_msg = _WITTY_STATUSES[i % len(_WITTY_STATUSES)]
            progress.update(task, description=f"{word} — {status_msg}")

            # ── Try Wuggy first ───────────────────────────────────────────
            orth_candidates = wuggy_candidates(word, wuggy_gen, n_candidates, lexicon_words)

            if orth_candidates:
                best_pw      = None
                best_phono   = None
                best_ptaf_v  = None
                best_rdiff   = float("inf")

                for pw in orth_candidates:
                    approx = pseudoword_to_phono(
                        pw, onset_map, rime_map, source_phono, vowels)
                    if not approx:
                        continue
                    cptaf = compute_ptaf(approx, phono_to_words, all_phones)
                    rdiff = (abs(cptaf - target_ptaf) / target_ptaf) if target_ptaf > 0 \
                            else abs(cptaf - target_ptaf)
                    if rdiff < best_rdiff:
                        best_rdiff  = rdiff
                        best_pw     = pw
                        best_phono  = approx
                        best_ptaf_v = cptaf

                if best_rdiff <= tolerance:
                    match_status = "MATCHED"
                    marker = "[green]✓[/green]"
                    tag    = ""
                else:
                    match_status = "BEST_AVAILABLE"
                    marker = "[yellow]~[/yellow]"
                    tag    = "  [yellow]BEST_AVAILABLE[/yellow]"

                disc_str = phono_to_disc(best_phono) if best_phono else ""
                progress.print(
                    f"  {marker} [bold]{word:12s}[/bold] → [bold]{best_pw}[/bold]"
                    f"  [dim][{disc_str}]  PTAF={best_ptaf_v:.4f}"
                    f"  diff={best_rdiff*100:.1f}%[/dim]{tag}"
                )

                results.append({
                    "Word":             word,
                    "Word_PTAF":        target_ptaf,
                    "Pseudoword":       best_pw     if best_pw    else "",
                    "Pseudoword_DISC":  disc_str,
                    "Pseudoword_PTAF":  round(best_ptaf_v, 4)      if best_ptaf_v is not None else "",
                    "PTAF_RelDiff_Pct": round(best_rdiff * 100, 2) if best_pw     else "",
                    "Status":           match_status,
                    "Method":           "wuggy",
                })

            else:
                # ── Fallback: phoneme mutation ────────────────────────────
                progress.update(task, description=f"{word} — using phoneme mutation fallback")
                phono_candidates = fallback_candidates(
                    phono_len, all_phones, consonants, vowels,
                    n_candidates * 10, lexicon_phonos, words_by_length, rng
                )

                best_seq    = None
                best_ptaf_v = None
                best_rdiff  = float("inf")

                for seq in phono_candidates:
                    cptaf = compute_ptaf(seq, phono_to_words, all_phones)
                    rdiff = (abs(cptaf - target_ptaf) / target_ptaf) if target_ptaf > 0 \
                            else abs(cptaf - target_ptaf)
                    if rdiff < best_rdiff:
                        best_rdiff  = rdiff
                        best_seq    = seq
                        best_ptaf_v = cptaf

                spelling = disc_to_spelling(best_seq) if best_seq else ""
                disc_str = phono_to_disc(best_seq) if best_seq else ""
                if best_rdiff <= tolerance:
                    match_status = "MATCHED"
                    marker = "[green]✓[/green]"
                    tag    = "  [dim]fallback[/dim]"
                else:
                    match_status = "BEST_AVAILABLE"
                    marker = "[yellow]~[/yellow]"
                    tag    = "  [yellow]BEST_AVAILABLE[/yellow]  [dim]fallback[/dim]"

                progress.print(
                    f"  {marker} [bold]{word:12s}[/bold] → [bold]{spelling}[/bold]"
                    f"  [dim][{disc_str}]  PTAF={best_ptaf_v:.4f}"
                    f"  diff={best_rdiff*100:.1f}%[/dim]{tag}"
                )

                results.append({
                    "Word":             word,
                    "Word_PTAF":        target_ptaf,
                    "Pseudoword":       spelling,
                    "Pseudoword_DISC":  disc_str,
                    "Pseudoword_PTAF":  round(best_ptaf_v, 4)      if best_ptaf_v is not None else "",
                    "PTAF_RelDiff_Pct": round(best_rdiff * 100, 2) if best_seq     else "",
                    "Status":           match_status,
                    "Method":           "fallback",
                })

            progress.advance(task)

    # ── Write output ──────────────────────────────────────────────────────
    print(f"\nWriting results → {output_path}")
    fieldnames = ["Word", "Word_PTAF", "Pseudoword", "Pseudoword_DISC",
                  "Pseudoword_PTAF", "PTAF_RelDiff_Pct", "Status", "Method"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    matched_n   = sum(1 for r in results if r["Status"] == "MATCHED")
    available_n = sum(1 for r in results if r["Status"] == "BEST_AVAILABLE")
    print(f"\nDone. {matched_n}/{len(results)} MATCHED within {tolerance*100:.0f}% tolerance, "
          f"{available_n} accepted as BEST_AVAILABLE.")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate PTAF-matched pseudowords using Wuggy + CLEARPOND."
    )
    parser.add_argument("--input",      required=True)
    parser.add_argument("--clearpond",  required=True)
    parser.add_argument("--output",     default="pseudowords_output.csv")
    parser.add_argument("--tolerance",  type=float, default=0.20,
                        help="Relative PTAF tolerance. Default: 0.20 (20%%).")
    parser.add_argument("--candidates", type=int,   default=200,
                        help="Wuggy candidates per word (default 200).")
    parser.add_argument("--seed",       type=int,   default=42)
    args = parser.parse_args()

    run(args.input, args.clearpond, args.output,
        args.tolerance, args.candidates, args.seed)
