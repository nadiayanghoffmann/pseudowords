# Findings: PTAF Calculation Audit

**Date:** 2026-06-11
**Scope:** Verification of the calculations in `pseudowords.py` against the README description, the CLEARPOND database, and the manually prepared `data/liina.csv`.

---

## TL;DR

- The script's neighbor-finding machinery is **correct** — it reproduces CLEARPOND's
  precalculated ePTAN/ePTAF exactly.
- However, CLEARPOND's PTAF (and therefore the `Word_PTAF` target column) is a
  **mean** of neighbor frequencies, while the script reports and matches the
  **sum**. The matching is an apples-to-oranges comparison, so the `MATCHED`
  statuses do not indicate genuinely PTAF-matched stimuli.
- The grapheme→phoneme approximation silently **degenerates to the source word's
  own pronunciation** for ~18 of 51 items, producing fake 0 % differences and
  spurious `MATCHED` statuses.
- `data/liina.csv` uses real transcriptions of the pseudowords (its neighbor
  counts are the more credible ones), but its columns mix sum and mean
  conventions, and its final PTAF column double-divides in several rows.
- **The statistic actually comparable to `Word_PTAF` is the mean:
  `Pseudoword_PTAF ÷ Pseudoword_PTAN`, computed from a proper transcription.
  Neither file currently reports it consistently.**

---

## 1. CLEARPOND's ePTAF is a mean, not a sum (verified)

Running the script's own `compute_ptaf_and_ptan()` over
`englishCPdatabase2.txt` and comparing with the database's precalculated
columns:

| word    | DB ePTAN | DB ePTAF  | script count | script sum | script mean |
|---------|----------|-----------|--------------|------------|-------------|
| chair   | 37       | 220.2279  | 37           | 8148.43    | **220.2279** |
| stone   | 18       | 6.9662    | 18           | 125.39     | **6.9662**   |
| flame   | 9        | 14.2331   | 9            | 128.10     | **14.2331**  |
| token   | 3        | 47.0784   | 3            | 141.24     | **47.0784**  |
| model   | 10       | 11.4412   | 10           | 114.41     | **11.4412**  |
| kitten  | 8        | 16.8088   | 8            | 134.47     | **16.8088**  |
| journal | 5        | 23.8824   | 5            | 119.41     | **23.8824**  |

The script's neighbor enumeration (one-phoneme substitution / deletion /
insertion) matches CLEARPOND's definition exactly: the counts equal ePTAN and
**sum ÷ count equals ePTAF to all four decimals**. So ePTAF is the *mean*
frequency of the phonological neighbors.

The same check on `compute_otan_otaf()` confirms **eOTAF is also a mean**
(chair: eOTAN 7, eOTAF 27.6163 = 193.3138 ÷ 7). On the orthographic side the
script *does* divide by OTAN, so `Pseudoword_OTAF` is consistent with the
database convention — only the PTAF side is not.

## 2. The sum-to-mean matching problem

`Pseudoword_PTAF` is written as the raw frequency **sum**, and the matching
logic compares that sum directly with the `Word_PTAF` target, which is the
ePTAF **mean** (`pseudowords.py:609`, `pseudowords.py:679`).

README section 5 documents this explicitly ("while mathematically
counter-intuitive, this direct sum-to-mean matching logic ensures original
matches … are produced"), so **the code matches the README's letter** — but the
README's headline claim that pseudowords have "a PTAF … within TOLERANCE of the
real word's PTAF" is misleading: the two quantities are in different units.

Consequence: a pseudoword is declared `MATCHED` when its neighbor-frequency
*sum* lands near the word's neighbor-frequency *mean*. This systematically
selects pseudowords whose neighborhoods are roughly PTAN-times weaker than the
real words'. Liina's own t-test row shows the effect: word mean PTAF ≈ 6.95 vs
pseudoword ≈ 1.07 (p ≈ .0001) — the stimuli are **not** actually matched.

## 3. Degenerate transcriptions (undocumented flaw)

`pseudoword_to_phono()` (`pseudowords.py:220`) approximates a pseudoword's
phonology by orthographic onset/rime lookup, falling back to the **source
word's** onset/rime when lookup fails. When both parts fall back (or the lookup
happens to round-trip), the result is literally the source word's own phoneme
string. This happens for **18 of the 51 items** in `liina.csv`, e.g.:

| pseudoword | script transcription | …which is actually |
|------------|----------------------|--------------------|
| kaate      | `k.oU.A.l.5`         | *koala*            |
| machent    | `m.5.S.i.n`          | *machine*          |
| faydic     | `f.1.b.r0.I.k`       | *fabric*           |
| drobon     | `d.r0.1.g.5.n`       | *dragon*           |
| blarhet    | `b.l.1.N.k.I0.t`     | *blanket*          |

