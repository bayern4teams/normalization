# Verified Resources — Ambiguity, Uncertainty, Confidence, Abstention, and ML/LLM-Assisted Normalization

**Scope:** for a normalization engine that must return `AMBIGUOUS` rather than a plausible guess, preserve input precision (a year stays a year), carry provenance/confidence, and be evaluated as a system that is allowed to say "I don't know."

**Verification:** every URL below was fetched or content-extracted and resolved to the stated resource. Four publisher/standards pages bot-wall automated clients (HTTP 403) but were confirmed real via content extraction or exact-title match; they are marked *(bot-walled — open in a browser)*. No link here is reconstructed from memory.

---

## 1. NULL semantics, missing-value taxonomies, precision-preserving value models (9)

1. Codd — *Missing Information (Applicable and Inapplicable) in Relational Databases* — https://sigmodrecord.org/publications/sigmodRecord/8612/pdfs/16301.16303.pdf — the original "unknown vs not-applicable" split; exactly the distinction you need between `UNKNOWN`, `MISSING`, and `NOT_APPLICABLE`.
2. Zaniolo — *Database Relations with Null Values* — http://web.cs.ucla.edu/~zaniolo/papers/nullvalues.pdf — formal semantics for "no information" nulls; argues for one sentinel meaning per column instead of one overloaded NULL.
3. Libkin — *SQL's Three-Valued Logic and Certain Answers* (TODS) — https://homepages.inf.ed.ac.uk/libkin/papers/tods16.pdf — establishes when SQL's 3VL actually returns *certain* answers; the theory behind "only emit a value you can guarantee."
4. Libkin — *Incomplete Information* lecture notes — https://homepages.inf.ed.ac.uk/libkin/teach/beijing2018/incinf.pdf — compact tutorial on c-tables, naive tables and certain answers; the best single onboarding doc for the team.
5. HL7 FHIR — `dataAbsentReason` extension — https://hl7.org/fhir/extensions/StructureDefinition-data-absent-reason.html — a production, battle-tested vocabulary (`unknown`, `asked-unknown`, `masked`, `not-applicable`, `error`); adopt this enum instead of inventing one.
6. Stata — *Missing Values* manual — https://www.stata.com/manuals/dmissingvalues.pdf — the 27-extended-missing-code design with defined ordering and propagation rules; a proven sentinel taxonomy.
7. Apache Arrow — *Columnar Format* (validity bitmaps) — https://arrow.apache.org/docs/format/Columnar.html — separates "is null" from the value buffer: the storage pattern that lets `AMBIGUOUS` coexist with strongly-typed values.
8. ISO/IEC 11404 — *General-Purpose Datatypes*, roadmap paper — https://www9.open-std.org/jtc1/sc22/open/n3620.pdf (standard itself: https://www.iso.org/standard/39479.html *(bot-walled)*) — a language-independent datatype model; anchor for defining your normalized value lattice portably.
9. *Moore: Interval Arithmetic in Modern C++* — https://arxiv.org/abs/1611.09567 — interval arithmetic with guaranteed enclosures: the precision-preserving alternative to picking a point value (`1998` ⇒ `[1998-01-01, 1998-12-31]`).

## 2. Precision-preserving date/time and locale standards (4)

10. Library of Congress — *Extended Date/Time Format (EDTF)* — https://www.loc.gov/standards/datetime/ *(bot-walled; content verified)* — canonical syntax for uncertain / approximate / reduced-precision dates (`1998`, `1998-05?`, `199X`, `1998/2001`); your date normalizer's output grammar.
11. `ixc/python-edtf` — https://github.com/ixc/python-edtf — working EDTF parser producing earliest/latest bounds, so a year stays a year yet remains sortable and comparable.
12. Unicode CLDR — https://cldr.unicode.org/ — locale data for date/number/name formats; the reference for *detecting* genuinely ambiguous input (`03/04/2020`) rather than assuming a locale.
13. `scrapinghub/dateparser` — https://github.com/scrapinghub/dateparser — the widely used human-date parser; study its ambiguity settings and failure modes as a catalogue of what must never be silently resolved.

