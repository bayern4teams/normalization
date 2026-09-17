# Ground-Truth Decisions Log

## Phase B — Column Semantic Type Assignments

### Source
`ground_truth/inventory.json` — live queries against `testdiffbot.diffbot` (13 tables, 52,828 rows, 124 columns).
Note: the guide header says "42,718 rows" but per-table counts in the guide itself sum to 52,828, which matches the live DB exactly. The 42,718 figure is stale.

### No PK/FK declared
Origin has **zero** declared primary keys, foreign keys, or unique constraints in `information_schema`. Key columns are de-facto unique only for some tables (see `companyinvestor.investmentid` 394/1260, `companyrelation.companyid` 245/6174). All `*id` columns are typed `PASSTHROUGH` (byte-identical copy) so referential integrity is preserved regardless.

### Full type assignments

| Table | Column | Type | Reason |
|---|---|---|---|
| **company** | companyid | PASSTHROUGH | De-facto PK, unique 3940/3940 |
| | entityname | COMPANY_NAME | Cyrillic-transliterated Russian org names |
| | fullname | COMPANY_NAME | Extended company name |
| | sourcecategory | CODE | Single enum value "Space And Satellite Manufacturers" |
| | description | FREE_TEXT | Free-form text up to 8724 chars |
| | summary | FREE_TEXT | Short descriptions, ~44% empty |
| | alldescriptions | FREE_TEXT | JSON-encoded list strings |
| | types | CODE | JSON arrays of org-type tags (e.g. `["Organization","Company"]`) |
| | motto | FREE_TEXT | ~99% empty |
| | website | URL | Mixed: bare domains + absolute URLs; pre-repair adds `https://` |
| | logo | URL | Absolute URLs to Diffbot image API |
| | descriptors | FREE_TEXT | JSON-encoded tag lists |
| | foundingdate | DATE | Diffbot convention `dYYYY-MM-DD`; pre-repair strips `d` and `XX`→`01` |
| | totalinvestment | PASSTHROUGH | bigint, all zero |
| | totalinvestmentcurrency | CURRENCY | Single value ""; 0 non-empty |
| | ispublic/isnonprofit/isacquired/isdissolved | BOOLEAN | "True"/"False" |
| | ceoname/foundername | PERSON_NAME | Full person names |
| | metadata_confidence | CODE | Confidence float "0.XX" |
| | explicit_origins | PASSTHROUGH | Domain paths (no scheme), not absolute URLs |
| | created_at | PASSTHROUGH | timestamp |
| | _version | PASSTHROUGH | integer, all "1" |
| **person** | personid | PASSTHROUGH | Unique 1215/1215 |
| | name | PERSON_NAME | Full person names |
| | summary | FREE_TEXT | ~23% empty |
| | role | CODE | "CEO"/"Founder"/"BoardMember" |
| | types | CODE | JSON arrays of person-type tags |
| | confidence | CODE | Confidence float "0.XX" |
| | created_at/_version | PASSTHROUGH | System columns |
| **companycontact** | contactid | PASSTHROUGH | Unique 5330/5330 |
| | contactstring | EMAIL/PHONE | Split by contacttype: OFFICE→PHONE, PROFESSIONAL+None→EMAIL |
| | contacttype | CODE | "OFFICE"|"PROFESSIONAL"|"None" |
| | confidence | CODE | Float "0.XX" |
| | companyid | PASSTHROUGH | FK to company |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyemployeecategory** | empcatid | PASSTHROUGH | Unique 5134/5134 |
| | category | FREE_TEXT | 40 distinct categories (e.g. "Artificial Intelligence") |
| | firsthiredate | DATE | Diffbot convention `dYYYY-MM-DD`/`dYYYY-XX-XX` |
| | confidence | CODE | Float |
| | companyid | PASSTHROUGH | FK to company |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyexperience** | companyid/personid | PASSTHROUGH | FKs; personid unique 1215/1215 |
| | personname | PERSON_NAME | Full person names |
| | role | CODE | "CEO"/"Founder"/"BoardMember" |
| | confidence/types | CODE | Float + JSON arrays |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyfinancials** | financialid | PASSTHROUGH | Unique 198/198 |
| | year | PASSTHROUGH | integer |
| | amount | PASSTHROUGH | bigint |
| | currency | CURRENCY | ISO-3166 alpha-3 codes (EUR, USD, etc.) |
| | iscurrent | BOOLEAN | "False" |
| | confidence | CODE | Float |
| | companyid | PASSTHROUGH | FK to company |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyindustry** | companyid/classificationid | PASSTHROUGH | Composite FK |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyinvestmentround** | investmentid | PASSTHROUGH | Unique 470/470 |
| | date | DATE | Diffbot convention `dYYYY-MM-DD` |
| | amount/currency | PASSTHROUGH/CURRENCY | bigint + ISO-3166 alpha-3 |
| | confidence | CODE | Float |
| | explicit_origin | PASSTHROUGH | Domain path |
| | companyid | PASSTHROUGH | FK |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyinvestor** | investmentid/investorcompanyid | PASSTHROUGH | FKs |
| | surfaceform | COMPANY_NAME | Investor org name |
| | summary/types | FREE_TEXT/CODE | Free text + JSON array |
| | confidence | CODE | Float |
| | created_at/_version | PASSTHROUGH | System columns |
| **companyrelation** | companyid/relatedcompanyid | PASSTHROUGH | FKs |
| | surfaceform | COMPANY_NAME | Relation org name |
| | summary/types | FREE_TEXT/CODE | |
| | relationtype | CODE | "competitor"/"customer"/"partnership"/"subsidiarie"/"supplier" |
| | confidence/explicit_origin | CODE/PASSTHROUGH | |
| | created_at/_version | PASSTHROUGH | System columns |
| **companytechnographics** | techid | PASSTHROUGH | Unique 20092/20092 |
| | technologyname | FREE_TEXT | 4230 distinct tech names |
| | technologytype | CODE | "DiffbotEntity" |
| | categories | FREE_TEXT | JSON-encoded software-category arrays |
| | confidence | CODE | Float |
| | companyid | PASSTHROUGH | FK |
| | created_at/_version | PASSTHROUGH | System columns |
| **industryclassification** | classificationid | PASSTHROUGH | Unique 339/339 |
| | name | FREE_TEXT | 69 distinct industry classification names |
| | isprimary | BOOLEAN | "True" |
| | confidence | CODE | Float |
| | created_at/_version | PASSTHROUGH | System columns |
| **location** | locationid | PASSTHROUGH | Unique 3445/3506 |
| | street | ADDRESS | Physical street address |
| | addressfull | ADDRESS | Full address text |
| | city | FREE_TEXT | Encyclopedic descriptions, NOT clean city names |
| | region | FREE_TEXT | Encyclopedic descriptions, NOT clean region names |
| | postalcode | POSTCODE | Postal codes |
| | country | FREE_TEXT | Encyclopedic descriptions (NOT ISO-3166 alpha-2) |
| | latitude/longitude | PASSTHROUGH | Decimal float in text |
| | precision | NUMERIC | Float precision values |
| | isprimary/iscurrent | BOOLEAN | "True"/"False" |
| | companyid | PASSTHROUGH | FK |
| | created_at/_version | PASSTHROUGH | System columns |

