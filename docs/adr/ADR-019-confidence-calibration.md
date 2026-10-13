# ADR-019: Confidence Calibration — Measure First, Threshold From a Stated Cost Ratio

## Status
Accepted — 2026-10-06. Implements `docs/improvement-report.md` D2, steps 1, 2 and 4. Step 3
(conformal prediction) is deferred.

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

## Alternatives considered

- **Conformal prediction (MAPIE), the report's step 3.** It gives a distribution-free coverage
  guarantee: emit a candidate set, and abstain when the set has more than one member. Deferred
  (`ponytail:` in `calibration.py`). It needs an exchangeable calibration set per semantic type,
  large enough that the per-type quantile is not noise, and a dispatch path that can emit sets.
  The trigger is a labelled corpus of that size; D6 is the means to build it.
- **Temperature or isotonic scaling of the stated confidences.** Rejected for now. It would
  rewrite every normalizer's output with a learned map before anyone has looked at the
  reliability diagram. Measuring comes first.
- **A default cost ratio.** Rejected, see above.

## Consequences

- `normcli calibrate <corpus> --cost-ratio R [--out-json P] [--out-md P]` scores a corpus with the
  real engine and writes the report. It refuses to run without `--cost-ratio`.
- The live numbers (the user's own labelled data) are recorded in `docs/plans/defects/LOCAL_VERIFY.md`.
