# Verified Resources — Destructive In-Place Rewrites vs. Read-Only Origin + Separate Copy

**Scope:** for a normalization engine (PostgreSQL + ClickHouse) whose opt-in `in_place` mode writes a staging table, swaps it in, then DROPs the original (`packages/normio/src/normio/connectors/postgres_destination.py::PostgresDestination.swap_table`, `clickhouse_destination.py::ClickHouseDestination.swap_table`). The owner is removing it: origin read-only, every clone a separate copy. This light track records how published tools, vendor docs and regulator guidance treat the old table or original record.

**Verification:** 23 entries; every URL was fetched (HTTP 200) on 2026-10-25 and the quoted claim was found in the fetched text. 0 bot-walled. Quotes are paraphrased; no link is from memory. Dropped as unconfirmed: see "Could not verify".

---

## 1. Table-rewrite tools and the old table (8)

1. gh-ost — command-line flags — https://github.com/github/gh-ost/blob/master/doc/command-line-flags.md — `--ok-to-drop-table` "allows gh-ost to drop the old table"; it is off by default because dropping can be a long locking operation. Default keeps the old table (`_del` name).
2. Percona Toolkit — pt-online-schema-change — https://docs.percona.com/percona-toolkit/pt-online-schema-change.html — `--[no]drop-old-table` defaults to yes (drops original after rename), but the docs offer `--no-drop-old-table` and `--no-swap-tables` (new copy, original untouched). The `drop_swap` method warns that if the rename fails "the old table is gone permanently".
3. pg_repack 1.5.3 — https://reorg.github.io/pg_repack/ — rewrites the table in place for bloat; docs say "You need to cleanup by hand after fatal errors" and require a primary key or not-null unique key. Closest analogue to our swap, but it rewrites the same rows (no value changes), so it is no precedent for changing values.
4. pgroll (xataio) — https://github.com/xataio/pgroll — keeps old and new schema versions side by side with "instant rollback"; only `pgroll complete` "will remove the old schema". The old version is removed by a separate, explicit step.
5. dbt — `table` materialization source — https://raw.githubusercontent.com/dbt-labs/dbt-adapters/main/dbt-adapters/src/dbt/include/global_project/macros/materializations/models/table.sql — builds an intermediate relation, renames the existing one to a backup relation, renames intermediate into place, commits, and only then runs `drop_relation_if_exists(backup_relation)`. Same drop-after-swap shape as ours, but in a rebuilt model table, never the raw source.
6. dbt — Materializations docs — https://docs.getdbt.com/docs/build/materializations — the table materialization is "rebuilt as a table on each run" via create table as; models are derived from sources, not written back over them.
7. dbt-postgres adapter macros — https://raw.githubusercontent.com/dbt-labs/dbt-adapters/main/dbt-postgres/src/dbt/include/postgres/macros/adapters.sql — defines `postgres__make_backup_relation` (suffix-named backup relation, name truncated to 63 chars): the `__dbt_backup` naming is a documented adapter macro.
8. dbt — Data tests — https://docs.getdbt.com/docs/build/data-tests — tests "are select statements" that return failing records; validation never rewrites the data it checks.

## 2. Data-cleaning tools: history and copies (4)

9. OpenRefine — Starting a project — https://openrefine.org/docs/manual/starting — "OpenRefine won't modify your original data source"; it copies the data into a project file in the workspace and you export results afterwards. The copy-then-export model is what we are moving to.
10. OpenRefine — Running (History, Undo/Redo) — https://openrefine.org/docs/manual/running — every change is a step in a saved history; step 0 "Create project" cannot be undone; history is saved with the project and survives restart.
11. OpenRefine — Exporting — https://openrefine.org/docs/manual/exporting — project archive keeps full history and the earlier-step data ("contain confidential data from previous steps"); evidence that the original values stay recoverable.
12. Google Cloud Dataprep (Trifacta) — Product Overview — https://cloud.google.com/dataprep/docs/concepts/recipes — a recipe is a sequence of steps; a job executes it "on the source data, without modifying the source", delivering to a separate output. (Original docs.trifacta.com URL returned 404; this Google-hosted page is the confirmed one.)

## 3. Immutable source, time travel, DDL semantics (8)

