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
    --candidates 1000 \
    --seed       23
```

### Options

| Flag           | Default | Description |
|----------------|---------|-------------|
| `--input`      | *(required)* | Clean input CSV with real words and statistics |
| `--clearpond`  | *(required)* | Path to `englishCPdatabase2.txt` |
| `--output`     | `pseudowords_output.csv` | Output CSV path (separate from the input file, e.g. `data/pseudowords_output.csv`) |
| `--tolerance`  | `0.20` | Maximum allowed relative PTAF difference (0.20 = 20%) |
| `--candidates` | `1000` | Number of Wuggy pseudoword candidates evaluated per word |
| `--seed`       | `23` | Random seed (affects fallback generator only) |

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
| `Consonant_Pseudoword` | `str` | Random consonant-only pseudoword of the same length |
| `Pseudoword_PTAN` | `int` | Computed phonological neighborhood size of the pseudoword |
| `Pseudoword_PTAF` | `float` | Computed phonological neighborhood frequency **mean** of the pseudoword (same convention as CLEARPOND's `ePTAF`) |
| `Pseudoword_OTAN` | `int` | Computed Coltheart's distance-1 orthographic neighborhood size of the pseudoword |
| `Pseudoword_OTAF` | `float` | Computed orthographic neighborhood frequency **mean** of the pseudoword |
| `PTAF_RelDiff_Pct` | `float` | Relative difference in percent between the pseudoword and real word PTAF means (the matching criterion) |
| `OTAN_Diff` | `int` | Direct integer difference in orthographic neighborhood size: `Pseudoword_OTAN - Word_OTAN` |
| `OTAF_RelDiff_Pct` | `float` | Relative difference in percent between the pseudoword OTAF mean and the real word OTAF mean |
| `Status` | `str` | `MATCHED` (within tolerance), `BEST_AVAILABLE` (closest match found, exceeds tolerance), or `NO_TRANSCRIPTION` (existing pseudoword whose onset/rime is not attested in CLEARPOND, so no phonological statistics could be computed) |
| `Method` | `str` | `existing` (pseudoword taken from the input), `wuggy` (Wuggy-generated), or `fallback` (phoneme-mutation fallback) |

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
If a pseudoword's onset or rime is not attested in CLEARPOND, no transcription
is attempted: generated candidates are skipped, and existing pseudowords from
the input are reported with `Status = NO_TRANSCRIPTION`. (Guessing — e.g.
reusing the source word's onset/rime — could reconstruct the source word's own
phonology and silently score the real word instead of the pseudoword.)

### 4. Generate candidates with Wuggy

[Wuggy](https://github.com/WuggyCode/wuggy) generates candidate pseudowords using **subsyllabic substitution** (onset, nucleus, coda), guaranteeing English-like phonotactics and non-existence in the English lexicon.

**Fallback:** If Wuggy cannot handle a word, or none of its candidates has a transcribable onset/rime, the script falls back to mutating 1–3 phonemes of a same-length real-word template while preserving consonant/vowel category at each mutated position.

### 5. Scoring & Matching

- **PTAF Matching:** For each candidate, the script enumerates all phonological neighbors at edit distance 1 (one-phoneme substitution, deletion, or insertion) and computes `Pseudoword_PTAF` as the **mean** frequency of those neighbors (`frequency sum ÷ neighbor count`) — the same convention as CLEARPOND's precalculated `ePTAF`, so the pseudoword statistic is directly comparable to the `Word_PTAF` target. The candidate whose mean lies closest to the target wins, and is accepted as `MATCHED` if the relative difference is within `--tolerance`.
- **PTAF Output Values:** `Pseudoword_PTAF` writes the neighbor-frequency mean, and `PTAF_RelDiff_Pct` is the relative difference between this mean and the target mean.

### 6. Orthographic Neighborhood Calculations

For the selected best pseudoword, orthographic statistics are computed dynamically using Coltheart's distance-1 definition:
- **Orthographic Neighborhood Size (`Pseudoword_OTAN`):** Count of unique real CLEARPOND words obtained by exactly one single-letter deletion, substitution, or insertion.
- **Orthographic Neighborhood Frequency (`Pseudoword_OTAF`):** The average (mean) frequency of those orthographic neighbors, computed as `OTAF_sum / OTAN` to remain mathematically consistent with the database precalculated mean `Word_OTAF`.
- **OTAN Difference (`OTAN_Diff`):** The direct integer difference `Pseudoword_OTAN - Word_OTAN`.
- **OTAF Relative Difference (`OTAF_RelDiff_Pct`):** Relative difference in percent between the pseudoword and real word's orthographic mean frequencies.

---

## Second Pseudoword Generator (`second_pseudowords.py`)

For designs that need a matched pair of pseudowords per real word (e.g. an
orthographic-neighbor manipulation), `second_pseudowords.py` takes the output
of the main pipeline and, for each `(Word, Pseudoword)` pair, generates a
**second pseudoword** that:

- differs from the first pseudoword by exactly one letter (occasionally two,
  only if no valid one-letter neighbor exists)
- is phonotactically plausible (its onset/rime are attested in CLEARPOND —
  the same check used for Wuggy candidates)
- is not a real English word (checked against the CLEARPOND lexicon)
- is not identical to the source word, the first pseudoword, or any other
  second pseudoword already chosen in the run

Among valid one-letter neighbors, substitutions that keep the same letter
category (vowel-for-vowel or consonant-for-consonant) are preferred, since
that best preserves syllable structure and produces a plausible-sounding
"relative" of the original pseudoword (e.g. `chare` → `chave`, `tunup` → `nunup`).

### Usage

```bash
.venv/bin/python3 second_pseudowords.py \
    --input     data/two-pseudowords.csv \
    --clearpond data/englishCPdatabase2/englishCPdatabase2.txt \
    --output    data/two-pseudowords_expanded.csv \
    --seed      42
