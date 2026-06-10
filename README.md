# Pseudoword Generator — PTAF & Orthographic Stats Matched

Generates pseudowords for psycholinguistic experiments. For each real English word in an input CSV, the script produces a pronounceable, word-like pseudoword whose **Phonological Total All-neighbors Frequency (PTAF)** is matched to the real word's target PTAF, while dynamically calculating orthographic neighborhood statistics (**OTAN**, **OTAF**) and reporting difference metrics.

---

## Requirements

- Python 3.10+
- [CLEARPOND English database](https://clearpond.northwestern.edu/) (offline download)
- [Wuggy](https://github.com/WuggyCode/wuggy) pseudoword generator
- [Rich](https://github.com/Textualize/rich) terminal rendering library

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install wuggy rich
```

The first run automatically downloads the Wuggy `orthographic_english` language plugin (~1 MB) from the Wuggy repository.

---

## Input files

### Your word list (`--input`)

A CSV with at minimum the following columns (extra columns are ignored, and statistics rows like `MEAN` or `T-test` are automatically skipped):

| Column           | Description                                                        |
|------------------|--------------------------------------------------------------------|
| `Word`           | Real English word (lowercase)                                      |
| `Length (Ortho)` | Orthographic letter length of the word                             |
| `Word_PTAN`      | Phonological Total All-neighbors Size (PTAN from CLEARPOND)        |
| `Word_PTAF`      | Phonological Total All-neighbors Frequency (ePTAF mean from CLEARPOND) |
| `Word_OTAN`      | Orthographic Total All-neighbors Size (OTAN from CLEARPOND)        |
| `Word_OTAF`      | Orthographic Total All-neighbors Frequency (eOTAF mean from CLEARPOND) |

Example (`data/words.csv`):

```csv
Word,Length (Ortho),Word_PTAN,Word_PTAF,Word_OTAN,Word_OTAF
chair,5,37,220.2279,7,27.6163
stone,5,18,6.9662,12,15.1356
brick,5,20,42.6882,9,11.2505
```

### CLEARPOND English database (`--clearpond`)

Download the offline English database from [clearpond.northwestern.edu](https://clearpond.northwestern.edu/).
The expected file is `englishCPdatabase2.txt` (tab-delimited, ~28 k words).
The companion header file `clearpondHeaders_EN.txt` must sit in the same directory as the database file.

Place both files under `data/englishCPdatabase2/`:

```
data/
└── englishCPdatabase2/
    ├── englishCPdatabase2.txt
    └── clearpondHeaders_EN.txt
```

---

## Usage

The script reads the clean input CSV file and writes its output to a separate output CSV file, leaving the input file untouched:

```bash
.venv/bin/python pseudowords.py \
    --input      data/words.csv \
    --clearpond  data/englishCPdatabase2/englishCPdatabase2.txt \
    --output     data/pseudowords_output.csv \
    --tolerance  0.20 \
    --candidates 200 \
    --seed       42
```

### Options

| Flag           | Default | Description |
|----------------|---------|-------------|
| `--input`      | *(required)* | Clean input CSV with real words and statistics |
| `--clearpond`  | *(required)* | Path to `englishCPdatabase2.txt` |
| `--output`     | `pseudowords_output.csv` | Output CSV path (separate from the input file, e.g. `data/pseudowords_output.csv`) |
| `--tolerance`  | `0.20` | Maximum allowed relative PTAF difference (0.20 = 20%) |
| `--candidates` | `200` | Number of Wuggy pseudoword candidates evaluated per word |
| `--seed`       | `42` | Random seed (affects fallback generator only) |

---

## Output Columns

The output CSV contains a comprehensive set of matched results and statistics:

| Column | Type | Description |
|--------|------|-------------|
| `Word` | `str` | Original real word |
| `Length (Ortho)` | `int` | Real word orthographic length |
| `Word_PTAN` | `int` | Real word phonological neighborhood size |
| `Word_PTAF` | `float` | Real word precalculated target PTAF mean |
| `Word_OTAN` | `int` | Real word orthographic neighborhood size |
| `Word_OTAF` | `float` | Real word precalculated target OTAF mean |
| `Pseudoword` | `str` | Generated pseudoword (orthographic, readable) |
| `Pseudoword_PTAN` | `int` | Computed phonological neighborhood size of the pseudoword |
| `Pseudoword_PTAF` | `float` | Computed PTAF frequency sum of the pseudoword |
| `Pseudoword_OTAN` | `int` | Computed Coltheart's distance-1 orthographic neighborhood size of the pseudoword |
| `Pseudoword_OTAF` | `float` | Computed orthographic neighborhood frequency **mean** of the pseudoword |
| `PTAF_RelDiff_Pct` | `float` | Relative PTAF difference in percent between the pseudoword PTAF sum and the real word PTAF mean (how they are deterministically matched) |
| `OTAN_Diff` | `int` | Direct integer difference in orthographic neighborhood size: `Pseudoword_OTAN - Word_OTAN` |
| `OTAF_RelDiff_Pct` | `float` | Relative difference in percent between the pseudoword OTAF mean and the real word OTAF mean |
| `Status` | `str` | `MATCHED` (within tolerance) or `BEST_AVAILABLE` (closest match found, exceeds tolerance) |
| `Method` | `str` | `wuggy` (Wuggy-generated) or `fallback` (phoneme-mutation fallback) |

---

## How it works

### 1. Load CLEARPOND

The CLEARPOND English database is loaded into memory, extracting the word's orthographic, phonotactic, and neighborhood frequency records. A reverse index `phoneme_tuple → [(word, freq)]` is built for fast neighbor lookups.

### 2. DISC phoneme format

CLEARPOND uses a **dot-separated DISC** notation where each token is a single phoneme. Multi-character tokens represent single phonemes:

| Token | Phoneme | Example |
|-------|---------|---------|
| `tS`  | /tʃ/    | ch in *chair* |
| `dZ`  | /dʒ/    | j in *jump* |
| `oU`  | /oʊ/    | o in *stone* |
| `eI`  | /eɪ/    | a in *cable* |
| `r0`  | /r/     | r in *brick* |
| `36`  | /ɜː/    | ur in *journal* |

### 3. Build onset/rime phoneme maps

For every CLEARPOND word, the script extracts its orthographic **onset** (letters before the first vowel) and **rime** (first vowel onward) to build onset/rime phone mappings:
```
onset_map["ch"] → ('tS',)
rime_map["arp"]  → ('Ar', 'p')
```
These are used to approximate the phoneme sequence of any Wuggy pseudoword.

### 4. Generate candidates with Wuggy

[Wuggy](https://github.com/WuggyCode/wuggy) generates candidate pseudowords using **subsyllabic substitution** (onset, nucleus, coda), guaranteeing English-like phonotactics and non-existence in the English lexicon.

**Fallback:** If Wuggy cannot handle a word, the script falls back to mutating 1–3 phonemes of a same-length real-word template while preserving consonant/vowel category at each mutated position.

### 5. Deterministic Scoring Logic

To remain deterministic and compatible with the original matching results:
- **PTAF Matching:** The script computes `cptaf_sum` (the frequency sum of all phonological neighbors at edit distance = 1) and compares it directly with the precalculated CLEARPOND database mean `target_ptaf` (`ePTAF`). While mathematically counter-intuitive, this direct sum-to-mean matching logic ensures original matches (like `chair` → `charp` and `stone` → `stoms`) are produced.
- **PTAF Output Values:** `Pseudoword_PTAF` writes the frequency sum, and `PTAF_RelDiff_Pct` represents the direct relative difference between this sum and the target.

### 6. Orthographic Neighborhood Calculations

For the selected best pseudoword, orthographic statistics are computed dynamically using Coltheart's distance-1 definition:
- **Orthographic Neighborhood Size (`Pseudoword_OTAN`):** Count of unique real CLEARPOND words obtained by exactly one single-letter deletion, substitution, or insertion.
- **Orthographic Neighborhood Frequency (`Pseudoword_OTAF`):** The average (mean) frequency of those orthographic neighbors, computed as `OTAF_sum / OTAN` to remain mathematically consistent with the database precalculated mean `Word_OTAF`.
- **OTAN Difference (`OTAN_Diff`):** The direct integer difference `Pseudoword_OTAN - Word_OTAN`.
- **OTAF Relative Difference (`OTAF_RelDiff_Pct`):** Relative difference in percent between the pseudoword and real word's orthographic mean frequencies.

---

## Notes

- **Static Type Safety:** Fully type-safe and validated using the `pyrefly` static type analysis.
- **Safety:** The clean input file `data/words.csv` remains untouched, and all generation outputs are piped to your designated output file (e.g. `data/pseudowords_output.csv`).