## 3. Provenance, data-quality vocabularies, declarative gates (5)

14. W3C — *PROV-O: The PROV Ontology* — https://www.w3.org/TR/prov-o/ — standard vocabulary for who/which-rule/which-source produced a normalized value; the interoperable way to ship provenance with every decision.
15. Cheney, Chiticariu & Tan — *Provenance in Databases: Why, How, and Where* — https://homepages.inf.ed.ac.uk/jcheney/publications/provdbsurvey.pdf — the standard survey; pick a provenance model deliberately before hard-coding one.
16. Buneman, Khanna & Tan — *Why and Where: A Characterization of Data Provenance* — https://link.springer.com/chapter/10.1007/3-540-44503-X_20 — the why- vs where-provenance distinction that decides whether you can explain *why* an output was `AMBIGUOUS`.
17. W3C — *Data Quality Vocabulary (DQV)* — https://www.w3.org/TR/vocab-dqv/ — RDF vocabulary for quality annotations and metrics; how to publish per-field confidence and documented limitations.
18. W3C — *SHACL* — https://www.w3.org/TR/shacl/ — declarative validation over graphs: closed-world-style constraints layered on open-world data, i.e. deterministic gates that run before any ML step.

## 4. Probabilistic / uncertain databases and possible-worlds semantics (9)

19. Suciu, Olteanu, Ré & Koch — *Probabilistic Databases* (monograph) — https://link.springer.com/book/10.1007/978-3-031-01879-4 — the one reference to read end-to-end before building an uncertainty layer.
20. Dalvi & Suciu — *Efficient Query Evaluation on Probabilistic Databases* — https://homes.cs.washington.edu/~suciu/probdb.pdf — the foundational paper: possible-worlds semantics plus tractability results for confidence computation.
21. Dalvi & Suciu — *The Dichotomy of Conjunctive Queries on Probabilistic Structures* — https://arxiv.org/abs/cs/0612102 — the safe/unsafe plan dichotomy: some uncertainty questions are provably hard, so design queries that stay in the tractable class.
22. Dalvi, Ré & Suciu — *Probabilistic Databases: Diamonds in the Dirt* (CACM) — https://cacm.acm.org/research/probabilistic-databases-diamonds-in-the-dirt/ *(bot-walled; content verified)* — accessible overview for convincing non-specialists that uncertainty belongs in the data model.
23. MayBMS — https://maybms.sourceforge.net/ *(bot-walled; content verified)* — a complete probabilistic DBMS over Postgres using U-relations; reference implementation for compactly representing many possible worlds.
24. Stanford Trio — http://infolab.stanford.edu/trio — ULDBs: data + *uncertainty* + *lineage* in one model; the architectural precedent for pairing every uncertain value with its provenance.
25. Suciu — *MystiQ* — https://homes.cs.washington.edu/~suciu/project-mystiq.html — probabilistic query engine layered over a deterministic database; shows how to keep uncertainty above clean storage rather than inside it.
26. Aggarwal & Yu — *A Survey of Uncertain Data Algorithms and Applications* — http://charuaggarwal.net/manuscript.pdf — the TKDE survey covering uncertain modeling, indexing and mining; a map before you commit to one formalism.
27. Rekatsinas et al. — *HoloClean: Holistic Data Repairs with Probabilistic Inference* — https://arxiv.org/abs/1702.00820 — repairs as probabilistic inference with explicit per-repair confidence: the principled baseline that still lets you threshold and abstain.

## 5. Abstention, learning-to-reject, selective prediction (7)