```

| Flag           | Default | Description |
|----------------|---------|-------------|
| `--input`      | *(required)* | CSV containing `Word` and `Pseudoword` columns (the output of `pseudowords.py`, or any CSV with those two columns) |
| `--clearpond`  | *(required)* | Path to `englishCPdatabase2.txt` |
| `--output`     | `two-pseudowords_expanded.csv` | Output CSV path — original columns preserved, `Pseudoword2*` columns appended |
| `--seed`       | `42` | Random seed controlling tie-breaks between equally-good candidates (fully reproducible — candidate lists are sorted before shuffling) |

### Added output columns

| Column | Description |
|--------|-------------|
| `Pseudoword2` | The generated second pseudoword |
| `Pseudoword2_EditDistance` | Number of letters changed from `Pseudoword` (1, occasionally 2) |
| `Pseudoword2_PTAN` / `Pseudoword2_PTAF` | Phonological neighborhood size/frequency mean of `Pseudoword2` |
| `Pseudoword2_OTAN` / `Pseudoword2_OTAF` | Orthographic neighborhood size/frequency mean of `Pseudoword2` |
| `Pseudoword2_vs_Pseudoword_PTAF_RelDiff_Pct` | Relative PTAF difference between `Pseudoword2` and `Pseudoword` |
| `Status2` | `MATCHED` (phonotactically valid pick), `BEST_AVAILABLE` (relaxed fallback, no phonotactic match found), or `NO_CANDIDATE` |

**Caveat:** "not a real word" is checked against the same CLEARPOND lexicon the
rest of the pipeline trusts (~28k words), not a full English dictionary —
spot-check borderline outputs manually.

---

## Mismatch Pseudoword Selector (`match_mismatch_pseudowords.py`)

> ⚠️ **Known limitation (current data):** OTAN/OTAF cannot be matched between
> the real-word and pseudoword mismatch sets — this is a hard ceiling in
> `data/workshopping.csv`, not a bug or a search shortfall. See
> [Important finding](#important-finding-hard-otanotaf-ceiling) below before
> relying on this script's OTAN/OTAF output.

Some `Stim1` words are paired with a real-word "mismatch" foil (the
`Mismatch Stim 2` column in `data/workshopping.csv`) — a same-length,
~1-letter-different real word used on mismatch trials. Only a subset of
words get this treatment. The pseudoword condition needs the same *number*
of mismatch trials, drawn from the pool of `Pseudoword2` items (each a
1-letter neighbor of `Pseudoword1`, from `second_pseudowords.py`) — but
which subset of that pool should be used?

This script treats the real-word `Mismatch Stim 2` set as the target
distribution (its PTAN/PTAF/OTAN/OTAF means) and searches the full
`Pseudoword2` pool for the equal-sized subset whose own PTAN/PTAF/OTAN/OTAF
means come closest to that target — verified with two-tailed independent
t-tests on each measure, so the eventual real-vs-pseudoword mismatch
comparison isn't confounded by a lexical-statistics mismatch between
conditions.

Because the four measures sit on very different numeric scales (PTAF is far
larger than PTAN/OTAN/OTAF), each measure's mismatch is expressed as a
standardized mean difference (Cohen's d, pooled SD) before being combined
into one composite score (`sum of d²`, lower is better). Since every
candidate subset is the same size as the target set, minimizing `|d|` for a
measure is mathematically equivalent to maximizing that measure's t-test
p-value — so the composite score directly captures both "small mean
differences" and "high p-values."

**Search strategy:** simulated annealing (swap-one-candidate-in-one-out
moves) with many random restarts, keeping the best subset found across the
whole search — far more effective than pure random subset sampling given
the combinatorial size of the pool (`50 choose 25` is astronomical).

### Usage

```bash
.venv/bin/python3 match_mismatch_pseudowords.py \
    --input     data/workshopping.csv \
    --output    data/mismatch_pseudowords_selected.csv \
    --restarts  100 \
    --steps     3000 \
    --seed      42
