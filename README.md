# Pseudoword Generator — PTAF Matched

Generates pseudowords for psycholinguistic experiments. For each real English
word in an input CSV, the script produces a pronounceable, word-like pseudoword
whose **Phonological Total All-neighbors Frequency (PTAF)** is matched to the
real word's PTAF within a configurable tolerance.

---

## Requirements

- Python 3.10+
- [CLEARPOND English database](https://clearpond.northwestern.edu/) (offline download)
- [Wuggy](https://github.com/WuggyCode/wuggy) pseudoword generator

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install wuggy
```

The first run automatically downloads the Wuggy `orthographic_english` language
plugin (~1 MB) from the Wuggy repository.

---

## Input files

### Your word list (`--input`)

A CSV with at minimum these two columns:

| Column     | Description                                      |
|------------|--------------------------------------------------|
| `Word`     | Real English word (lowercase)                    |
| `Word_PTAF`| Phonological Total All-neighbors Frequency (ePTAF from CLEARPOND) |

Example:

```
Word,Word_PTAF
chair,220.2279
stone,6.9662
brick,42.6882
```

### CLEARPOND English database (`--clearpond`)

Download the offline English database from
[clearpond.northwestern.edu](https://clearpond.northwestern.edu/).
The expected file is `englishCPdatabase2.txt` (tab-delimited, ~28 k words).
The companion header file `clearpondHeaders_EN.txt` must sit in the same
directory as the database file.

Place both files under `data/englishCPdatabase2/`:

```
data/
└── englishCPdatabase2/
    ├── englishCPdatabase2.txt
    └── clearpondHeaders_EN.txt
```

---

## Usage

```bash
.venv/bin/python3 pseudowords.py \
    --input    data/real_words4.csv \
    --clearpond data/englishCPdatabase2/englishCPdatabase2.txt \
    --output   pseudowords_output.csv \
    --tolerance 0.20 \
    --candidates 200 \
    --seed 42
```

### Options

| Flag           | Default | Description |
|----------------|---------|-------------|
| `--input`      | *(required)* | Input CSV with `Word` and `Word_PTAF` columns |
| `--clearpond`  | *(required)* | Path to `englishCPdatabase2.txt` |
| `--output`     | `pseudowords_output.csv` | Output CSV path |
| `--tolerance`  | `0.20` | Maximum allowed relative PTAF difference (0.20 = 20%) |
| `--candidates` | `200` | Number of Wuggy pseudoword candidates evaluated per word |
| `--seed`       | `42` | Random seed (affects fallback generator only) |

---

## Output

The output CSV contains one row per input word:

| Column             | Description |
|--------------------|-------------|
| `Word`             | Original real word |
| `Word_PTAF`        | Target PTAF (from your input CSV) |
| `Pseudoword`       | Generated pseudoword (orthographic, readable) |
| `Pseudoword_DISC`  | Pseudoword phoneme sequence in CLEARPOND DISC notation |
| `Pseudoword_PTAF`  | Computed PTAF of the pseudoword |
| `PTAF_RelDiff_Pct` | Relative PTAF difference in percent |
| `Status`           | `MATCHED` — within tolerance · `BEST_AVAILABLE` — best found, exceeds tolerance |
| `Method`           | `wuggy` — Wuggy-generated · `fallback` — phoneme-mutation fallback |

**`BEST_AVAILABLE`** rows should be reviewed manually before use in an
experiment. They are the closest match Wuggy could find but lie outside the
requested tolerance.

---

## How it works

### 1. Load CLEARPOND

The CLEARPOND English database is loaded into memory, giving for each word:
- its DISC phoneme sequence (dot-separated tokens, e.g. `s.t.oU.n`)
- its lexical frequency (SUBTLEX)
- its pre-computed `ePTAF`

A reverse index `phoneme_tuple → [(word, freq)]` is built for fast
neighborhood lookup.

### 2. DISC phoneme format

CLEARPOND uses a **dot-separated DISC** notation where each token between
dots is one phoneme. Multi-character tokens represent single phonemes:

| Token | Phoneme | Example |
|-------|---------|---------|
| `tS`  | /tʃ/    | ch in *chair* |
| `dZ`  | /dʒ/    | j in *jump* |
| `oU`  | /oʊ/    | o in *stone* |
| `eI`  | /eɪ/    | a in *cable* |
| `r0`  | /r/     | r in *brick* |
| `36`  | /ɜː/    | ur in *journal* |

### 3. Build onset/rime phoneme maps

For every CLEARPOND word the script extracts its orthographic **onset**
(letters before the first vowel) and **rime** (first vowel onward), and the
corresponding phoneme onset/rime split. The most common phoneme mapping for
each orthographic pattern is stored:

```
onset_map["ch"] → ('tS',)
rime_map["arp"]  → ('Ar', 'p')
```

These maps are used later to approximate the phoneme sequence of any
Wuggy pseudoword.

### 4. Generate candidates with Wuggy

[Wuggy](https://github.com/WuggyCode/wuggy) generates pseudowords using a
**subsyllabic substitution** strategy: it keeps 2/3 of the word's subsyllabic
segments (onset, nucleus, coda) and replaces the rest with statistically
plausible English alternatives. This guarantees:
- correct letter length
- natural English phonotactics
- the pseudoword does not exist in the English lexicon

Up to `--candidates` pseudowords are generated per real word.

**Fallback:** if a word is not in Wuggy's lexicon, the script falls back to a
phoneme-mutation strategy: it randomly mutates 1–3 phonemes of a same-length
real-word template, preserving consonant/vowel category at each position.

### 5. Approximate phoneme sequence

For each Wuggy candidate the script looks up its orthographic onset and rime
in the maps from step 3 to construct an approximate DISC phoneme sequence.
If the rime is not found in the map (common for novel pseudoword rimes), the
source word's phoneme rime is used as the fallback — this keeps the phoneme
count and neighborhood structure close to the original.

### 6. Compute PTAF

PTAF is computed for each candidate phoneme sequence by iterating over all
phonological neighbors — sequences differing by exactly one **substitution**,
**deletion**, or **addition** — and summing their CLEARPOND lexical
frequencies. This mirrors CLEARPOND's own `ePTAF` definition.

### 7. Select best match

The candidate with the smallest relative PTAF difference from the target is
selected. If it falls within `--tolerance`, it is marked `MATCHED`. Otherwise
the best available candidate is accepted and marked `BEST_AVAILABLE`.

---

## Notes

- **Phoneme counts** in CLEARPOND reflect a British English analysis in which
  diphthongs (e.g. /eɪ/, /oʊ/) and affricates (e.g. /tʃ/) count as single
  phonemes. Generated pseudowords respect this convention.
- **PTAF approximation**: because Wuggy operates orthographically, the
  pseudoword's phoneme sequence is inferred rather than looked up. For most
  common English patterns the approximation is accurate; `BEST_AVAILABLE`
  rows are the cases where the approximation diverges.
- The CLEARPOND database and the `.venv` directory are excluded from version
  control (see `.gitignore`). Download CLEARPOND separately and place it as
  described above.