28. Chow — *On Optimum Recognition Error and Reject Tradeoff* (1970) — https://dl.acm.org/doi/10.1109/TIT.1970.1054406 *(bot-walled)* — Chow's rule: the optimal reject threshold given the cost of an error vs the cost of a rejection; the math behind your `AMBIGUOUS` threshold.
29. Hendrickx et al. — *Machine Learning with a Reject Option: A Survey* — https://arxiv.org/abs/2107.11277 — the map of the field (separated / dependent / integrated rejectors, plus metrics); start here.
30. Same survey, peer-reviewed version (*Machine Learning*, 2024) — https://link.springer.com/article/10.1007/s10994-024-06534-x — updated consolidated taxonomy and evaluation guidance; the citable form.
31. El-Yaniv & Wiener — *On the Foundations of Noise-free Selective Classification* (JMLR) — https://jmlr.org/papers/v11/el-yaniv10a.html — defines the risk–coverage tradeoff and selective risk; the source of the curve your engine should report.
32. Geifman & El-Yaniv — *SelectiveNet* — https://arxiv.org/abs/1901.09192 — trains prediction and rejection jointly at a target coverage; the model-side analogue of a never-guess contract.
33. Thulasidasan et al. — *Combating Label Noise in Deep Learning Using Abstention* — https://arxiv.org/abs/1905.10964 — an explicit abstention class in the loss; abstention also protects you from noisy gold labels.
34. Mozannar & Sontag — *Consistent Estimators for Learning to Defer to an Expert* — https://arxiv.org/abs/2006.01862 — theory for routing hard cases to humans instead of guessing: the formal version of your escalation queue. (Calibrated variant: https://arxiv.org/abs/2202.03673)

## 6. Calibration, conformal prediction, OOD detection (11)

35. Shafer & Vovk — *A Tutorial on Conformal Prediction* (JMLR) — https://www.jmlr.org/papers/v9/shafer08a.html — canonical introduction to distribution-free validity: the theory that lets you claim "this candidate set contains the truth with 95% probability."
36. Angelopoulos & Bates — *A Gentle Introduction to Conformal Prediction and Distribution-Free UQ* — https://arxiv.org/abs/2107.07511 — the practical tutorial: turn scores into guaranteed prediction *sets*, then abstain whenever the set holds more than one candidate.
37. `aangelopoulos/conformal-prediction` — https://github.com/aangelopoulos/conformal-prediction — runnable notebooks matching the tutorial; the fastest path to a statistically-backed abstention threshold.
38. MAPIE — https://github.com/scikit-learn-contrib/MAPIE — scikit-learn-compatible conformal sets/intervals and risk control; production-grade coverage guarantees (paper: https://arxiv.org/abs/2207.12274).
39. `henrikbostrom/crepes` — https://github.com/henrikbostrom/crepes — conformal classifiers/regressors with Mondrian (per-class, per-bin) variants; use when ambiguity rates differ sharply by field type.
40. Guo et al. — *On Calibration of Modern Neural Networks* — https://arxiv.org/abs/1706.04599 — modern networks are systematically overconfident; introduces temperature scaling. Mandatory before you trust any confidence threshold.
41. Zadrozny & Elkan — *Transforming Classifier Scores into Accurate Multiclass Probability Estimates* — https://www.cs.cornell.edu/courses/cs678/2007sp/ZadroznyElkan.pdf — isotonic-regression calibration; the non-parametric option when score distributions are badly shaped.
42. Nixon et al. — *Measuring Calibration in Deep Learning* — https://arxiv.org/abs/1904.01685 — exposes ECE's binning artifacts and offers better estimators; stops you certifying calibration with a broken metric.
43. Kumar, Liang & Ma — *Verified Uncertainty Calibration* — https://arxiv.org/abs/1909.10155 — calibration with finite-sample guarantees and debiased estimators; the rigorous version of "our 0.9 really means 0.9" (code: https://github.com/AnanyaKumar/verified_calibration).
44. Hendrycks & Gimpel — *A Baseline for Detecting Misclassified and Out-of-Distribution Examples* — https://arxiv.org/abs/1610.02136 — the max-softmax OOD baseline; the first line of defense against normalizing inputs unlike anything in training.
45. Ovadia et al. — *Can You Trust Your Model's Uncertainty? Predictive Uncertainty Under Dataset Shift* — https://arxiv.org/abs/1906.02530 — confidence degrades badly under shift; the empirical case for re-calibrating per source/vendor feed.
46. Lakshminarayanan et al. — *Deep Ensembles* — https://arxiv.org/abs/1612.01474 — ensemble disagreement as a cheap, reliable uncertainty signal: disagreement among independent normalizers ⇒ `AMBIGUOUS`.
47. Kendall & Gal — *What Uncertainties Do We Need in Bayesian Deep Learning?* — https://arxiv.org/abs/1703.04977 — aleatoric vs epistemic uncertainty: "input is genuinely ambiguous" and "model is ignorant" must trigger different actions.