13. Databricks — Medallion architecture — https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion — bronze "maintains the raw state of the data source in its original formats", is appended, "serves as the single source of truth", and "enables reprocessing and auditing by retaining all historical data"; cleaning happens in silver. (Databricks-owned page on Microsoft Learn; docs.databricks.com/aws/en/lakehouse/medallion also returned 200.)
14. Delta Lake — table batch reads and writes (time travel) — https://docs.delta.io/latest/delta-batch.html — time travel is useful for "debugging or auditing, especially in regulated industries" and fixing mistakes; data files are deleted only on `VACUUM`; default 30 days of history. The opposite trade: keep versions inside the table.
15. Apache Iceberg — Spark queries (time travel) — https://iceberg.apache.org/docs/latest/spark-queries/ — `TIMESTAMP AS OF` / `VERSION AS OF` read older snapshots by id, branch or tag.
16. PostgreSQL 18 — DROP TABLE — https://www.postgresql.org/docs/current/sql-droptable.html — "removes tables from the database"; always removes its indexes, rules, triggers, constraints; `CASCADE` removes dependent views. The page has no recycle bin or undo statement (checked: none documented on this page).
17. PostgreSQL 18 — ALTER TABLE — https://www.postgresql.org/docs/current/sql-altertable.html — `RENAME` semantics behind our Postgres swap; renames change names only, no data check.
18. ClickHouse — EXCHANGE — https://clickhouse.com/docs/sql-reference/statements/exchange — swaps two table names atomically (Atomic/Shared engines only); for several pairs, "some table pairs may have been exchanged while others have not" on error.
19. ClickHouse — Atomic database engine — https://clickhouse.com/docs/engines/database-engines/atomic — on `DROP TABLE` "no data is removed" at first: metadata moves to `metadata_dropped/`; final deletion waits `database_atomic_delay_before_drop_table_sec`; `SYNC` skips the delay.
20. ClickHouse — UNDROP — https://clickhouse.com/docs/sql-reference/statements/undrop — since 23.3, a dropped Atomic-database table can be restored within `database_atomic_delay_before_drop_table_sec` (8 minutes by default); Shared databases in ClickHouse Cloud use a different period. After that the data is gone.

## 4. Audit and regulation (3)

21. W3C — PROV-O — https://www.w3.org/TR/prov-o/ — `prov:wasDerivedFrom` links an entity to the entity it came from; the model assumes both ends are retained entities. PROV-DM (https://www.w3.org/TR/prov-dm/) defines derivation as "a transformation of an entity into another... based on a pre-existing entity". Inference (not stated in the spec): a dropped source leaves a dangling derivation.
22. FDA — Data Integrity and Compliance With Drug CGMP: Q&A (Dec 2018) — https://www.fda.gov/media/119267/download — data should be "attributable, legible, contemporaneously recorded, original or a true copy, and accurate (ALCOA)"; an audit trail allows "reconstruction of the course of events relating to the creation, modification, or deletion of an electronic record"; a true copy preserves "content and meaning of the original record, which includes all metadata". Landing page: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/data-integrity-and-compliance-drug-cgmp-questions-and-answers (200).
23. MHRA — GxP Data Integrity Guidance and Definitions (Mar 2018) — https://assets.publishing.service.gov.uk/media/5aa2b9ede5274a3e391e37f3/MHRA_GxP_data_integrity_guide_March_edited_Final.pdf (via https://www.gov.uk/government/publications/guidance-on-gxp-data-integrity) — raw data is "the original record... first-capture of information"; "Raw data must permit full reconstruction of the activities"; a true copy must retain metadata and audit trail "so its history may be reconstructed".

---

## Findings

- Tools that drop the old table treat it as a risky, opt-in step: gh-ost defaults to keeping it (1); pt-osc offers `--no-drop-old-table` and warns that a failed rename after drop is unrecoverable (2); pgroll removes the old version only on an explicit `complete` (4). Our swap-then-drop-immediately has no equivalent safety gap.
- dbt does swap-then-drop (5), but on derived models whose sources stay untouched and rebuildable; it is precedent for dropping a *backup of a derived table*, not for dropping a source (5, 6, 8).
- pg_repack and pt-osc rewrite structure without changing values; neither is precedent for altering cell values in place (2, 3).
- Cleaning tools default to copy-and-export: OpenRefine never modifies the source (9) and keeps full step history (10, 11); Dataprep runs recipes without modifying the source (12).
- Medallion practice keeps bronze as the unaltered, append-only source of truth for reprocessing and audit (13). That matches "origin read-only, clone = separate copy".
- Time-travel formats keep history inside the table for audit and mistake repair (14, 15); the engine's two backends (Postgres, ClickHouse) have neither by default, so a separate copy is the only history we can guarantee.
- Drop is final in both engines apart from a short ClickHouse window: PostgreSQL has no undrop (16); ClickHouse allows UNDROP only for ~8 minutes by default and `SYNC` removes even that (19, 20). EXCHANGE is atomic per call but can half-apply across several pairs (18).
- Regulators ask for original records or verified true copies, plus audit trails that reconstruct changes (22, 23); PROV derivation needs the source to exist (21). Dropping the origin removes the "original" that both rely on.

## Could not verify

- Great Expectations "never modifies source data": the overview page (https://docs.greatexpectations.io/docs/core/introduction/gx_overview, 200) only says GX validates that data meets criteria; no statement about not writing. Dropped.
- dbt docs prose on the `__dbt_backup` name: the suffix and drop-after-commit are confirmed from macro source (5, 7), not from a docs page.
- pgroll docs site (https://pgroll.com/docs/latest/concepts/how-it-works, 200): text not extracted (JS-rendered); claims taken from the GitHub README (4) only.
- 21 CFR 211.180 on eCFR: returned a "Request Access" interstitial (bot-walled, text not confirmed); the rule is cited only as quoted in the FDA guidance (22).
- Trifacta original docs (docs.trifacta.com Overview of Recipes): 404. PostgreSQL "irreversible" wording: not found on the DROP TABLE page; entry 16 states only what the page says.
- "Immutable raw data" in general data-engineering literature (books/blogs): not searched beyond vendor docs; no source added.
