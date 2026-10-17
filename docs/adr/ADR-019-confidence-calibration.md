# ADR-019: Confidence Calibration — Measure First, Threshold From a Stated Cost Ratio

## Status
Accepted — 2026-10-06; amended 2026-10-14. Implements `docs/improvement-report.md` D2, steps 1
to 4 (step 3 as risk control over the emitted answers, see below).

## Context

The normalizers state a `confidence` on every answer, but the numbers are typed by hand: 61
`confidence=` sites, many of them the literal `1.0` (report D2, plan finding F4). Nothing compared
them with how often the engine is right, so no threshold built on `confidence` had a known scale.
D6 now supplies `(stated confidence, correct)` pairs from a gold corpus with known truth
(`normanalysis/gold.py`). Without such labels, calibration is impossible.

## Decision

**Measure before tuning.** `normanalysis/calibration.py` reports, and changes nothing. It is not
wired into dispatch, and no `confidence=` literal in any normalizer changes with this ADR. A
`confidence` that turns out to be dishonest is fixed in its normalizer later, as its own change,
with this report as the evidence.

**Reliability.** Stated confidence goes into equal-width bins, ten by default (the textbook
reliability diagram). The last bin is closed, so a stated `1.0` is counted. Each bin reports its
count, mean stated confidence and observed accuracy. An empty bin reports no accuracy (`None`), so
it claims nothing. The expected calibration error (ECE) weights each bin's gap by its share of
the answers. Results are also grouped per semantic type. A source id can be the grouping key in
the report too, but it is never a lookup key at run time.

**Noise is derived, not tuned.** The only convention is the significance level, 5%, kept in one
constant. Everything else follows from it:
- *ECE tolerance:* the ECE a perfectly calibrated engine can reach at this sample size. It is
  `sqrt(bins/n)/2` (expected value, Cauchy-Schwarz) plus a McDiarmid term
  `sqrt(2 ln(1/delta)/n)`, because ECE moves by at most 2/n when one answer changes.
- *Overconfident bin:* a one-sided Hoeffding test rejects "observed accuracy >= stated" at
  delta/bins (Bonferroni over the bins).

Both bounds assume the pairs are independent (one per distinct value and context, as D6 builds
them). The tolerance is a worst-case bound: a calibrated engine's real ECE is typically about a
quarter of it, so "ECE under tolerance" cannot certify calibration. The per-bin flags carry the
power. Per-group flags hold each group at the 5% level, not the family of groups.

**Chow's rule from a stated cost ratio.** The abstain/emit threshold is the confidence `t` with
the lowest total cost. The engine emits when confidence >= `t`. A wrong emitted value costs
`cost ratio` abstentions, and a right one costs nothing. The **cost ratio is a required argument
with no default** in the library and on the CLI (`normcli calibrate --cost-ratio R`). Q16 gives
only its direction (a wrong value is worse than an abstention), never the number. A default would
be a hidden policy decision. For calibrated confidences the optimum is Chow's `1 - 1/ratio`. The
threshold is computed over the observed confidences instead, so a miscalibrated engine gets the
threshold its real accuracy earns. When two thresholds cost the same, the higher one wins (abstain
when in doubt), which also makes the threshold monotone in the ratio. With no confident answers
there is no threshold (`None`), never an invented 0.5.

**Risk-coverage, not accuracy.** A system that may abstain is reported as a curve: the error rate
among the answers it keeps as the threshold rises, and its area (AURC). Tied confidences are kept
or dropped together, so the input order cannot change the result.

**Guarantee and use (amended 2026-10-14, PART1 D2.2, D2.3, D2.5; user decision: build, opt-in
per job).** Part 1 lists the guarantee as step 3 and calls the threshold "the abstain-versus-emit
threshold", so both are built, and neither changes a value unless a job asks:

- *A risk-controlled threshold.* Every normalizer here emits one answer, never a candidate set,
  so the conformal guarantee that fits is risk control over the emitted answers
  (Learn-then-Test, Angelopoulos et al. 2021): scanning the stated confidences from the highest
  down, a threshold `t` passes while the Hoeffding upper bound of the error rate among answers
  at `>= t` stays at most `alpha = 1 / (1 + R)` (the error rate Chow's rule tolerates for cost
  ratio R; R = 20 gives 4.76%); fixed-sequence testing keeps the family-wise error at
  `_DELTA` (5%) with no Bonferroni term. The last passing `t` is the threshold. None passing
  means "abstain on everything" for that type: on that corpus the stated confidence carries no
  information.
- *Per-type tables as versioned data.* `normcli calibrate --out-table` writes, per semantic
  type, the threshold, the reliability bins and the corpus size, with the cost ratio, delta and
  the corpus's provenance. The committed table (`normapi/data/calibration.json`) is built from
  the corpora whose truth does not come from the engine: the seeded D6 corpus, Raha's erroneous
  cells and BART's injected cells. Unchanged real cells are left out: their truth would be the
  engine's own answer.
- *Clones report it, and refuse only when asked.* Every clone reports per column how many of its
  answers fall below the type's threshold and the expected number wrong (the bins' observed
  accuracy). With `calibrated_abstention: true` on the job, such an answer becomes AMBIGUOUS,
  original kept, and goes to the review queue (ADR-018). Default off: on today's corpora several
  types have no passing threshold, and switching every job to "abstain on everything" for them
  is the user's call per job, not a default.

## Alternatives considered

- **Conformal prediction sets (MAPIE).** A candidate *set* needs several scored candidates per
  value; the normalizers emit one answer (or refuse, listing candidates without scores), so the
  set form reduces to "emit or abstain", which the risk-controlled threshold above guarantees
  directly. MAPIE would add a dependency for the same decision.
- **Temperature or isotonic scaling of the stated confidences.** Rejected for now. It would
  rewrite every normalizer's output with a learned map before anyone has looked at the
  reliability diagram. Measuring comes first.
- **A default cost ratio.** Rejected, see above.

## Consequences

- `normcli calibrate <corpus> --cost-ratio R [--out-json P] [--out-md P]` scores a corpus with the
  real engine and writes the report. It refuses to run without `--cost-ratio`.
- The live numbers (the user's own labelled data) are recorded in `docs/plans/defects/LOCAL_VERIFY.md`.