## 7. Human-in-the-loop, weak supervision, label quality (7)

48. `modAL-python/modAL` — https://github.com/modAL-python/modAL — modular active learning; turns your abstention queue into the sampling pool that most improves the model per unit of labeling effort.
49. Label Studio — https://github.com/HumanSignal/label-studio (site: https://labelstud.io/) — open-source multi-type labeling with review/adjudication workflows; where escalated `AMBIGUOUS` cases get resolved by humans.
50. Argilla — https://github.com/argilla-io/argilla — dataset-centric annotation with model suggestions plus explicit human confirmation; fits a deterministic-first pipeline requiring sign-off.
51. `snorkel-team/snorkel` — https://github.com/snorkel-team/snorkel — labeling functions plus a label model; encode your deterministic rules as weak labelers and surface exactly where they *conflict* (that conflict is your ambiguity signal).
52. Ratner et al. — *Snorkel: Rapid Training Data Creation with Weak Supervision* — https://pmc.ncbi.nlm.nih.gov/articles/PMC5951191/ — the system paper; its generative label model explicitly estimates rule accuracies and disagreement.
53. `NorskRegnesentral/skweak` — https://github.com/NorskRegnesentral/skweak — weak supervision for text/sequence tasks via aggregated heuristics, well suited to span-level normalization (paper: https://arxiv.org/abs/2104.09683).
54. `cleanlab/cleanlab` — https://github.com/cleanlab/cleanlab — finds label errors and low-quality examples; run it on your gold corpus before blaming the model for a "wrong" abstention (theory: https://arxiv.org/abs/1911.00068).

## 8. LLM-assisted normalization and its risks (12)

55. Narayan et al. — *Can Foundation Models Wrangle Your Data?* — https://arxiv.org/abs/2205.09911 — the reference result that LLMs are competitive on entity matching / imputation / error detection, and precisely where they still require validation.
56. Li et al. — *Ditto: Deep Entity Matching with Pre-Trained Language Models* — https://arxiv.org/abs/2004.00584 — a strong LM matcher producing thresholdable, calibratable scores (code: https://github.com/megagonlabs/ditto).
57. Zhang et al. — *Jellyfish: A Large Language Model for Data Preprocessing* — https://arxiv.org/abs/2312.01678 — instruction-tuned *local* models for cleaning tasks; keeps normalization auditable, reproducible and on-prem (weights: https://huggingface.co/NECOUDBFM/Jellyfish-13B).
58. Li et al. — *Table-GPT: Table-tuned GPT for Diverse Table Tasks* — https://arxiv.org/abs/2310.09263 — table-tuning to fix LLM brittleness on tabular input; documents the prompt/format sensitivity that silently produces wrong values.
59. Eltabakh et al. — *RetClean: Retrieval-Based Data Cleaning Using LLMs and Data Lakes* — https://arxiv.org/abs/2303.16909 (VLDB PDF: https://www.vldb.org/pvldb/vol17/p4421-eltabakh.pdf) — grounds every LLM cleaning proposal in a retrieved source tuple, so values are *sourced* rather than invented.
60. Peeters & Bizer — *Entity Matching using Large Language Models* — https://arxiv.org/abs/2310.11244 — systematic evaluation across open and hosted models with prompt-sensitivity analysis; realistic accuracy expectations rather than vendor claims.
61. Steiner, Peeters & Bizer — *Fine-tuning Large Language Models for Entity Matching* — https://arxiv.org/abs/2409.08185 — when fine-tuning helps versus hurts out-of-distribution generalization; input to deciding whether an LLM belongs in the hot path at all.
62. Huang et al. — *A Survey on Hallucination in LLMs: Principles, Taxonomy, Challenges, Open Questions* — https://arxiv.org/abs/2311.05232 — the thorough hallucination survey; use its taxonomy to name the exact failure modes your guardrails must block.
63. Kadavath et al. — *Language Models (Mostly) Know What They Know* — https://arxiv.org/abs/2207.05221 — self-evaluated P(True) as a usable confidence signal; the empirical basis for LLM self-abstention.
64. Kuhn, Gal & Farquhar — *Semantic Uncertainty* — https://arxiv.org/abs/2302.09664 — clusters semantically equivalent generations before measuring entropy; the correct way to detect uncertainty on free-text normalizations where surface forms vary.
65. Farquhar et al. — *Detecting hallucinations in LLMs using semantic entropy* (Nature, 2024) — https://www.nature.com/articles/s41586-024-07421-0 — peer-reviewed abstention signal needing no task-specific labels; defensible in an audit.
66. Zhang et al. — *R-Tuning: Instructing LLMs to Say "I Don't Know"* — https://arxiv.org/abs/2311.09677 — fine-tuning explicitly for refusal on unknowns; the most direct match to a never-guess contract. (Selective-prediction variant: https://arxiv.org/abs/2310.11689)