```

| Flag         | Default | Description |
|--------------|---------|-------------|
| `--input`    | *(required)* | CSV with `Stim1`, `Mismatch Stim 2`, `PTAN`/`PTAF`/`OTAN`/`OTAF` (the real-word mismatch's own stats), and `Pseudoword2`/`Pseudoword2_PTAN` etc. |
| `--output`   | `mismatch_pseudowords_selected.csv` | Output CSV path |
| `--restarts` | `100` | Independent simulated-annealing restarts (best result kept across all of them) |
| `--steps`    | `3000` | Annealing steps per restart |
| `--seed`     | `42` | Random seed (fully reproducible) |

### Output

The CSV has three parts:

1. **Selected rows (`Selected = YES`)** — the winning subset: one row per
   pseudoword chosen for the pseudoword mismatch condition, with `Stim1`,
   `Pseudoword1`, `Pseudoword2` (the item to actually use as the mismatch
   foil), and its own PTAN/PTAF/OTAN/OTAF.
2. **Unselected rows (`Selected = no`)** — the rest of the candidate pool
   that was considered but not picked, because including it would have
   pulled the group means further from the real-word target. Leftover;
   not used for anything unless you need extra items later.
3. **Summary block** (after a blank row) — five rows:

   | Row | What it is |
   |---|---|
   | `Real-word mismatch mean` | Target: average PTAN/PTAF/OTAN/OTAF across the real-word `Mismatch Stim 2` items |
   | `Selected pseudoword mean` | Same four averages, but for the selected subset |
   | `Cohen's d` | Standardized distance between those two means, per measure |
   | `t-test p-value` | Whether that distance is statistically significant |
   | `Composite score (sum d^2)` | Single number the search minimized — sum of the four squared Cohen's d values |

   Reading across the `Cohen's d`/`t-test p-value` rows tells you, measure
   by measure, whether the pseudoword mismatch condition is statistically
   indistinguishable from the real-word one (high p, small d = good match)
   or not (low p, large d = mismatch) — this is what you'd report in a
   methods section to justify the matching.

### Important finding: hard OTAN/OTAF ceiling

With `data/workshopping.csv`, PTAN and PTAF match well (p ≈ 0.84 and 0.80),
but **OTAN and OTAF do not** (p ≈ 0.005 and 0.07) — and this is a **hard
ceiling in the data, not a search failure**. The real-word mismatch set has
a mean OTAN of 4.24, but even the 25 *highest*-OTAN items in the entire
50-item `Pseudoword2` pool only average 2.32 — no subset can do better,
and the optimizer already converges to exactly this ceiling (verified by
independently sorting the pool and hand-picking the top 25).