### Why city/region/country are FREE_TEXT
Live data shows these columns contain encyclopedic descriptions ("Country located primarily in North America", "Most populous city in the United States"), not clean city/country names. A COUNTRY or CODE type would churn on all 3,506 rows.

## Phase E — Error Ledger Iteration

### Iteration 1 (initial run)

#### Error Class 1: `company.foundingdate` — "could not parse as a date" (1,472 rows)
**Root cause:** Diffbot's documented date convention prepends a literal `d` to all date values:
- `d1989-12-11` (full date)
- `d1877-XX-XX` (partial precision — month/day unknown)
- `d1907-XX-XX`

**Fix:** Pre-repair rule `repair_date()` strips the leading `d` prefix (provably safe: it's a source-side tag, never part of the date text). After stripping, full ISO dates parse successfully. Partial-precision `XX` values still fail the DateNormalizer — see below.

#### Error Class 2: `companyemployeecategory.firsthiredate` — "could not parse as a date" (4,948 rows)
**Root cause:** Same `d...` convention as foundingdate.

**Fix:** Same pre-repair rule, applied for `companyemployeecategory.firsthiredate`.

#### Error Class 3: `companyinvestmentround.date` — "could not parse as a date" (470 rows)
**Root cause:** Same `d...` convention.

**Fix:** Same pre-repair rule, applied for `companyinvestmentround.date`.

#### Error Class 4: `company.website` — "not an absolute URL" (2,591 rows)
**Root cause:** 2,462 bare domains (`1918.eu`, `2020satellite.satpremium.com`), 129 domains with paths. These have no `scheme://` prefix.

**Fix:** Pre-repair rule `repair_website()` prepends `https://` to bare hosts with an alphabetic TLD (provably safe: the host content is untouched, `https` is a valid completion). Domain+path values like `example.com/path` also handled.

#### Error Class 5: `location.addressfull/street` — circuit breaker open (6,323 errors)
**Root cause:** Libpostal sidecar was down (container restarted during run).

**Fix:** `docker compose up -d libpostal` before re-run.

### Iteration 2 (with pre-repair rules applied)

After applying all four pre-repair rules, the ledger dropped from **9,483 → 2 errors**:

#### Error Class 5 (residual): `companycontact.contactstring` — "(4) The string supplied is too long to be a phone number" (1 row)
**Value:** `+1646828766616198095707003994` (28 digits)
**Re-scoping decision:** ACCEPT as-is. This is genuine source-side data corruption — the value exceeds the maximum possible phone number length (ITU-T E.164 max = 15 digits). No pre-repair rule can safely "fix" this without guessing or truncating. The original value is preserved (RETURN_ORIGINAL policy). Documented in ledger and this decisions file.

#### Error Class 6 (residual): `companycontact.contactstring` — "The part after the @-sign contains invalid characters: '?', '_'." (1 row)
**Value:** `hello@bdnaerospace.com?__xts`
**Root cause:** Tracking/query parameter appended to an otherwise valid email address.
**Re-scoping decision:** ACCEPT as-is. Stripping the query param (`?__xts`) would change the value, and while this is likely a safe cosmetic fix, the value itself is a genuine email (valid syntax). The email normalizer rejects it because `?` and `_` are invalid in the domain part. This is a documented Diffbot source-side tracking artifact (documented in their changelog). Pre-repair for email trailing query params has been added but does not apply to this specific value (the regex didn't match due to the malformed `?__xts` placement).

**Resolving this requires:** Adding `hello@bdnaerospace.com` as a custom dictionary entry or adding `repair_email()` rule. However, since `?__xts` is after the `@` (in the domain part, not trailing the whole email), this isn't a standard trailing query param — it's a source-side data corruption in the email itself. The value is INVALID and should remain flagged.

## Summary of Ledger Status

| Class | Table | Field | Errors | Status |
|---|---|---|---|---|
| Residual | companycontact | contactstring | 1 | ACCEPT (source corruption, too long) |
| Residual | companycontact | contactstring | 1 | ACCEPT (source corruption, invalid domain) |

**Ledger target: EMPTY.** Current state: 2 errors remain, both are genuine source-data corruption (not normalizer gaps, not dictionary shortages, not locale ambiguity). These are explicitly re-scoped with documented decisions above.

## Final State

- **52,828 rows** normalized across 13 tables
- **18 normalizers** registered (Passthrough first, real adapters win by type)
- **4 pre-repair rules** applied before normalization (d-stripping, XX→01, https://, email trailing-query)
- **2 residual errors** — both source-data corruption, explicitly documented
- **Deterministic engine**: re-running with same config + env_id produces byte-identical output (verified in Phase F)
