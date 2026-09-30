# Relational schema normalization + numeric/feature normalization — verified resources

Source: delegated deep-research sweep (deleg_e5257f89 task 2), 2026-09-30.
Every URL fetched live at compile time. Markers: **[T]** teaching · **[P]**
production-usable tool · **[R]** research paper.

## "Normalization" means two different things — decide which one you mean

| If your project… | You want | Section |
|---|---|---|
| restructures tables to remove redundancy/update anomalies | **relational schema normalization** (1NF→6NF, FD/key discovery) | A |
| rescales numeric columns so a model can learn from them | **feature normalization** (z-score, min-max, quantile, …) | B |

---

# Part A — Relational / schema normalization

### A1. Foundational papers (the normal forms, from the source)

1. **Codd (1970), "A Relational Model of Data for Large Shared Data Banks"** — https://www.seas.upenn.edu/~zives/03f/cis550/codd.pdf — **[R]** origin of the relational model and 1NF.
2. **Codd (1971), "Further Normalization of the Data Base Relational Model" (IBM RJ909)** — https://forum.thethirdmanifesto.com/wp-content/uploads/asgarosforum/987737/00-efc-further-normalization.pdf — **[R]** where 2NF and 3NF are actually defined.
3. **Fagin (1977), "Multivalued dependencies and a new normal form"** — https://dl.acm.org/doi/10.1145/320557.320571 — **[R]** defines **4NF**.
4. **Fagin (1979), "Normal forms and relational database operators"** — https://research.ibm.com/publications/normal-forms-and-relational-database-operators — **[R]** defines **5NF / PJNF**.
5. **Fagin (1981), "A Normal Form … Based on Domains and Keys"** — https://research.ibm.com/publications/a-normal-form-for-relational-databases-that-is-based-on-domains-and-keys — **[R]** **DKNF**.
6. **Bernstein (1976), "Synthesizing third normal form relations from functional dependencies"** — https://dl.acm.org/doi/10.1145/320493.320489 — **[R]** the classic *synthesis* algorithm.
7. **Beeri & Bernstein (1979), "Computational problems related to the design of normal form relational schemas"** — https://dl.acm.org/doi/10.1145/320064.320066 — **[R]** why BCNF testing/decomposition is computationally hard.

### A2. Normal-form reference & teaching material

8. **Silberschatz/Korth/Sudarshan, *Database System Concepts* — "Relational Database Design" slides** — https://www.db-book.com/slides-dir/PDF-dir/ch13.pdf — **[T]** best single teaching artifact.
9. **CMU 15-445/645 Database Systems** — https://15445.courses.cs.cmu.edu/ — **[T]**
10. **Wikipedia: Database normalization** — https://en.wikipedia.org/wiki/Database_normalization — **[T]**
11. **Date, *Database Design and Relational Theory: Normal Forms and All That Jazz*** — https://doi.org/10.1007/978-1-4842-5540-7 — **[T]**
12. **RelaX relational algebra calculator** — https://dbis-uibk.github.io/relax/ — **[P/T]** prove a decomposition is lossless before migrating data.

### A3. Functional-dependency discovery — algorithms

13. **"Functional Dependency Discovery: An Experimental Evaluation of Seven Algorithms" (Papenbrock et al., VLDB 2015)** — https://www.vldb.org/pvldb/vol8/p1082-papenbrock.pdf — **[R]** ⭐ read first.
14. **TANE (Huhtala et al., 1999)** — https://cs.helsinki.fi/u/htoivone/pubs/tane_99.pdf — **[R]**
15. **TANE project page + reference implementation** — https://cs.helsinki.fi/research/fdk/datamining/tane — **[P]**
16. **FUN (Novelli & Cicchetti, ICDT 2001)** — https://link.springer.com/chapter/10.1007/3-540-44503-X_13 — **[R]**
17. **FD_Mine (Yao, Hamilton & Butz, ICDM 2002)** — https://www2.cs.uregina.ca/~butz/publications/icdm02.pdf — **[R]**
18. **DFD (Abedjan et al., CIKM 2014)** — https://hpi.de/oldsite/fileadmin/user_upload/fachgebiete/naumann/publications/PDFs/2014_abedjan_dfd.pdf — **[R]**
19. **HyFD (Papenbrock & Naumann, SIGMOD 2016)** — https://hpi.de/fileadmin/user_upload/fachgebiete/naumann/publications/PDFs/2016_papenbrock_a.pdf — **[R]** ⭐ the one to implement.
20. **Pyro — "Efficient Discovery of Approximate Dependencies" (VLDB 2018)** — https://www.vldb.org/pvldb/vol11/p759-kruse.pdf — **[R]** essential for dirty data.
21. **Pyro source code** — https://github.com/HPI-Information-Systems/pyro — **[P]**
22. **Abedjan, Golab & Naumann, "Profiling relational data: a survey" (VLDB J. 2015)** — https://dataresponsibly.github.io/courses/documents/Abedjan_2015.pdf — **[R]**
23. **Abedjan, Golab, Naumann & Papenbrock, *Data Profiling* (book)** — https://link.springer.com/book/10.1007/978-3-031-01865-7 — **[T]**