This happens because pseudowords are deliberately constructed (via Wuggy) to
avoid resembling real words, so they inherently have sparser orthographic
neighborhoods than real words do — it's a structural property of the
stimulus design, not something more `--restarts`/`--steps` can fix. Closing
this gap would require generating a richer `Pseudoword2` candidate pool
(more neighbor candidates per pseudoword to choose from, e.g. by relaxing
`second_pseudowords.py`'s phonotactic-validity filter or allowing 2-letter
neighbors more often) — worth raising with the advisor before assuming
OTAN/OTAF-matched pseudoword mismatch trials are achievable at all.

---

## Notes

- **Static Type Safety:** Fully type-safe and validated using the `pyrefly` static type analysis.
- **Safety:** The clean input file `data/words.csv` remains untouched, and all generation outputs are piped to your designated output file (e.g. `data/pseudowords_output.csv`).
- **Known limitation:** the pseudoword mismatch condition cannot currently be matched to the real-word mismatch condition on OTAN/OTAF — see [Important finding: hard OTAN/OTAF ceiling](#important-finding-hard-otanotaf-ceiling).

---

## Appendix: Statistical Concepts Reference

Background for the calculations used in `match_mismatch_pseudowords.py`.

### Standard deviation as a ruler

A difference between two numbers only means something relative to how much
natural variation already exists in the data. If word A's PTAF averages 20
and word B's averages 25, is 5 a big gap? It depends entirely on whether
individual PTAF values normally range from 18–22 (huge gap) or from 0–500
(trivial gap). Standard deviation (SD) is "the typical spread of values
around the mean" — `sqrt(average squared deviation from the mean)`. It gives
you the ruler everything else below is measured against.

### Pooled standard deviation

**The problem it solves:** you have two groups (e.g. the real-word target
and a candidate pseudoword subset), each with its own spread. To compute an
effect size you need one shared "typical spread" to divide by — but whose
spread do you use? Pooled SD combines both groups' variances into a single,
principled estimate instead of picking one arbitrarily.

```
pooled_sd = sqrt( ((n1−1)·var1 + (n2−1)·var2) / (n1+n2−2) )
```

- It operates on **variances**, not SDs, and takes one square root at the
  end — variances add in a statistically meaningful way (they're sums of
  squared deviations); SDs don't.
- The `(n−1)` weights mean a variance estimated from more data (more
  trustworthy) counts for more in the combined estimate. `(n−1)` is that
  variance estimate's degrees of freedom. When `n1 = n2` (always true in
  this script, since subset size is forced to match target size), the
  weights are equal and this is just a plain average of the two variances.
- Dividing by `n1+n2−2` rather than `n1+n2` corrects for the fact that each
  group's own mean was estimated from its own data, which "uses up" one
  degree of freedom per group. This is the same `−1` correction seen in the
  ordinary sample-variance formula (`var = Σ(x−mean)² / (n−1)`), a bias fix
  called Bessel's correction.

**Bottom line:** pooled SD is the best single estimate of "how spread-out
values typically are," given both samples, weighted by how much data backs
up each one's own variance estimate.

### Cohen's d — a scale-free measure of "how far apart"

```
d = (mean1 − mean2) / pooled_sd
```

Dividing the raw mean difference by pooled SD expresses the gap in units of
"how much things normally vary" instead of raw numbers — so `d` is
comparable across measures with wildly different scales (PTAF vs. PTAN, for
example) in a way raw differences never could be. `d = 0.07` means the two
means are a trivial fraction of a standard deviation apart; `d = 0.84` means
they're nearly a full standard deviation apart — a large, obvious gap on any
scale.

### The t-statistic — factoring in sample size

A mean computed from 25 items is a noisier estimate of "the truth" than one
computed from 25,000 — more data means sampling noise averages out more.
The standard error of a difference between two sample means is
`sqrt(pooled_sd² · (1/n1 + 1/n2))`, and the t-statistic is:

```
t = (mean1 − mean2) / standard_error
```

— "signal ÷ expected noise." A `t` of 3 means the observed gap is 3x bigger
than what random sampling wobble alone would typically produce.

### Why a t-distribution, not just a normal distribution