## 9. Constrained decoding, structured output, guardrails, deterministic-first hybrids (8)

67. `dottxt-ai/outlines` — https://github.com/dottxt-ai/outlines — regex and JSON-Schema-constrained generation; makes `AMBIGUOUS` a first-class representable output and malformed output structurally impossible.
68. Willard & Louf — *Efficient Guided Generation for Large Language Models* — https://arxiv.org/abs/2307.09702 — the FSM-index method behind Outlines; explains why constrained decoding is near-free and provably format-safe.
69. `guidance-ai/guidance` — https://github.com/guidance-ai/guidance — interleaves program control with constrained generation; lets you enforce "select from this closed candidate set, or abstain" at the token level.
70. `noamgat/lm-format-enforcer` — https://github.com/noamgat/lm-format-enforcer — JSON Schema / regex enforcement integrated with vLLM and transformers; keeps large batch normalization jobs schema-valid end to end.
71. `1rgs/jsonformer` — https://github.com/1rgs/jsonformer — minimal token-level JSON-schema enforcement; small enough to fully audit when you cannot take a heavy dependency.
72. `567-labs/instructor` — https://github.com/567-labs/instructor — Pydantic-typed LLM outputs with validation and bounded retries; the glue for "LLM proposes, typed validator decides."
73. `guardrails-ai/guardrails` — https://github.com/guardrails-ai/guardrails — declarative validators with fail / fix / **refrain** actions; `refrain` maps directly onto returning `AMBIGUOUS` instead of a repaired guess.
74. `pydantic/pydantic` — https://github.com/pydantic/pydantic — strict typed validation with custom validators; the deterministic gate that no model suggestion may bypass.

## 10. Similarity, blocking and retrieval that respect precision (10)

75. Christen — *A Survey of Indexing Techniques for Scalable Record Linkage and Deduplication* — https://users.cecs.anu.edu.au/~christen/publications/christen2011indexing.pdf — the canonical blocking survey with recall/efficiency tradeoffs; blocking must never silently drop the true match.
76. Papadakis et al. — *A Survey of Blocking and Filtering Techniques for Entity Resolution* — https://arxiv.org/abs/1905.06167 — modern schema-agnostic blocking and meta-blocking; keeps candidate generation high-recall so an abstention is genuine, not a blocking artifact.
77. Fellegi & Sunter — *A Theory for Record Linkage* (1969) — https://nhis.ipums.org/nhis/resources/Fellegi69.pdf — the original three-way decision: link / non-link / **possible link needing clerical review** — the historical blueprint for `AMBIGUOUS`.
78. `ekzhu/datasketch` — https://github.com/ekzhu/datasketch — MinHash, LSH, LSH Ensemble/Forest; probabilistic candidate generation with tunable and *documented* error bounds (LSH docs: https://ekzhu.com/datasketch/lsh.html).
79. Reimers & Gurevych — *Sentence-BERT* — https://arxiv.org/abs/1908.10084 — the embedding-similarity workhorse; note it yields *scores*, never identity, so always verify exactly before committing a value.
80. `UKPLab/sentence-transformers` — https://github.com/UKPLab/sentence-transformers — models, training and evaluation for embedding similarity, incl. hard-negative mining to sharpen near-duplicate discrimination.
81. Formal et al. — *SPLADE* — https://arxiv.org/abs/2107.05720 — learned sparse retrieval that preserves lexical exactness (codes, SKUs, IDs) which dense vectors blur away.
82. Bruch et al. — *An Analysis of Fusion Functions for Hybrid Retrieval* — https://arxiv.org/abs/2210.11934 — principled sparse+dense score fusion; ad-hoc fusion destroys score calibration and therefore your thresholds.
83. `dedupeio/dedupe` — https://github.com/dedupeio/dedupe — active-learning record linkage that emits match probabilities plus an explicit review band; a directly reusable abstention pattern.
84. `moj-analytical-services/splink` — https://github.com/moj-analytical-services/splink — scalable Fellegi–Sunter linkage with EM-estimated match weights and strong explainability/diagnostics for defending decisions.