### A4. Discovery tools you can run today

24. **Desbordante (C++ profiler, Python bindings)** — https://github.com/Desbordante/desbordante-core — **[P]** ⭐ FDs, approximate FDs, UCCs, INDs, order dependencies, denial constraints.
25. **Desbordante on PyPI** — https://pypi.org/project/desbordante — **[P]** start here.
26. **Metanome (HPI) — data profiling platform** — https://hpi.de/en/naumann/projects/data-profiling-and-analytics/metanome-data-profiling.html — **[P]**
27. **Metanome source** — https://github.com/HPI-Information-Systems/Metanome — **[P]**
28. **metanome-algorithms repo** — https://github.com/HPI-Information-Systems/metanome-algorithms — **[P]**
29. **FDTool (US EPA) — pure-Python FD miner** — https://github.com/USEPA/FDTool — **[P]** · PyPI: https://pypi.org/project/fdtool

### A5. Keys, unique column combinations, inclusion dependencies

30. **"Data-driven Schema Normalization" (Papenbrock & Naumann, EDBT 2017)** — https://www.openproceedings.org/2017/conf/edbt/paper-89.pdf — **[R]** ⭐ discover FDs on real data → emit a BCNF decomposition.
31. **HyUCC — hybrid unique column combination discovery (2017)** — https://hpi.de/fileadmin/user_upload/fachgebiete/naumann/publications/2017/paper.pdf — **[R]**
32. **DUCC — "Scalable discovery of unique column combinations" (VLDB 2014)** — http://www.vldb.org/pvldb/vol7/p301-heise.pdf — **[R]**
33. **HPIValid — hitting-set UCC enumeration (VLDB 2020)** — https://www.vldb.org/pvldb/vol13/p2270-birnick.pdf — **[R]**
34. **SPIDER — "Efficiently Detecting Inclusion Dependencies" (ICDE 2007)** — https://hpi.de/fileadmin/user_upload/fachgebiete/naumann/publications/PDFs/2007_bauckmann_efficiently.pdf — **[R]**
35. **BINDER — "Divide & conquer-based inclusion dependency discovery" (VLDB 2015)** — https://dl.acm.org/doi/10.14778/2752939.2752946 — **[R]** · configs: https://hpi.de/naumann/projects/repeatability/data-profiling/metanome-ind-algorithms.html
36. **PostgreSQL constraint documentation** — https://www.postgresql.org/docs/current/ddl-constraints.html — **[P]**
37. **AWS Deequ — constraint suggestion** — https://github.com/awslabs/deequ/blob/master/src/main/scala/com/amazon/deequ/examples/constraint_suggestion_example.md — **[P]**
38. **Great Expectations** — https://docs.greatexpectations.io/docs/core/introduction/ — **[P]**

### A6. Schema matching & mapping

39. **Rahm & Bernstein, "A survey of approaches to automatic schema matching" (VLDB J. 2001)** — https://link.springer.com/article/10.1007/s007780100057 — **[R]** · free PDF: https://dbs.uni-leipzig.de/file/VLDBJ-Dec2001.pdf
40. **COMA (VLDB 2002)** — https://dbs.uni-leipzig.de/file/COMA.pdf — **[R]**
41. **Valentine (ICDE 2021)** — https://arxiv.org/abs/2010.07386 — **[R]** honest benchmark: most matchers underperform their papers.
42. **Valentine toolkit (code)** — https://github.com/delftdata/valentine — **[P]** · docs: https://delftdata.github.io/valentine/

### A7. Denormalization and analytics modeling (when *not* to normalize)

43. **Kimball Group — Dimensional Modeling Techniques** — https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/ — **[T/P]**
44. **Inmon vs. Kimball comparison (lecture deck)** — https://www.ismll.uni-hildesheim.de/lehre/bi-10s/script/Inmon-vs-Kimball.pdf — **[T]**
45. **Data Vault 2.0 introduction** — https://datavaultalliance.com/engineering/data-vault-2-0-an-introduction/ — **[T/P]**
46. **Anchor Modeling — the 6NF paper** — https://anchormodeling.com/wp-content/uploads/2010/08/6nf.pdf — **[R]**
47. **Anchor Modeling home / online modeler** — https://anchormodeling.com/ — **[P]**
48. **dbt — "How we structure our dbt projects"** — https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview — **[P]**
49. **ClickHouse — "When to denormalize, when to join"** — https://clickhouse.com/resources/engineering/when-to-denormalize-when-to-join — **[P]**

### A8. Temporal data / 6NF

50. **Date, Darwen & Lorentzos, *Temporal Data and the Relational Model*** — https://shop.elsevier.com/books/temporal-data-and-the-relational-model/date/978-1-55860-855-9 — **[T]**
51. **Darwen's temporal-data course notes (free PDF)** — https://www.dcs.warwick.ac.uk/~hugh/TTM/DTATRM.pdf — **[T]**
52. **Snodgrass, *Developing Time-Oriented Database Applications in SQL* (free PDF)** — https://cs.ulb.ac.be/public/_media/teaching/infoh415/tdbbook.pdf — **[T]**