With small samples, your estimate of the SD is itself uncertain — an unlucky
draw could look tighter or looser than the true population. That extra
uncertainty gives the sampling distribution of `t` fatter tails than a
normal distribution, especially for small n. The t-distribution accounts
for this, parameterized by *degrees of freedom* (`n1+n2−2` here — roughly
"how much independent information you have to pin down the spread"). As
sample size grows, the t-distribution converges to normal — the correction
matters most exactly when samples are small, like the 25-item groups here.

### p-value — turning t into a probability

Imagine a hypothetical world (the "null hypothesis") where the two groups
are actually drawn from the same underlying population, and any observed
difference is pure sampling luck. Under that assumption, the p-value is:
"what fraction of the time would random sampling alone produce a
t-statistic this extreme (in either direction — the 'two-tailed' part)?"

- p = 0.005 → "if there were truly no difference, a gap this large would
  show up only 0.5% of the time by chance" → evidence the groups really do
  differ.
- p = 0.84 → "a gap this large happens 84% of the time even with no real
  difference" → unremarkable, consistent with the groups being the same.

For stimulus matching, **high p is the goal** — you want to fail to find
evidence that the real-word and pseudoword groups differ.

### Why d and p collapse into one objective here

Substituting `t = d / sqrt(2/n)` (valid because subset size always equals
target size, `n1 = n2 = n`) shows `t` is just `d` rescaled by a constant
that depends only on `n`. Since `n` never changes across candidate subsets
in this search, `t` — and therefore `p` — is a fixed, monotonic function of
`d` alone. Minimizing `|d|` and maximizing `p` are the same objective, not a
trade-off.

### Simulated annealing

**The general problem:** a discrete search space too large to check
exhaustively (here, `C(50,25) ≈ 1.26×10¹⁴` possible subsets), and a score
function to minimize. You need a way to explore it intelligently.

**The naive approach and its flaw:** plain hill-climbing — start somewhere,
look at neighboring states (here, "one swap away": remove one item, add
another), move to whichever neighbor improves the score, repeat until
nothing helps. This gets stuck in *local optima* — a state better than
everything immediately next to it, but far from the true best state, like
settling into a foothill instead of the summit, because every path to the
real summit briefly goes downhill first and greedy hill-climbing refuses to
ever step downhill.

**The physics analogy:** cooling molten metal slowly lets atoms settle into
a low-energy, well-ordered crystal lattice; cooling too fast ("quenching")
freezes them into a disordered, higher-energy structure. Simulated
annealing borrows this: treat the score as "energy" (lower = better), and
introduce a "temperature" that starts high and cools over the run.

**The acceptance rule (Metropolis criterion):** for a proposed swap that
changes the score by `Δ`:
- If `Δ < 0` (an improvement), always accept it.
- If `Δ ≥ 0` (a worse move), accept it anyway with probability `exp(−Δ/T)`.

At high temperature `T`, `exp(−Δ/T)` stays close to 1 even for moderately
bad `Δ` — the search wanders freely, jumping out of shallow local optima.
As `T` shrinks toward zero, `exp(−Δ/T)` collapses toward 0 for any positive
`Δ` — the search becomes pickier, until near the end it behaves like greedy
hill-climbing, polishing whatever good region it landed in. One formula
smoothly dials between "explore broadly" and "exploit locally," controlled
entirely by the cooling schedule.

**Why it beats pure random sampling:** random sampling never uses
information from previous tries — every guess is independent. Annealing's
swap moves make each new candidate a small perturbation of a *known-decent*
candidate, concentrating effort in promising regions instead of wasting
budget on far-fetched combinations.

**Random restarts as insurance:** even annealing can land in different
final states depending on where it started — the cooling schedule doesn't
guarantee the global optimum, only a good one. Running it independently from
many different random starting subsets and keeping the single best result
found across all of them is cheap protection against any one run getting
unlucky.

**In `match_mismatch_pseudowords.py`:** state = a set of 25 indices into the
50-item pool; a move = swap one included index for one excluded index;
energy = the composite score (`sum of d²` across the 4 measures);
temperature decays geometrically from 1.0 to 0.0001 over 3000 steps per
restart, across 100 restarts. Re-running with 3x the search budget landed on
the exact same result — matching the independently-computed theoretical
ceiling — which is good evidence the search genuinely converged rather than
just running out of budget mid-search.
