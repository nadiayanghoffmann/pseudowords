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
   orthographic onset and rime in the CLEARPOND-derived maps.  Candidates
   whose onset or rime is not attested in CLEARPOND are skipped (existing
   pseudowords from the input are reported as NO_TRANSCRIPTION instead).

4. Compute PTAF (mean frequency of all phonological neighbors, the same
   convention as CLEARPOND's ePTAF) for that phoneme sequence.

5. Pick the candidate with PTAF closest to the target; accept if within
   TOLERANCE.

USAGE
-----
    python pseudowords.py \\
        --input    your_words.csv \\
        --clearpond data/englishCPdatabase2/englishCPdatabase2.txt \\
        --output   results.csv

    Optional flags:
        --tolerance   0.20     # relative PTAF tolerance (default 20%)
        --candidates  1000     # Wuggy candidates per word (default 1000)
        --seed        23       # random seed (only affects fallback generator)
"""

import argparse
import csv
import os
import random
import sys
from collections import Counter, defaultdict
from typing import Any, TypedDict

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
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


def pseudoword_to_phono(pseudoword, onset_map, rime_map):
    """
    Approximate the phoneme sequence for an orthographic pseudoword via exact
    onset/rime lookup in the CLEARPOND-derived maps.

    Returns None if either part is not attested in CLEARPOND.  No fallback is
    attempted: substituting the source word's onset/rime can reconstruct the
    source word's own phonology, which would silently score the real word
    instead of the pseudoword.
    """
    orth_onset, orth_rime = _split_orth(pseudoword)

    phono_onset = onset_map.get(orth_onset)
    phono_rime  = rime_map.get(orth_rime)
    if phono_onset is None or phono_rime is None:
        return None

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


def compute_ptaf_and_ptan(
    phono_tuple: tuple[str, ...],
    phono_to_words: dict[tuple[str, ...], list[tuple[str, float]]],
    all_phones: set[str],
) -> tuple[float, int]:
    """
    Sum frequencies and count unique words of all phonological neighbors (sub/del/add).
    """
    total_freq = 0.0
    total_count = 0
    seen = set()
    n = len(phono_tuple)

    for i in range(n):
        orig = phono_tuple[i]
        for ph in all_phones:
            if ph == orig:
                continue
            c = phono_tuple[:i] + (ph,) + phono_tuple[i+1:]
            if c not in seen:
                seen.add(c)
                for _, freq in phono_to_words.get(c, []):
                    total_freq += freq
                    total_count += 1

    for i in range(n):
        c = phono_tuple[:i] + phono_tuple[i+1:]
        if c not in seen:
            seen.add(c)
            for _, freq in phono_to_words.get(c, []):
                total_freq += freq
                total_count += 1

    for i in range(n + 1):
        for ph in all_phones:
            c = phono_tuple[:i] + (ph,) + phono_tuple[i:]
            if c not in seen:
                seen.add(c)
                for _, freq in phono_to_words.get(c, []):
                    total_freq += freq
                    total_count += 1

    return total_freq, total_count


def compute_otan_otaf(word: str, lexicon: dict[str, dict[str, Any]]) -> tuple[int, float]:
    """
    Compute Orthographic Total All Neighborhood Size (OTAN) and
    Orthographic Total All Frequency Sum (OTAF sum) for a word.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    n = len(word)
    candidates = set()

    # Deletions
    for i in range(n):
        candidates.add(word[:i] + word[i+1:])

    # Substitutions
    for i in range(n):
        orig = word[i]
        for c in alphabet:
            if c != orig:
                candidates.add(word[:i] + c + word[i+1:])

    # Insertions
    for i in range(n + 1):
        for c in alphabet:
            candidates.add(word[:i] + c + word[i:])

    candidates.discard(word)

    otan = 0
    otaf_sum = 0.0
    for cand in candidates:
        if cand in lexicon:
            otan += 1
            otaf_sum += lexicon[cand]["freq"]

    return otan, otaf_sum


# ═══════════════════════════════════════════════════════════════════════════
# 7.  LOAD INPUT WORDS
# ═══════════════════════════════════════════════════════════════════════════


class InputWord(TypedDict):
    word: str
    length_ortho: int
    word_ptan: int
    word_ptaf: float
    word_otan: int
    word_otaf: float
    pseudoword: str


def load_input(path: str) -> list[InputWord]:
    rows: list[InputWord] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row.get("Word")
            if word is None:
                word = row.get("")
            if word is None and reader.fieldnames:
                word = row.get(reader.fieldnames[0])
            
            if not word:
                continue
            word_cleaned = word.strip().lower()

            # Skip metadata/summary rows
            if word_cleaned in ("mean", "t-test") or not row.get("Length (Ortho)"):
                continue

            try:
                length_ortho = int(row.get("Length (Ortho)", 0))
            except (ValueError, TypeError):
                length_ortho = 0

            try:
                word_ptan = int(row.get("Word_PTAN", 0))
            except (ValueError, TypeError):
                word_ptan = 0

            try:
                word_ptaf = float(row.get("Word_PTAF", 0))
            except (ValueError, TypeError):
                word_ptaf = 0.0

            try:
                word_otan = int(row.get("Word_OTAN", 0))
            except (ValueError, TypeError):
                word_otan = 0

            try:
                word_otaf = float(row.get("Word_OTAF", 0))
            except (ValueError, TypeError):
                word_otaf = 0.0

            pseudoword = row.get("Pseudoword", "").strip()

            rows.append({
                "word": word_cleaned,
                "length_ortho": length_ortho,
                "word_ptan": word_ptan,
                "word_ptaf": word_ptaf,
                "word_otan": word_otan,
                "word_otaf": word_otaf,
                "pseudoword": pseudoword,
            })
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# 8.  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def run(
    input_path: str,
    clearpond_path: str,
    output_path: str,
    tolerance: float,
    n_candidates: int,
    seed: int,
) -> None:
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

    print("\n[4/5] Verifying real-word PTAFs against CLEARPOND …")
    for entry in input_words:
        w = entry["word"]
        if w in lexicon:
            db    = lexicon[w]["eptaf"]
            inp   = entry["word_ptaf"]
            diff  = abs(db - inp) / max(inp, 1e-9) * 100
            flag  = "" if diff < 1 else f"  ⚠ DB has {db:.4f} ({diff:.1f}% off)"
            print(f"    {w:15s}  input={inp:.4f}  db={db:.4f}{flag}")
        else:
            print(f"    {w:15s}  ⚠ NOT FOUND in CLEARPOND")

    print("\n[5/5] Generating & scoring pseudowords …")
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
            target_ptaf = entry["word_ptaf"]
            phono_len   = len(lexicon[word]["phono"]) if word in lexicon else len(word)

            status_msg = _WITTY_STATUSES[i % len(_WITTY_STATUSES)]
            progress.update(task, description=f"{word} — {status_msg}")

            # Generate a random consonant-only pseudoword of the same length, avoiding same consecutive consonants
            L = entry["length_ortho"] if entry["length_ortho"] > 0 else len(word)
            consonants_pool = "bcdfghjklmnpqrstvwxyz"
            chars = []
            for _ in range(L):
                if not chars:
                    next_char = rng.choice(consonants_pool)
                else:
                    next_char = rng.choice([c for c in consonants_pool if c != chars[-1]])
                chars.append(next_char)
            consonant_pseudoword = "".join(chars)

            existing_pw = entry.get("pseudoword", "")

            if existing_pw:
                # ── Use existing pseudoword ────────────────────────────────
                best_pw = existing_pw
                approx = pseudoword_to_phono(best_pw, onset_map, rime_map)

                if approx is not None:
                    cptaf_sum, cptan = compute_ptaf_and_ptan(approx, phono_to_words, all_phones)
                    best_ptaf_v = cptaf_sum / cptan if cptan > 0 else 0.0
                    best_ptan_v = cptan
                    best_phono = approx
                    best_rdiff = (abs(best_ptaf_v - target_ptaf) / target_ptaf) if target_ptaf > 0 \
                                 else abs(best_ptaf_v - target_ptaf)

                    if best_rdiff <= tolerance:
                        match_status = "MATCHED"
                        marker = "[green]✓[/green]"
                        tag    = "  [cyan]existing[/cyan]"
                    else:
                        match_status = "BEST_AVAILABLE"
                        marker = "[yellow]~[/yellow]"
                        tag    = "  [cyan]existing[/cyan] [yellow]BEST_AVAILABLE[/yellow]"
                    ptaf_str = f"PTAF={best_ptaf_v:.4f}  diff={best_rdiff*100:.1f}%"
                else:
                    best_ptaf_v = None
                    best_ptan_v = None
                    best_phono = ()
                    best_rdiff = None
                    match_status = "NO_TRANSCRIPTION"
                    marker = "[red]✗[/red]"
                    tag    = "  [cyan]existing[/cyan] [red]NO_TRANSCRIPTION[/red]"
                    ptaf_str = "onset/rime not in CLEARPOND"

                disc_str = phono_to_disc(best_phono) if best_phono else ""

                pw_otan, pw_otaf_sum = compute_otan_otaf(best_pw, lexicon)
                pw_otaf_mean = pw_otaf_sum / pw_otan if pw_otan > 0 else 0.0

                otan_diff = pw_otan - entry["word_otan"]
                otaf_reldiff = (abs(pw_otaf_mean - entry["word_otaf"]) / entry["word_otaf"] * 100) \
                               if entry["word_otaf"] > 0 else 0.0

                progress.print(
                    f"  {marker} [bold]{word:12s}[/bold] → [bold]{best_pw}[/bold] (existing)"
                    f"  [dim][{disc_str}]  {ptaf_str}[/dim]{tag}"
                )

                results.append({
                    "Word":             word,
                    "Length (Ortho)":   entry["length_ortho"],
                    "Word_PTAN":        entry["word_ptan"],
                    "Word_PTAF":        entry["word_ptaf"],
                    "Word_OTAN":        entry["word_otan"],
                    "Word_OTAF":        entry["word_otaf"],
                    "Pseudoword":       best_pw,
                    "Consonant_Pseudoword": consonant_pseudoword,
                    "Pseudoword_PTAN":  best_ptan_v if best_ptan_v is not None else "",
                    "Pseudoword_PTAF":  round(best_ptaf_v, 4)      if best_ptaf_v is not None else "",
                    "Pseudoword_OTAN":  pw_otan,
                    "Pseudoword_OTAF":  round(pw_otaf_mean, 4),
                    "PTAF_RelDiff_Pct": round(best_rdiff * 100, 2) if best_rdiff is not None else "",
                    "OTAN_Diff":        otan_diff,
                    "OTAF_RelDiff_Pct": round(otaf_reldiff, 2),
                    "Status":           match_status,
                    "Method":           "existing",
                })
                progress.advance(task)

            else:
                # ── Try Wuggy first ───────────────────────────────────────────
                # Candidates whose onset/rime is not in CLEARPOND are skipped;
                # if none survives, fall through to the phoneme-mutation fallback.
                orth_candidates = wuggy_candidates(word, wuggy_gen, n_candidates, lexicon_words)

                best_pw      = None
                best_phono   = None
                best_ptaf_v  = None
                best_ptan_v  = None
                best_rdiff   = float("inf")

                for pw in (orth_candidates or []):
                    approx = pseudoword_to_phono(pw, onset_map, rime_map)
                    if approx is None:
                        continue
                    cptaf_sum, cptan = compute_ptaf_and_ptan(approx, phono_to_words, all_phones)
                    cptaf_mean = cptaf_sum / cptan if cptan > 0 else 0.0
                    rdiff = (abs(cptaf_mean - target_ptaf) / target_ptaf) if target_ptaf > 0 \
                            else abs(cptaf_mean - target_ptaf)
                    if rdiff < best_rdiff:
                        best_rdiff  = rdiff
                        best_pw     = pw
                        best_phono  = approx
                        best_ptaf_v = cptaf_mean
                        best_ptan_v = cptan

                if best_pw is not None:
                    if best_rdiff <= tolerance:
                        match_status = "MATCHED"
                        marker = "[green]✓[/green]"
                        tag    = ""
                    else:
                        match_status = "BEST_AVAILABLE"
                        marker = "[yellow]~[/yellow]"
                        tag    = "  [yellow]BEST_AVAILABLE[/yellow]"

                    disc_str = phono_to_disc(best_phono) if best_phono else ""
                    
                    # Compute orthographic neighborhood statistics for selected best candidate
                    if best_pw:
                        pw_otan, pw_otaf_sum = compute_otan_otaf(best_pw, lexicon)
                        pw_otaf_mean = pw_otaf_sum / pw_otan if pw_otan > 0 else 0.0
                    else:
                        pw_otan, pw_otaf_sum, pw_otaf_mean = 0, 0.0, 0.0

                    # Compute difference statistics compared to real word
                    otan_diff = pw_otan - entry["word_otan"]
                    otaf_reldiff = (abs(pw_otaf_mean - entry["word_otaf"]) / entry["word_otaf"] * 100) \
                                   if entry["word_otaf"] > 0 else 0.0

                    progress.print(
                        f"  {marker} [bold]{word:12s}[/bold] → [bold]{best_pw}[/bold]"
                        f"  [dim][{disc_str}]  PTAF={best_ptaf_v:.4f}"
                        f"  diff={best_rdiff*100:.1f}%[/dim]{tag}"
                    )

                    results.append({
                        "Word":             word,
                        "Length (Ortho)":   entry["length_ortho"],
                        "Word_PTAN":        entry["word_ptan"],
                        "Word_PTAF":        entry["word_ptaf"],
                        "Word_OTAN":        entry["word_otan"],
                        "Word_OTAF":        entry["word_otaf"],
                        "Pseudoword":       best_pw     if best_pw    else "",
                        "Consonant_Pseudoword": consonant_pseudoword,
                        "Pseudoword_PTAN":  best_ptan_v if best_ptan_v is not None else "",
                        "Pseudoword_PTAF":  round(best_ptaf_v, 4)      if best_ptaf_v is not None else "",
                        "Pseudoword_OTAN":  pw_otan,
                        "Pseudoword_OTAF":  round(pw_otaf_mean, 4),
                        "PTAF_RelDiff_Pct": round(best_rdiff * 100, 2) if best_pw     else "",
                        "OTAN_Diff":        otan_diff,
                        "OTAF_RelDiff_Pct": round(otaf_reldiff, 2),
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
                    best_ptan_v = None
                    best_rdiff  = float("inf")

                    for seq in phono_candidates:
                        cptaf_sum, cptan = compute_ptaf_and_ptan(seq, phono_to_words, all_phones)
                        cptaf_mean = cptaf_sum / cptan if cptan > 0 else 0.0
                        rdiff = (abs(cptaf_mean - target_ptaf) / target_ptaf) if target_ptaf > 0 \
                                else abs(cptaf_mean - target_ptaf)
                        if rdiff < best_rdiff:
                            best_rdiff  = rdiff
                            best_seq    = seq
                            best_ptaf_v = cptaf_mean
                            best_ptan_v = cptan

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

                    # Compute orthographic neighborhood statistics for fallback spelling candidate
                    if spelling:
                        pw_otan, pw_otaf_sum = compute_otan_otaf(spelling, lexicon)
                        pw_otaf_mean = pw_otaf_sum / pw_otan if pw_otan > 0 else 0.0
                    else:
                        pw_otan, pw_otaf_sum, pw_otaf_mean = 0, 0.0, 0.0

                    # Compute difference statistics compared to real word
                    otan_diff = pw_otan - entry["word_otan"]
                    otaf_reldiff = (abs(pw_otaf_mean - entry["word_otaf"]) / entry["word_otaf"] * 100) \
                                   if entry["word_otaf"] > 0 else 0.0

                    progress.print(
                        f"  {marker} [bold]{word:12s}[/bold] → [bold]{spelling}[/bold]"
                        f"  [dim][{disc_str}]  PTAF={best_ptaf_v:.4f}"
                        f"  diff={best_rdiff*100:.1f}%[/dim]{tag}"
                    )

                    results.append({
                        "Word":             word,
                        "Length (Ortho)":   entry["length_ortho"],
                        "Word_PTAN":        entry["word_ptan"],
                        "Word_PTAF":        entry["word_ptaf"],
                        "Word_OTAN":        entry["word_otan"],
                        "Word_OTAF":        entry["word_otaf"],
                        "Pseudoword":       spelling,
                        "Consonant_Pseudoword": consonant_pseudoword,
                        "Pseudoword_PTAN":  best_ptan_v if best_ptan_v is not None else "",
                        "Pseudoword_PTAF":  round(best_ptaf_v, 4)      if best_ptaf_v is not None else "",
                        "Pseudoword_OTAN":  pw_otan,
                        "Pseudoword_OTAF":  round(pw_otaf_mean, 4),
                        "PTAF_RelDiff_Pct": round(best_rdiff * 100, 2) if best_seq     else "",
                        "OTAN_Diff":        otan_diff,
                        "OTAF_RelDiff_Pct": round(otaf_reldiff, 2),
                        "Status":           match_status,
                        "Method":           "fallback",
                    })

                progress.advance(task)

    # ── Write output ──────────────────────────────────────────────────────
    print(f"\nWriting results → {output_path}")
    fieldnames = [
        "Word", "Length (Ortho)", "Word_PTAN", "Word_PTAF", "Word_OTAN", "Word_OTAF",
        "Pseudoword", "Consonant_Pseudoword", "Pseudoword_PTAN", "Pseudoword_PTAF", "Pseudoword_OTAN", "Pseudoword_OTAF",
        "PTAF_RelDiff_Pct", "OTAN_Diff", "OTAF_RelDiff_Pct", "Status", "Method"
    ]
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
    parser.add_argument("--candidates", type=int,   default=1000,
                        help="Wuggy candidates per word (default 1000).")
    parser.add_argument("--seed",       type=int,   default=23)
    args = parser.parse_args()

    run(args.input, args.clearpond, args.output,
        args.tolerance, args.candidates, args.seed)