### A9. JSON / semi-structured normalization

53. **`pandas.json_normalize`** — https://pandas.pydata.org/docs/reference/api/pandas.json_normalize.html — **[P]**
54. **Spark `DataFrameReader.json` (schema inference)** — https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrameReader.json.html — **[P]**
55. **DuckDB JSON support** — https://duckdb.org/docs/stable/data/json/overview.html — **[P]**
56. **PostgreSQL JSON functions** — https://www.postgresql.org/docs/current/functions-json.html — **[P]**
57. **GenSON — JSON Schema inference in Python** — https://github.com/wolverdude/genson — **[P]**
58. **Baazizi et al., "Schema Inference for Massive JSON Datasets" (EDBT 2017)** — https://openproceedings.org/2017/conf/edbt/paper-62.pdf — **[R]**
59. **"Schemas and Types for JSON Data" (EDBT 2019 tutorial)** — https://openproceedings.org/2019/conf/edbt/EDBT_tutorial_2.pdf — **[T]**

---

# Part B — Numeric / feature normalization

### B1. Core reference

60. **scikit-learn, "Preprocessing data" user guide** — https://scikit-learn.org/stable/modules/preprocessing.html — **[P]** ⭐
61. **"Compare the effect of different scalers on data with outliers"** — https://scikit-learn.org/stable/auto_examples/preprocessing/plot_all_scaling.html — **[P]** ⭐ the actual decision aid.
62. **Google ML Crash Course — "Numerical data: Normalization"** — https://developers.google.com/machine-learning/crash-course/numerical-data/normalization — **[T]**

### B2. The individual transforms

63. **`StandardScaler` (z-score)** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html — **[P]**
64. **`MinMaxScaler`** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.MinMaxScaler.html — **[P]** very outlier-sensitive.
65. **`RobustScaler` (median / IQR)** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.RobustScaler.html — **[P]** right default with outliers.
66. **`QuantileTransformer`** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.QuantileTransformer.html — **[P]**
67. **`PowerTransformer` (Box-Cox / Yeo-Johnson)** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.PowerTransformer.html — **[P]**
68. **`Normalizer` (unit-vector / L2 row scaling)** — https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.Normalizer.html — **[P]** ⚠ scales **rows, not columns** — commonly misused.
69. **`scipy.stats.boxcox`** — https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.boxcox.html — **[P]**
70. **`numpy.log1p`** — https://numpy.org/doc/stable/reference/generated/numpy.log1p.html — **[P]**
71. **Box & Cox (1964), "An Analysis of Transformations"** — https://www.jstor.org/stable/2984418 — **[R]**
72. **Yeo & Johnson (2000)** — https://www.jstor.org/stable/2673623 — **[R]**
73. **Feature-engine** — https://feature-engine.trainindata.com/en/latest/ — **[P]**

### B3. Pitfalls

74. **scikit-learn, "Common pitfalls and recommended practices"** — https://scikit-learn.org/stable/common_pitfalls.html — **[P]** ⭐ leakage: fit on train only.
75. **scikit-learn, "Pipelines and composite estimators"** — https://scikit-learn.org/stable/modules/compose.html — **[P]**
76. **Kaggle — "Data Leakage" lesson** — https://www.kaggle.com/code/alexisbcook/data-leakage — **[T]**

### B4. In-network normalization (neural nets)

77. **Batch Normalization (Ioffe & Szegedy, 2015)** — https://arxiv.org/abs/1502.03167 — **[R]**
78. **Layer Normalization (Ba, Kiros & Hinton, 2016)** — https://arxiv.org/abs/1607.06450 — **[R]**
79. **RMSNorm (Zhang & Sennrich, 2019)** — https://arxiv.org/abs/1910.07467 — **[R]**
80. **Group Normalization (Wu & He, 2018)** — https://arxiv.org/abs/1803.08494 — **[R]**
81. **"How Does Batch Normalization Help Optimization?" (Santurkar et al., 2018)** — https://arxiv.org/abs/1805.11604 — **[R]**
82. **"On Layer Normalization in the Transformer Architecture" (Xiong et al., 2020)** — https://arxiv.org/abs/2002.04745 — **[R]**
83. **PyTorch `BatchNorm1d`** — https://docs.pytorch.org/docs/stable/generated/torch.nn.BatchNorm1d.html — **[P]**

---

## Fast path if you only read four things

- **Theory:** #2 (Codd 1971) + #8 (db-book design slides)
- **Doing it on real data:** #13 (FD-algorithm shootout) → #30 (data-driven BCNF decomposition); run **#25 Desbordante** today
- **Feature normalization:** #60 + #61, then #74 (leakage)

## Verification notes

- All URLs checked live (HTTP 200 or successful content fetch).
- `dl.acm.org` returns **403 to automated clients** even for public pages, so ACM DOIs (#3, #6, #7, #35) are paired with free author PDFs where one exists.
- Rahm & Bernstein (#39) is DOI `10.1007/s007780100057` — the frequently copied `s001780100003` is a **404**.
- `academic.oup.com` blocks bots, so Yeo & Johnson (#72) is cited via JSTOR.