## 11. Evaluating a normalizer that is allowed to abstain (8)

85. Christen & Hand — *A Review of the F-Measure: History, Properties, Criticism, and Alternatives* — https://users.cecs.anu.edu.au/~Peter.Christen/publications/christen2023fmeasure.pdf — why F1 misleads on imbalanced linkage/normalization tasks; read before making F1 the headline metric.
86. scikit-learn — `fbeta_score` — https://scikit-learn.org/stable/modules/generated/sklearn.metrics.fbeta_score.html — exact F-beta semantics and edge-case behavior; set β<1 to encode "precision matters more than coverage."
87. Artstein & Poesio — *Inter-Coder Agreement for Computational Linguistics* — https://aclanthology.org/J08-4004/ — the definitive guide to κ/α and their pitfalls; where annotators cannot agree, `AMBIGUOUS` is the *correct* gold label, not a system failure.
88. `LightTag/simpledorff` — https://github.com/LightTag/simpledorff — Krippendorff's α straight from a DataFrame; practical agreement computation tolerant of missing judgments (also `nltk.metrics.agreement`: https://www.nltk.org/_modules/nltk/metrics/agreement.html).
89. Abedjan et al. — *Detecting Data Errors: Where Are We and What Needs to Be Done?* — https://www.vldb.org/pvldb/vol9/p993-abedjan.pdf — empirical error taxonomy plus tool-coverage analysis; the template for your own normalization error taxonomy.
90. Mahdavi et al. — *Raha: A Configuration-Free Error Detection System* — http://raulcastrofernandez.com/papers/raha.pdf — ensembles detection strategies under a strict label budget; precision/recall evaluation methodology worth imitating (code + benchmarks: https://github.com/BigDaMa/raha).
91. Voorhees & Harman — *TREC: Experiment and Evaluation in Information Retrieval* (review) — https://aclanthology.org/J06-4008.pdf — how shared-task evaluation infrastructure (pooling, qrels, significance testing) is actually built; the model for a defensible gold corpus.
92. SemEval — https://semeval.github.io/ — the shared-task conventions to copy for internal benchmarks: published annotation guidelines, reported inter-annotator agreement, baselines, and a single official scorer.

---

### Suggested reading order for this engine

1. **Fix the semantics first** — #1, #4, #5, #10. Settle the `UNKNOWN` / `MISSING` / `NOT_APPLICABLE` / `AMBIGUOUS` vocabulary and the precision-preserving date grammar before writing code.
2. **Choose the abstention rule** — #28 (Chow's threshold), #36 (conformal sets for the guarantee), #31 (risk–coverage as the report format).
3. **Calibrate whatever you threshold** — #40, #42, #43. An uncalibrated score makes the threshold meaningless, and #45 shows it drifts per source.
4. **Keep LLMs off the critical path** — #59 (retrieval-grounded proposals), #67 (constrained decoding), #73 (`refrain`), #74 (typed validation gate). LLM proposes, deterministic validator decides.
5. **Evaluate honestly** — #85–#88 plus #89: selective risk and coverage alongside F-beta with β<1, over a gold corpus whose *own* ambiguity rate has been measured with κ/α.