For these rows `Pseudoword_PTAF` is just the real word's own statistic,
`PTAF_RelDiff_Pct` is a fake 0.0, and the `MATCHED` status is meaningless.

Illustration: for *kaate* the script "found" the neighbor *cola* (because it
was actually scoring *koala*), while Liina's single neighbor with frequency
7.569 is **karate** — a sensible neighbor of a real /kɑːte/-style transcription.

## 4. What is going on in `data/liina.csv`

The left-hand (real word) columns match the database exactly: PTAN = ePTAN and
PTAF = ePTAF (the mean). The pseudoword side diverges from the script's output
for three stacked reasons:

1. **Different transcriptions.** Liina evaluated the pseudowords' actual
   pronunciations (presumably via CLEARPOND's online nonword tool); the script
   uses its orthographic onset/rime approximation. Example: *losen* as
   `l.oU.s.5.n` yields her ND = 6 (listen, lesson, logan, loosen, lotion,
   lessen); the script's `l.oU.z.5.n` yields 3. Where transcriptions differ,
   **her neighbor counts are the more credible ones** — and ~18 of the script's
   rows are outright degenerate (see §3).

2. **Sum/mean confusion in her columns.** In several rows the column labeled
   *"Sum of the frequencies of all neighbors"* (TotalNF) actually contains the
   **mean** of exactly the neighbor sets recomputed here, to every printed
   decimal:

   | pseudoword | true neighbors            | true sum | true mean | liina "TotalNF" |
   |------------|---------------------------|----------|-----------|------------------|
   | lucket     | bucket, locket, lucked    | 12.6471  | 4.2157    | **4.216**        |
   | rillet     | fillet, willet            | 0.9412   | 0.4706    | **0.471**        |
   | pamble     | gamble, ramble            | 9.5490   | 4.7745    | **4.775**        |
   | dorger     | dodger, forger            | 1.8823   | 0.9412    | **0.941**        |

   Her final column then divides by ND *again* (e.g. lucket: 4.216 ÷ 3 =
   1.405), producing a mean-divided-twice — not a meaningful quantity.

3. **Internal inconsistency.** Other rows are labeled correctly. E.g. *secture*
   (`s.E.k.tS.56`, neighbors lecture + sector): her TotalNF 17.402 ≈ the true
   sum 17.5294 and her final 8.701 ≈ the true mean 8.7647. So the spreadsheet
   mixes both conventions and its final PTAF column cannot be trusted as a
   whole.

## 5. Which numbers are correct?

**Neither file, as is.** The statistic comparable to `Word_PTAF` / ePTAF is the
**mean frequency of the pseudoword's phonological neighbors, computed from a
proper transcription** — i.e. `Pseudoword_PTAF ÷ Pseudoword_PTAN`, but only on
rows where the script's transcription did not degenerate.

For the rows where both sources used the same transcription, the correct mean
values are:

| pseudoword | correct PTAF (mean) |
|------------|---------------------|
| lucket     | 4.216               |
| rillet     | 0.471               |
| pamble     | 4.775               |
| dorger     | 0.941               |
| secture    | 8.765               |

Liina's ND values and neighbor identification are generally trustworthy; her
final PTAF column is right only in the "secture-style" rows.

## 6. Minor documentation mismatches

- Module docstring claims defaults of tolerance 0.10, candidates 30, seed 42;
  the argparse defaults are 0.20, 200, 23 (`pseudowords.py:840-844`).
- The README options table claims seed default 42; the code default is 23.

## 7. Recommended fixes (applied 2026-06-11)

1. ✅ `Pseudoword_PTAF` is now reported as **sum ÷ PTAN** (mean) and the
   matching compares that mean against `Word_PTAF`, in all three code paths
   (existing pseudowords, Wuggy candidates, phoneme-mutation fallback).
2. ✅ The source-word fallback in `pseudoword_to_phono()` was removed: the
   function returns `None` when the onset or rime is not attested in
   CLEARPOND. Untranscribable Wuggy candidates are skipped (falling through to
   the phoneme-mutation generator if none survives); untranscribable existing
   pseudowords are reported with the new `NO_TRANSCRIPTION` status and blank
   PTAF fields.
3. ✅ Verified by a full re-run against `data/words-final.csv` (scratch output,
   `data/` untouched): 14 MATCHED / 30 BEST_AVAILABLE / 17 NO_TRANSCRIPTION.
   All 17 formerly degenerate "perfect matches" (machent, faydic, drobon,
   blarhet, …) now report NO_TRANSCRIPTION, and the corrected means from §5
   are reproduced exactly (lucket 4.2157, pamble 4.7745, secture 8.7647).
4. ✅ Docstring and README defaults aligned with argparse
   (tolerance 0.20, candidates 200, seed 23). `pyrefly check`: 0 errors.
