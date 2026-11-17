# Format findings (Refract)

These are our own measurements. They build on prismbinder `docs/format/README.md`, which is the base spec.
Each finding is marked **verified** (backed by a test or script on the local corpus) or **hypothesis**.

Local corpus as of 2026-11-12: 13 of the user's `.prism` files, 56 of the user's `.pzfx` files, and about 170 samples bundled in the Prism 11.1.0 app (read only, never copied into the repo).

## ZIP container
- **verified:** our lossless writer (`refract/formats/zipio.py`) round-trips all 13 local `.prism` files byte for byte (`tests/test_formats_corpus.py`).
- **verified:** Python's stock zlib with `level=2, memLevel=9, wbits=-15` recompresses all 801 deflate streams in those files byte for byte. A replaced entry is therefore compressed exactly as Prism would compress it.

## PCFFGRA4 graph/layout binary
- **verified:** the framing is `<u16 tag><u32 len><payload>`. A tag with 0x4000 set and 0x8000 clear is a 2-byte close marker. A tag with 0x8000 set opens a container whose children follow in the stream.
- **verified:** a close marker can implicitly close children that are still open. Example: `0x8003` is never closed explicitly; the root's `0x4001` closes it. With that rule, 191 of 197 local blobs (52.8 MB) parse as a nested tree and reserialise byte for byte.
- **verified:** a container's length covers only its own header payload, not its children. Changing a child's size therefore needs no length fix-ups in its ancestors.
- **verified:** in a text object, the `0x802B` container header holds the text length as a u16 at offset 6 (275 of 275 cases), followed by `0x002C` with the raw single-byte text (no terminator), then `0x002D` and `0x002E`, which look like formatting runs (hypothesis).
- **verified:** in the user's column graphs, the 2nd `0x0017` axis chunk is the left Y axis (its data extent matches the table), the 1st is X, and the 3rd defaults to 0..100 (probably the right Y axis; hypothesis).
- **verified:** Prism 11.1 *Multiple Variables* graphs (bundled samples Wine, Gene Expression, Hierarchical Clustering) do **not** use PCFF. Their `data.bin` starts with `00 00 00 00 ee 80 68 01`, a second graph binary format that has not been analysed yet.
- **verified by E7 (Prism 11.1 Viewer):** PCFF blobs have **no checksum**. Prism renders edited text (same length, longer, and longer with a stale `0x802B` length field) without complaint.
- **verified by E7:** `0x802B` header u16@6 is redundant. Prism reads the text using the `0x002C` chunk length.
- **verified by E7:** `0x0017` is a **layout cache**. Prism recomputes it on open, and edits to it (range, log flag, data extent) have zero visible effect. Do not use it as the source of truth when writing.
- **verified by E7b/E7c:** editing the `0x8025` container *header* (min, max, log flag, tick) has no visible effect on the seed (a Prism 10.0.3 file). E7c's self-labelling titles confirm the probe files themselves were rendered. The header is therefore derived as well. Hypothesis under test in E7d: the user settings live in child chunks (`0x0103` scale, `0x00a2` …) that Prism 11 writes and the seed lacks, and their absence means "fully automatic".
- **verified by E7d:** child chunks of the `0x8025` axis container carry **axis appearance** (frame/offset). Transplanting a donor's children visibly moved the Y axis. They do not carry range or scale.
- **verified by E7e (written by us, rendered by Prism 11.1):** `0x00A5` (68 bytes, one per axis in X/Y/Y2 order) holds the axis **mode**.
  - +4 u32 flags: setting `0xC` makes Prism honour the `0x8025` header min/max (manual range). With the flags at 0 the axis is auto and Prism recomputes the range. Whether bit 2 and bit 3 independently mean min and max is untested.
  - +64 u16 = 1 switches the axis to log10 (Prism picks the range when the axis is auto). Writing (1, 1) at +64/+66 works; +66 alone is untested.
  - Bit 4 (`0x10`) is **not** manual tick spacing. With manual range, Prism still auto-picked a major tick of 1 over our 0.25. The manual-tick switch is still to be found.
  - On a manual log axis the "crosses at" value is read as an exponent: cross = 0 put the X axis at 10⁰ = 1. Location still to be found.
- **verified (E7–E7e):** `0x0017` and the `0x8025` header of an *auto* axis are recomputed on open. To write a range, set the `0x00A5` flags plus the `0x8025` min/max. Writing the `0x0017` cache is unnecessary (E7e-03 = E7e-01).
- **verified (corpus statistics), but derived (see above):** `0x8025` header layout, 9 per graph = 3 axes (X, Y, Y2) × 3 segments. Main segments are at positions 0/3/6. +0 u16 object id, +2 double min, +10 double max, +18 double (unknown, derived?), +28 u8 log10 flag, +54 double major tick interval. Log axes store exponents. min/max equal the drawn range on 1,696 of 1,710 axes; all 14 exceptions are segmented axes. Scale codes 2/3/4 in `0x0017`@46 (one sample each) are unmapped (log2? probability?).
- **verified:** a Prism-printed PDF (macOS "Save as PDF" from Viewer) is pure vector, has no watermark, and has extractable text. It is good enough for graph reference renders and for reading back result values (~11 significant digits).

## Bundle-level findings from phase-0 batch 2 (Prism 11.1 trial, automated)
- **verified (E1/E2):** bundles synthesised by `refract/formats/bundle_builder.py` open without warnings for column, grouped (replicates, mean/SD/N), XY (single, replicates) and parts-of-whole tables. `createdBy.name = "Refract"` is accepted. Y data sets need `decimalsLength`: without it Prism displays 0 decimals (stored values are unaffected).
- **verified (E2 re-save):** Prism normalises `replicate ranges` per contiguous group of subcolumns that share a row extent (e.g. `0~1` + `2` when the 3rd replicate is shorter), and omits `firstRow` when it is 0.
- **verified (E3):** frequency-distribution results are recomputed on every open. `results.json` and the ANALYSIS_VIEW result tables are caches. Prism rewrites `results.json` only when it is missing or the inputs changed; otherwise it keeps what is stored (even wrong values) while displaying fresh ones. It detects input changes without relying on `data.dt`.
- **verified (E4):** `data.dt` and `parameters.dt` are not validated on open. On save Prism writes a deterministic content-derived value (identical for identical content), so writers can emit any 32-hex placeholder.
- **verified (E5):** unknown ZIP entries (e.g. `x-refract/model.json`) survive a Prism open/save. Unknown top-level keys in `document.json` are dropped.
- **verified (E6/E6b):** the graph container header `0x8012` payload u16 equals the graph sheet's `fenID` (62/62 corpus graphs). A duplicate makes Prism report damage and drop the graph. Data binding follows the JSON `inputDataSets`: with only the JSON re-pointed, Prism redraws from the new table. Inner graph objects appear to carry document-wide ids as well (the copy rendered the original's title text), so copies need those renumbered.
- **verified (E8):** a graph sheet with a missing or empty `data.bin` triggers "file damaged". Omit the sheet instead.
- **verified:** our JSON writer reproduces 1,566 of 1,568 Prism JSON entries byte for byte. The 2 exceptions differ only in float32-derived coordinate rounding.

## Graph properties via Prism-generated controlled variants (batch 3)
- **verified (Prism script diff + our write, E7f):** manual major tick = `0x00A5` +4 flag `0x10000` plus `0x8025` +54. Prism writes `0x800C` for a manual range (bit 15 set as well); `0xC` alone is honoured.
- **verified negative (E7f-03/04):** `0x8025` +62/+70 are derived, not the axis crossing. The crossing setting is still unlocated and no script command sets it.
- **verified (E7i):** colours live in chunk `0x0852`, a `Zval` property store: `b"Zval" <u32 clen> <u32 rawlen> <zlib>`, decompressing to `Mval <type> <len> body Mend` (type 1 scalar, 5 dict of `Dkey/Dval…Dfin`, 6 array `Asiz/Aval…Afin`). 43 keys in the corpus, all colours (RGBA). Writing `SEDObject_Array[i]/XYPlot_Map/PCFF_Plot::fillcolor|errorcolor|BarBoxBordercolor` and `PCFF_Graph::bkgndcolor` renders as written, alpha included. Legacy RGB copies (`0x8028` +68/+76, `0x009c`, palette in `0x0082`/`0x00ed`) are ignored when the store is present. Parser: `refract/formats/pcff/propstore.py` (62/62 round trip; Prism's zlib level varies, 4/7/8).
- **verified (recalc batch):** displayed analysis results are recomputed on open for frequency distribution, paired t test, nonlinear regression and two-way ANOVA. Tampered `results.json` and tampered ANALYSIS_VIEW CSVs are never shown.

## Graph duplication (DuplicateFamily, batches 4-5): solved for single-graph families
Learned by having Prism run `GoTo D 1` + `DuplicateFamily "Copy of "` on 4 documents (grouped bars, column, parts-of-whole pie, XY with a curve fit), then diffing (`tools/pcff_diff.py`, `tools/check_idmap_coverage.py`, `tools/emulate_dupfamily.py`).
- **verified, byte for byte:** `refract/formats/graph_copy.duplicate_family()` produces the same copied graph blob as Prism (only the instance UUID differs), with the same data-set fenIDs and graph fenID, on the bar/grouped, column and pie documents (tests). On the dose-response document the first copy matches except the `0x0014` slot.
- **verified, pixel for pixel (Prism 11.1 renders):** same-data copies render identical to their originals (two grouped-bar documents: 0.0000%). The pie copy renders identical to Prism's own copy (0.0000%); its title is linked to the sheet name, so it reads "Copy of …" as in Prism. Copies with new data (values ×2) keep all styling and rescale the axes.
- **ID namespaces** (u16 fields, registry in `refract/formats/pcff/idmap.py`):
  - plot ids `0x8028`+0 (also `0x0015` entries, legend `0x002f`, plot frames, `0x80f6`+16, `0x00a9`+16 under plot objects).
  - **data-set fenIDs** (`0x8028`+4, `0x009c`+313, slot tables `0x0016`/`0x00a0`, legend `0x0030`, row-title refs `0x0027`+4 and `+20` fields).
  - text ids `0x802b`+0 (axis refs `0x0017`+48, `0x0013`+32, pie label refs `0x00f9`+64+12k).
  - axis-settings ids `0x8025`+0 (`0x0017`+54/56/58, `0x002a`, `0x000a`+20).
  - pie namespaces `pie`/`pie2`/`pie3`/`slice` (`0x009e`+64, `0x00db`+4 under `0x80fa`, `0x00f8`, `0x00f9`, `0x80f4`, `0x00f5`, `0x00f7`, `0x00a9`+16 under `0x80fa` type 17; `0x009c`+141, `0x80f6`+8).
  - graph fenID (`0x8012`, `0x0013`+8, `0x8018`, `0x009c`+113, `0x80f6`+12).
  - `0x00db`+158 frames take the framed object's id.
  - Ids need **not** be unique across graphs: ranges overlap between graphs in real documents. What matters is following Prism's allocation.
- **Allocation:** each counted namespace is renumbered sequentially from (max of its defining field over all graphs) + 2, in ascending order of old ids. Data-set fields follow the copied table's fenID map. New data-set fenIDs = max + 1 (Y sets in order, then row titles, then X). Data sheet fenID = max + 1; graph fenID = max + 2. Plot containers' `0x8020`+26 goes up by 1. Slots get −1 fill. `0x000a`+18/+298 = 0x40, `0x0013`+26 = 0, `0x0091` = 0, `0x0014` slots = max + family size. Without pie objects `0x009e`+64 = −1. Sheet JSON: "Copy of " title, `isCustomTitle: true`, everything else kept.
- **Open:** families of several graphs at once (Prism continues at +1 for the second graph; implemented but not verified) and families that include analyses (result tables, fit curves) are not covered. A copy of a graph alone on the *same* data has no Prism script equivalent. Use the family copy (copy the table too), which is also the "same graph, new data" template workflow.

## Phase 1: reading and writing data tables (verified against Prism)
- **Readers:** `refract/formats/prism_reader.py` (bundles) and `pzfx_reader.py` (XML) produce the format-neutral model in `refract/model/document.py`. `refract.formats.open_document` dispatches on magic bytes. Legacy all-binary `.pzf`/old `.pzt` files are recognised; their tables are inside PCFF and are not read yet.
- **verified (oracle = Prism's own `ExportTable`, run by `tools/prism_auto.py --tables-only`, compared by `tools/check_tables_vs_prism.py`): 398 of 398 tables equal**: 317 in the user's 67 files and 81 in GraphPad's bundled samples. Numbers must agree within Prism's display rounding; text must match exactly.
- **Prism export conventions learned along the way** (not file-format facts): no title row when every column title is empty; untitled empty data sets and empty row-title columns are omitted; excluded values get a trailing `*`; time X shown as H:MM:SS; "(Bad value)" is shown as `#N/A`.
- **Reader facts:** cells in XML files can use a decimal comma ("56,92015"), which Prism reads as a number. Titles can contain Symbol-font runs (`TGF<Font Face="Symbol">b</Font>1` = TGFβ1). Prism 11 Multiple Variables tables can hold in-table formula columns (`valuesStorageData`) whose values are **not stored** (Prism computes them on open), so the model flags them. ElementTree: never `a or b` on Elements, because a childless Element is falsy.
- **Writer:** `refract/formats/prism_writer.save_project`. **verified:** the CSV rebuilt from the model is byte-identical for all 124 bundle tables, and saving without edits returns all 27 bundles byte-identical. Edits (changed value, added row, Mean/SD/N cells, cleared replicate cell, 10 rows removed) all open in Prism and export exactly as written. Analyses recompute on the edited data (frequency counts 2130 → 2120), and graphs pick up added rows. Row spans match Prism's re-save; Prism 11 writes `lastRow` always and `firstRow` only when ≠ 0.

## Writing .pzfx files and converting them to .prism (E-pzfxsave, E-pzfxconvert)
- **In-place writer (verified):** `refract/formats/pzfx_writer.save_pzfx` rewrites only the `<Table>` elements whose content changed and splices them into the original bytes. Everything else stays byte-identical, including `<Template>`. Unchanged parts of a rewritten table are copied verbatim: its start tag, a title whose text is unchanged (it can hold `<Font>`/`<TextAlign>` markup), `FloatingNote`s, column start tags, unchanged `<d>` cells.
  - Saving without edits returns all 134 local `.pzfx` files byte-identical.
  - Five edited copies opened in Prism (value changed, value excluded, data set and table renamed, data set added). Prism's re-save holds exactly the edited tables, every graph, analysis and layout is still there, analyses recompute on the edited data, graphs draw the added data set and leave the excluded point out, and graphs of other tables are pixel-identical.
- **Layout Prism writes:** one element per line with the file's own line ending (CRLF in 130 of 134 files); `<d/>` for an empty cell, `<d Excluded="1">` for an excluded one, trailing empty cells left out.
- **Line breaks in cells:** Prism writes a cell's line break as a lone CR inside `<d>` (and `"\r"` in bundle CSV). An XML parser turns it into LF, so the reader escapes lone CRs as `&#13;` before parsing.
- **Multiple-variables columns** carry Prism's bookkeeping: `MVType` ("Manual|Categorical", "Continues", "Manual|Label"; Manual = set by hand), a `CategoryDictionary` (`id`, `firstRowUsage`, `numUsage`, `numExcluded`), and per cell `CellType`/`UserText`/`num`. Their `Decimals` can hold unrelated numbers (hundreds). The in-place writer refuses edits to such typed columns rather than guess the bookkeeping.
- **Conversion to .prism (verified, 61 files, 282 tables):** every table becomes a new bundle table (bundle_builder), then excluded values are written as an edit; the first info sheet's constants and notes are kept.
  - Prism's `ExportTable` of the converted file equals its export of the original `.pzfx` for 281 of 282 tables.
  - Exports are display values, so two things must be carried: each column's `Decimals` as `decimalsLength`, and Multiple-variables types. A categorical variable of numbers set by hand stays categorical with its dictionary's ids; `isManual`; label variables; categories listed by name, as in every Prism-saved file.
  - The one difference is an 8-digit integer label column of a GraphPad sample. Prism exports our copy in exponent notation although the stored cells and the data-set JSON equal Prism's own conversion.
  - The Template (graphs, analyses, layouts) is not converted.

## Estimation plots of t tests (E-estimation)
- **Data (verified on 8 view tables):** an analysis view sheet titled `<analysis>:Estimation Plot` (`flags: ["ANALYSIS_VIEW"]`, table format `view`, three Y data sets): group A, group B and `B\r-\rA`. For a paired test the third set holds each subject's difference. For unpaired and Welch tests it holds the low end of the difference's confidence interval, the difference of the means and the high end. The analysis's result sheet `Estimation Plot` (viewIdx 8) points at that sheet; its `graphId` exists only once the graph is made.
- **Drawing (measured on Prism's PDF of a paired plot):**
  - Categories at 0, 1 and 2 on a three-column Column geometry, with a divider at 1.5 and a frame line along the top.
  - A right axis whose zero is group A's mean, on the same scale as the left axis, with outward ticks. Its title sits 12 pt outside the labels and reads top to bottom.
  - Dotted lines at both groups' means across the plot.
  - Paired subjects joined by lines.
  - At the difference: the points, a mean bar 0.733 of the category pitch wide, and a confidence interval with caps 0.367 of the pitch wide.
  - The interval is the t interval of the differences, at the analysis's confidence level.

## Phase 2: statistics engine and Prism as oracle
- **verified:** analyses we write from scratch (`refract/formats/analysis_writer.add_analysis`: sheet + parameters + constants + empty results, no result sheets) are recognised and computed by Prism. Prism creates the result sheets itself. Prism computes **lazily**: results appear only after a results sheet has been displayed, so `tools/prism_auto.py` visits every results sheet (`GoTo R i`) before saving. `tools/stats_oracle.py` packages this as data in, full-precision `results.json` out.
- **Enum values found by probing:** T_TESTS_AND_NONPARAMETRIC `experimentalDesign` = PAIRED_T_TEST, UNPAIRED_T_TEST, WELCH_T_TEST, RATIO_PAIRED_T_TEST, MANN_WHITNEY_TEST, WILCOXON_TEST, KOLMOGOROV_SMIRNOV_TEST. Unknown names produce no result model. Schemas are not shipped with the app.
- **Parity (`tools/stats_parity.py`, 60 generated data pairs, column statistics + 7 designs): 112 result fields equal to ≤ 1e-9 relative.** Exceptions: the variance F-test P agrees only to 1.4e-8 (Prism's numerics), plus one K-S case (below).
- **Prism conventions reproduced:**
  - percentiles use the (n+1)p rule (type 6) clipped to min/max, and "90% percentiles" are the 10th and 90th
  - CV = SD/|mean|; skewness/kurtosis are bias-adjusted
  - pairing-effectiveness Pearson P = two-tailed / 2 in both fields
  - Spearman pairing P is exact for n ≤ 17 (permutation DP over mid-ranks, direction of the observed sign) and t-approximation / 2 for n ≥ 18
  - Mann-Whitney and Wilcoxon "exact" P are exact **conditional on ties** (DP over doubled mid-ranks); their approximate P uses a continuity correction on |stat − μ| without capping at 1; Wilcoxon drops zero differences, and `tieCount` = number of zero differences
  - K-S exact P is computed when C(n1+n2, n1) ≤ 60,000, exact conditional on ties; otherwise the Kolmogorov limit sf(√(n1n2/(n1+n2))·D)
- **Prism quirk (not reproduced):** in one case (5 vs 7 values, no ties) Prism's exact K-S P is 72/792 where the exact value is 92/792. Prism builds its ECDF from repeated +1/n additions, so D carries rounding error and a lattice point lying exactly on D is not counted.

## Phase 2 batch 2: one-way ANOVA and multiple comparisons (ONE_WAY_ANOVA)
- **Parameters:** schema `analyses/one_way_anova/parameters.schema.json`. `experimentalDesign` = ORDINARY_ANOVA, BROWN_FORSYTHE_ANOVA (Brown-Forsythe and Welch), KRUSKAL_WALLIS_TEST, REPEATED_MEASURES_ANOVA, FRIEDMAN_TEST. `postTests.type` = PAIRWISE_TESTS; `pairwiseDesign.type` = ALL_VS_ALL, CONTROL_VS_ALL, SELECTED_VS_SELECTED; `multipleComparisons.type` = STATISTICAL, FDR, NO_CORRECTION. Valid `statistical.test` values:

  | Context | Tests |
  |---|---|
  | ordinary, all pairs | TUKEY, BONFERRONI_SIDAK, HOLM_SIDAK, NEWMAN_KEULS |
  | ordinary, vs control | DUNNET, HOLM_SIDAK, BONFERRONI_SIDAK |
  | Brown-Forsythe/Welch | GAMES_HOWELL, DUNNET_T3, TAMHANE_T2 |
  | Kruskal-Wallis / Friedman | DUNN |
  | repeated measures | TUKEY |

  `pairwiseDesign.controlID.col` must name a real data set (idx, title, uid), or Prism resets the post tests. `add_analysis` fills it in from the input data sets.
- **Results layout:** `<design>Model` (ordinaryAnovaModel, brownForsytheAnovaModel, kruskalWallisTestModel, friedmanTestModel, repeatedMeasuresGlmAnovaModel). Post tests are nested in `<model>.multipleComparisons.tests[hash(col i)].value[hash(col j)].value`. Each pair carries `sample1`/`sample2` {mean, n}; for Dunn the mean is the mean rank. `descriptiveStatistics` sits beside the model; rank tests add `meanRanks`, RM adds `missing`. `compactLetterDisplay` is present but **not implemented**.
- **Parity (`tools/anova_parity.py`: 20 generated data sets × 19 configurations, plus options): 3,300+ result fields equal to ≤ 1e-9 relative (or 1e-13 absolute).** Exact-P probes are in `tools/anova_exact_probe.py`.
- **Prism algorithms identified:**
  - **Studentized range** = the Copenhaver-Holland Gauss-Legendre algorithm (as in R's `ptukey.c`). Prism agrees with it to ~1e-14 absolute. scipy's `studentized_range` differs by up to 1e-3 relative in the far tail. P = 1 − cdf.
  - **Dunnett P** = exact product-correlation integral, λ_i = √(n_i/(n_i+n_0)), agreeing to ~1e-15 absolute.
  - **Dunnett T3** = studentized maximum modulus over m = all pairs, at the Welch df **rounded to the nearest integer**. P = 1 − cdf, so it is exactly 1 when the cdf underflows, and **then Prism reports the CI as "undefined"**.
  - **Games-Howell** = Tukey on the Welch SE and df; the statistic is t, not q. **Tamhane T2** = Šídák on Welch t.
  - **Šídák** uses the naive 1 − (1 − p)^m. **Holm-Šídák** is step-down Šídák with running max.
  - **Newman-Keuls**: q = t√2 against the studentized range for r = number of means spanned. It is step-down: a range is tested only if both ranges one mean wider were tested and significant. Untested pairs get statistic "undefined", P = 1, and the plain t interval. Tested pairs get the q(r) interval.
  - **FDR (two-stage BKY) q-value** = BH-adjusted P × m0/m × (1+Q), capped at 1, where m0 = m − (stage-1 rejections at Q/(1+Q)) for the chosen Q. Prism 11 quirk (reproduced): `qValue.level` is stored as Q/100 and `isDiscovery` is tested against that stored level, while `discoveryCount` uses Q itself.
  - **Repeated measures post tests:** with Geisser-Greenhouse, SE is from the paired differences and df = n − 1. With `assumeSphericity`, SE = √(2·MS_residual/n) and df = (k−1)(n−1).
  - **Dunn:** mean-rank differences; the KW variance uses the ties correction; P × m (Bonferroni).
  - **Bartlett's test** is reported only when every group has ≥ 4 values (else `TOO_FEW_POINTS`). The Brown-Forsythe test is the median-centred Levene test.
  - **Exact P for Kruskal-Wallis and Friedman** (pValue = exact when available). These are exact permutation P conditional on the observed mid-ranks, so ties are allowed. Kruskal-Wallis is exact when the partition count N!/∏n_i! ≤ 2e9: exact at 1.63e9, not at 2.02e9. Friedman is exact when (k!)^n ≤ 1e9: exact at 3.7e8, not at 1.63e9. Ours uses symmetry-reduced DPs (`one_way.kw_exact_p`, `friedman_exact_p`) and matches Prism bit for bit. Worst case is ~12 s for six unequal groups near the limit.
  - The post-test `significanceLevel` applies only to the post tests. The ANOVA, Brown-Forsythe and Bartlett P levels stay 0.05. `swapDirection` reports pair (j, i) as mean_j − mean_i. The `report.*` switches add no result fields.
- **Known deviations (not reproduced):**
  - Prism's **Dunnett CI critical value** is 0.6e-4 to 3e-4 off the exact root of its own P function (sf at Prism's value is 0.04998 to 0.05001). It is one value per family and deterministic, but it is not bisection or secant on the same function, so its algorithm is unknown. Our CIs use the exact root, which shifts bounds by ≤ 4e-3 relative.
  - Prism's **T3 P near 1e-9** carries ~1e-10 absolute quadrature error.
- **Not implemented yet:** SELECTED_VS_SELECTED pairs; FDR methods other than BKY (enum names unprobed); repeated measures with missing values (Prism fits a mixed model); compact letter display; trend test.

## Phase 2 batch 3: two-way ANOVA (TWO_WAY_ANOVA)
- **Parameters:**
  - Schema `analyses/two_way_anova/parameters.schema.json`.
  - `experimentalDesign`:
    - ORDINARY_ANOVA
    - REPEATED_MEASURES_BY_ROWS: the row factor is repeated; in each column, replicate s is one subject.
    - REPEATED_MEASURES_BY_COLS: the column factor is repeated; in each row, replicate s is one subject.
    - REPEATED_MEASURES_BY_BOTH_FACTORS: replicate s is one subject measured in every cell.
  - `postTests.pairwiseTests.meansDesignType` = COMPARE_COLUMNS (column main effect), COMPARE_ROWS (row main effect), COMPARE_CELLS (all cells, as one family). `pairwiseDesign.type` takes the one-way values.
  - `options.includeInteractionTerm`.
  - Simple effects use COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_{SEPARATE_FAMILIES, SINGLE_FAMILY} and COMPARE_CELLS_BY_ROWS_WITHIN_COLUMNS_{…}. The names came from a sample the user made in Prism (`corpus/manual/tw_simple.prism`); 109 guessed names had all been rejected.
- **Ordinary model (verified):**
  - SS are Type III: drop-one increase in residual SS with sum-to-zero coding. An empty cell forces the main-effects model.
  - `variation` = 100·SS/SS_total.
  - `means` are least-squares means: cell means for the full model, additive-model predictions for the main-effects model; rows, cols and total are averages of those.
  - `isBalancedDesign` is always false for the main-effects model.
- **RM models (verified):**
  - **By rows / by cols:** split plot. The between factor is tested against subjects-within-groups. The repeated factor and the interaction are tested against the residual with GG ε from the pooled within-group covariance. `ggEpsilon` is omitted when the repeated factor has two levels.
  - **By both:** row vs S×R, column vs S×C, interaction vs residual, each with its own ε from orthonormal contrasts. ε = 1 is reported for a two-level factor.
  - The table lists `matchedFactorVsRowFactor` and `matchedFactorVsColFactor`, but no subjects row.
- **Post tests (verified):**
  - **Main effects:** compare LS means. Var = MS_resid·(L(X'X)⁻¹L'), i.e. mean over the other factor's levels of 1/n, divided by the number of levels.
  - **Cells:** one family over R·C cells, numbered row-major.
  - **Reported P values:** two-way always reports `pValueIndividual`. With Dunnett it equals the adjusted P (a Prism quirk).
  - **Dunnett:** λ uses the **total n** per level, not the LS variances.
  - **FDR:** q-values use the real Q as level and isDiscovery (no one-way /100 quirk). There is no `discoveryCount`. When stage 1 rejects everything (m0 = 0), Prism uses m0 = m.
- **Simple effects (verified, `corpus/auto/tw2`, 17 configurations, 1,649 fields equal):**
  - Results are nested by cell id like COMPARE_CELLS.
  - **Separate families:** one family per column (rows within columns) or per row (columns within rows). Each is adjusted on its own; Tukey uses k = levels in the family. Prism omits multipleComparisons when each family holds a single comparison.
  - **Single family:** all simple comparisons in one family. Prism replaces Tukey, Dunnett and Newman-Keuls with Bonferroni-Šídák.
  - **Control:** taken from `controlID.row` (rows within columns) or `controlID.col`.
  - **RM designs:** pairs that share subjects use paired differences (df = n − 1). Pairs of different subjects use a Welch t, except when the repeated factor has two levels: then the pooled within-cell MS is used, with df = df_subjects + df_residual.
- **Two-level factors:**
  - No multipleComparisons for that main effect. Instead `differenceBetweenColMeans` or `differenceBetweenRowMeans` gives {mean1, mean2, difference, SE, t CI on the error df}.
  - A 2 × 2 table adds `interaction` {meanDifference1, meanDifference2, interaction, SE, CI}. The additive model gives the same block with interaction = SE = 0 and no CI.
  - In RM designs each block uses the error term that tests that effect.
- **RM post-test rules:**
  - The repeated factor (by rows / by cols) and the cells (by both) use paired differences over **all** subjects, df = subjects − 1. With `assumeSphericity`, SE = √(2·MS_resid/subjects) on the residual df.
  - The between factor is compared (on MS subjects) only when the repeated factor has two levels; otherwise POSTTEST_DISABLED.
  - Main effects of the both-factors design give POSTTEST_DISABLED.
  - Cells of a one-factor RM design are silently skipped.
- **Parity (`tools/twoway_parity.py`: 12 grouped tables, balanced and unbalanced, 2–4 levels, 24 configurations): 2,193 fields equal to ≤ 1e-9.**
- **Known deviations:**
  - The Dunnett CI critical value, as in one-way.
  - **RM by both factors on 3 × 4 or 4 × 3 tables:** Prism's GG ε for the row factor and the interaction differs from the textbook value. It matches for 3×3, 4×4, 5×3, 3×5 and 5×4 (`tools/twoway_eps_probe.py`). Pooled, index-permuted and reweighted-contrast variants were tried, and none reproduce it.
- **Not implemented:** SELECTED_VS_SELECTED, RM with missing values (mixed model), compact letter display, effect sizes / goodness of fit reports.

## Phase 2 batch 4: multiple two-sample tests (MULTIPLE_TWO_SAMPLE_TESTS)
- **Parameter versions matter (verified):** Prism 11.1 writes `parameters.json` version `0.0.1` for MULTIPLE_TWO_SAMPLE_TESTS, ONE_WAY_ANOVA, TWO_WAY_ANOVA and T_TESTS_AND_NONPARAMETRIC (`0.0.2` SURVIVAL, `0.1.0` MULTIPLE_COX_REGRESSION). Older versions are migrated on open, and a migration can change meaning: written as `0.0.0`, MULTIPLE_TWO_SAMPLE_TESTS swaps EQUAL_SD and UNEQUAL_SD, so Prism computes the other test. `analysis_writer.VERSION` now writes the current version. Readers must apply the same swap to `0.0.0` documents.
- **Enums:**
  - `test` takes 7 values: MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS, …_UNEQUAL_SD_TESTS (Welch), MULTIPLE_PAIRED_TWO_SAMPLE_TESTS, MULTIPLE_RATIO_PAIRED_TWO_SAMPLE_TESTS, MULTIPLE_MANN_WHITNEY_TESTS, MULTIPLE_WILCOXON_TESTS, MULTIPLE_KOLMOGOROV_SMIRNOV_TESTS. An unknown value is kept as "UNKNOWN".
  - `multipleComparisons.statistical.test` = HOLM_SIDAK, BONFERRONI_DUNN, BONFERRONI_SIDAK.
  - `fdr.test` = BENJAMINI_KRIEGER_YEKUTIELI, BENJAMINI_HOCHBERG, BENJAMINI_YEKUTIELI.
  - `fdr.options.discoveryLevel` is in **percent**.
- **Layout:**
  - `summary` holds {correctionMethod, validTestCount, significantCount (or discoveryCount for FDR), threshold}.
  - `rows[hash(row)].value` = {<test>Model: {status, <test>: {…, pValue {value, level, isSignificant, rank, state}}, difference block}, pValueAdjusted | qValue}.
  - The adjusted P / q value sit **beside** the model.
  - `rank` is 0-based by exact P (table order for exact ties).
  - With swapDirection, mean1/mean2 swap as well as the sign.
- **Thresholds (verified):**
  - No correction: α.
  - Bonferroni-Dunn: α/m.
  - Bonferroni-Šídák: 1 − (1−α)^(1/m).
  - Holm-Šídák: the Šídák critical value of the last rejected step, 1 − (1−α)^(1/(m−k+1)).
  - BH: kQ/m.
  - BY: kQ/(m·Σ1/i).
  - BKY: k·Q/(1+Q)/m0.
  - FDR and Holm give `"undefined"` when nothing is rejected.
  - Each raw P has `level` = threshold; adjusted P and q values have level α / Q.
  - Method names include "Original FDR method (Benjamini and Hochberg)" and "Corrected FRD method (Benjamini and Yekutieli)" (sic).
- **Validity rules (verified):**
  - The pooled t test needs n1 + n2 ≥ 3. Welch, paired, ratio, Mann-Whitney and K-S need ≥ 2 per group (pair). Wilcoxon needs ≥ 3 pairs.
  - Failing rows are still reported with inner status TOO_FEW_POINTS: statistics "undefined", df = n − 2 for paired tests, means and rank sums filled in, Wilcoxon tieCount 0.
  - Mann-Whitney reports EQUAL_VALUES when one group is constant; it still counts as a valid test.
  - Exact Mann-Whitney/Wilcoxon P values are rational (count / C(n1+n2,n1) or 2^n). We snap them so that equal P values rank like Prism's.
- **Parity (`tools/multi_t_parity.py`, 22 tables × 23 configurations): 450 fields equal to ≤ 1e-9.**
- **Known deviation:** in ratio-paired TOO_FEW_POINTS rows, Prism's `geometricMeanOfRatios` matches no formula of the row's data (looks like stale state), so it is not reproduced.

## Phase 2 batch 5: one-sample tests and normality tests
- **ONE_SAMPLE_TESTS:**
  - `experimentalDesign` = ONE_SAMPLE_T_TEST, WILCOXON_SIGNED_RANK_TEST.
  - `samples[col]` holds `tTestModel` {tTest, discrepancy {discrepancy, SD, SE, CI, rSquared = t²/(t²+df)}} or `wilcoxonTestModel` {wilcoxonTest {zeroesStatus, sums, n, tieCount (= zero differences), pValue = exact, pValueExact, pValueApproximate}, discrepancy {median − hypothetical, CI}}, plus descriptiveStatistics.
  - Wilcoxon specifics:
    - Uses Pratt's method by default (`calc.usePrattMethod`): ranks include the zeros, which are then dropped.
    - The exact P is tie-conditional.
    - The approximate P uses |(|W−E|) − 0.5|/σ, the same quirk as the two-sample tests.
    - The median CI is the order-statistic (sign-test) interval: the narrowest with coverage ≥ 95%, and at least min..max. Its level is reported (75 / 87.5 / 93.75% for n = 3 / 4 / 5).
    - n < 3 gives TOO_FEW_POINTS.
- **NORMALITY_TESTS:**
  - Per column: `normalityModel` and `lognormalityModel`, each {D'Agostino-Pearson K2, Anderson-Darling A2, Shapiro-Wilk W, K-S distance, allTestsPassed, descriptiveStatistics}, plus `relativeLikelihoodTest` and `dataSummary`.
  - The parameter key is spelled `shaproWilks` (sic).
  - Algorithms:
    - K2 = D'Agostino 1990 omnibus (SciPy `normaltest`).
    - Anderson-Darling P = D'Agostino & Stephens with A* = A²(1 + 0.75/n + 2.25/n²).
    - Shapiro-Wilk = Royston. For n = 3 Prism uses the exact formula with **7-digit constants** 1.909859 and 1.047198; reproduced bit for bit.
    - K-S = Lilliefors distance with Dallal–Wilkinson P. P > 0.10 is reported as 0.1 with state P_VALUE_GREATER. For n > 100, D·(n/100)^0.49 at n = 100.
  - Minimum n: 8 (K2, A2), 3 (W), 5 (K-S); below that, TOO_FEW_POINTS.
  - Relative likelihood: (2πs²)^(−n/2)·e^(−n/2) with the n−1 SD (lognormal: of ln x, × ∏1/x). The ratio equals the MLE ratio.
  - Non-positive data: lognormalityModel {status NON_POSITIVE_VALUES} and relativeLikelihoodTest {UNDEFINED_LOGNORMAL_MODEL, preferred NORMAL}. `dataSummary.impossibleValues` is reported only when lognormality or the likelihood test is on.
- **Parity (`tools/column_tests_parity.py`: 6 tables × 13 sample sizes (2–120) × 7 configurations, with ties, zeros, negatives, values equal to the hypothetical mean): 2,699 fields equal to ≤ 1e-9, no exceptions.**

## Phase 2 batch 6: frequency distribution (FREQUENCY_DISTRIBUTION)
- **Parameters:** `calc.distributionType` = FREQUENCY, CUMULATIVE_FREQUENCY. `calc.tabulate` = VALUE_COUNT; the relative-frequency names are not found yet (16 candidates rejected). `calc.binWidth.type` = AUTO_BINS, NO_BINS. On save Prism writes its automatic choice into `binWidth.autoValue`, `binCenterFirst.autoValue` and `binCenterLast.autoValue`.
- **Results:** `results.json` holds only `dataSummary` (descriptive statistics) and `binsSummary` {binnedValuesCount, excludedValuesCount} per data set. The histogram itself is the ANALYSIS_VIEW result table "…:Frequency distribution", with bin centres as X and one count column per data set.
- **Automatic bins (`tools/freq_parity.py`, 40 generated tables):**
  - Per data set, width = range / (floor(log₂ n) + 2). GraphPad FAQ 1660 says 1 + log₂ n; Prism evidently rounds it up, and an exact power of two gets one more.
  - Average the widths over data sets and round down to 1/2/5 × 10^k. All-integer data round down to an integer, at least 1.
  - The first and last centres are min and max rounded to the nearest multiple of the width.
  - This reproduces **every single-data-set case**. Four multi-set tables that mix an all-integer data set with non-integer ones get a different width from Prism; the rule for that mix is not found (recorded in the parity tool as known).
- **Binning:** a value goes to bin floor((v − first)/w + 0.5), in plain floating point, as Prism: 0.0875 at w = 0.005 falls in the lower bin. NO_BINS lists each data set's sorted distinct values in turn (rows are not merged); counts sit in the data set's own rows and the other cells are blank. Cumulative is the running sum.
- **Parity:** with Prism's bins, all tables (counts, centres, cumulative, NO_BINS) and all results.json fields agree (141 field groups).

## Phase 2 batch 7: survival analysis (SURVIVAL)
- **Table:** `XYDataTable` with format `survival`. X is the time; each data set is one group, with the event code (1 event, 0 censored; `data.eventCode/censorCode`) in the subject's row and blank elsewhere. `bundle_builder` now writes these tables (kind "survival").
- **Results:**
  - `curveComparison` {logrankMantelCoxTest, gehanBreslowWilcoxonTest, logrankTestForTrend (≥ 3 groups)}: chiSquared, df, pValue.
  - `ratios` (2 groups): ratio and ratioReciprocal, each {medianSurvivalRatio, Mantel-Haenszel HR, log-rank HR, each with a CI}.
  - `dataSummary` per group: rowCount, blankRowCount, impossibleDataRowCount, censored/event counts, medianSurvival and its CI.
  - The KM curves, numbers at risk etc. are ANALYSIS_VIEW result tables.
- **Verified rules (`tools/survival_parity.py`, 16 tables with 2–4 groups and tied times, plus the bundled sample: all fields equal):**
  - The log-rank test uses the k−1 dimensional O−E quadratic form with the hypergeometric covariance. Gehan-Breslow-Wilcoxon weights by the number at risk. The trend test uses scores 1..k.
  - Mantel-Haenszel HR = exp((O−E)/V) with CI exp(± z/√V). Log-rank HR = (O₁/E₁)/(O₂/E₂) with CI exp(± z·√(1/E₁+1/E₂)). Median ratio CI = ratio·exp(± z·√(1/d₁+1/d₂)). **These intervals always use z = 1.96** and are labelled with ciLevel.
  - Median = first time with S ≤ 0.5. When S equals 0.5 exactly, it is the average with the next event time. It is "undefined", with no CI, when S stays above 0.5.
  - The median CI follows Brookmeyer–Crowley: the first times at which the log-log (Kalbfleisch–Prentice, "ASYMMETRICAL") band limits reach 0.5. Points with S = 0 are skipped, so +inf is possible. It is computed at ciLevel, **but labelled 95.0** whatever ciLevel is (Prism 11.1).
  - P-value levels are 1 − ciLevel/100.
- **Regression check:** with the corrected parameter versions (0.0.1), the t-test, one-way and two-way parity runs reproduce the earlier results exactly. The only differences are the already documented ones (K-S 72/792 quirk, Dunnett CI critical value, T3 tail).

## Phase 2 batch 8: correlation, simple linear regression, contingency tables
Names and layouts come from a Prism-made sample (`corpus/manual/batch2_samples.prism`). The rules come from `tools/xy_parity.py` (18 generated XY tables, 8 configurations) and `tools/contingency_parity.py` (16 tables, 2 × 2 to 4 × 2 and 2 × 5, with zero cells, 7 configurations). Every field agrees except the two known items listed at the end.

- **CORRELATION** (`refract.stats.xy_basic.correlation`). X is the control (`pairwiseDesign.controlID` idx −1) and each Y data set is correlated with it; replicates are averaged per row first.
  - Pearson: CI via Fisher z.
  - Spearman:
    - CI uses the Fieller variance 1.06/(n−3) and is "undefined" below n = 11.
    - Exact P for n ≤ 17. Two-sided means P(|S − E S| ≥ |S_obs − E S|), which differs from twice the smaller tail when there are ties.
    - Values equal to about 12 significant digits (averages such as 7.3 vs 7.300000000000001) are ranked as ties.
- **SIMPLE_LINEAR_REGRESSION**:
  - **Inverse-prediction intervals.** The X-intercept and "X when Y=…" (`calc.xCI.y` ≠ 0) use the Fieller inverse-prediction set. When the slope is not significant this becomes a half-line ("+inf"/"-inf").
  - **"Y when X=…"** (`calc.yCI.x` ≠ 0) is the fitted value with its SE and t CI.
  - **Line through a fixed point** (`model.constrainLineToFixedPoint`):
    - one free parameter; df = n − 1;
    - SE(Y-intercept) = |x0|·SE(slope);
    - r2 "undefined".
  - **`runsTest`** (`calc.departureFromLinearityTest`): residual signs in X order, with the one-sided exact Wald–Wolfowitz P(R ≤ runs). pValue and pValueExact are equal. Any repeated X value, with or without replicates, gives status SAMPLE_HAS_REPLICATES and zero counts.
  - **`modelComparisonTests`** (`calc.modelComparisonTest`, at least 2 data sets) is an ANCOVA:
    - slopeTest: pooled slope ΣSxy/ΣSxx, F(k−1, N−2k);
    - interceptTest, only when the slopes do not differ (P ≥ 0.05): pooledIntercept is the intercept of one line through all points, F(k−1, N−k−1).
- **CONTINGENCY_TABLE** (`refract.stats.contingency`):
  - **Layout.** Rows are groups and columns are outcomes. RR, difference, OR and sensitivity use the top-left 2 × 2, for larger tables too.
  - **Tests.**
    - `calc.method` takes FISHER_EXACT_TEST or CHI_SQUARE_TEST; no Yates or trend names were found (9 candidates rejected).
    - Fisher: two-sided for 2 × 2. "One-tailed" (`options.pValueTailType` = P_VALUE_ONE_TAILED) is the smaller one-sided P. R × C tables get the Fisher–Freeman–Halton P (network enumeration, relative tolerance 1e-7), two-sided in all cases.
    - Chi-square is uncorrected; z = √χ² for 2 × 2; the one-tailed P is half. R × C gets status CHI_WARNING when at least 20 % of expected counts are below 5 or any is below 1 (never for 2 × 2).
  - **Relative risk** (`ciMethod`):
    - KOOPMAN: asymptotic score interval.
    - KATZ_LOG: a zero count becomes 0.5 with totals unchanged, and that side of the interval becomes 0 / +inf.
  - **Difference** (`attributableRisk`): the value is |p1 − p2|.
    - NEWCOMBE_WILSON_CC (default) and NEWCOMBE_WILSON: Prism computes the Newcombe half-widths of p1 − p2, with the lower width from (p1 − l1, u2 − p2) and the upper from (u1 − p1, p2 − l2). It places them around |p1 − p2| without swapping when p1 < p2. With continuity correction it uses the raw Wilson-cc limits, with no x = 0 / x = n special cases and no clipping. The upper limit can therefore exceed 1.
    - ASYMPTOTIC: |p1 − p2| ± z·√(p̄(1 − p̄)(1/n1 + 1/n2)), using the pooled SE.
    - NNT is 1/|AR|; its CI is "undefined" when the AR interval includes 0.
  - **Odds ratio:**
    - BAPTISTA_PIKE (default): accepts ψ when P(outcomes less probable than the observed one) + ½·P(observed) ≥ α. This acceptability is a sawtooth in ψ, and Prism reports the edges of the piece that contains the estimate.
    - WOOLF_LOGIT: switches to Gart's adjusted logit (0.5 added to every cell, ratio included) when a cell is 0, and is then labelled GART_ADJUSTED_LOGIT.
    - Results name the method `CI_PROPORTIONS_RATIO_METHOD_*`.
  - **Sensitivity, specificity, PPV, NPV:**
    - WILSON_BROWN (default) is Wilson with Brown–Cai–DasGupta Poisson ends: lower = χ²(α; 2x)/2n for x = 1, 2, and the mirror image for n − x = 1, 2, with one-sided α.
    - WILSON and CLOPPER_PEARSON are also available.
    - likelihoodRatio = sens/(1 − spec), "undefined" when spec = 1.
  - `associationMeasures`: no output was seen.
- **Known, not reproduced:**
  - Prism's Koopman interval when a row proportion is 1 ([[37, 0], [38, 22]] gives 1.57894..1.57944) looks like a solver artefact.
  - The X-intercept CI of a line through a fixed point: no Fieller or delta-method variant tried matches.

## Phase 2 batch 9: nonlinear regression (NONLINEAR_REGRESSION)
Rules come from `tools/nonlinear_parity.py`: 14 data sets generated from the 7 built-in equations in `corpus/seeds/nonlinear_equations.json`, 1–2 data sets each, 1–3 replicates. It runs 4 configurations: profile-likelihood CI, Wald CI, a CONST constraint and a LESS constraint. 734 field groups agree to 1e-6 and 32 more to 1e-4.

- **Model.** The equation text travels in the parameters: `model.equation.definition`, `parameters`, `initialValueRules`, `transforms`. `refract.stats.equation` parses Prism's equation language into a vectorised function without evaluating user code:
  - `^` binds tighter than unary minus;
  - `log` is log10;
  - `IF(cond, a, b)` is supported;
  - intermediate-variable lines are allowed.
- **Results** (`models[*].value`):
  - `parameters.<name>`: {status, estimate, se, ci}, wrapped in a per-model hash layer.
  - `transforms` (e.g. EC50 = 10^LogEC50; Span).
  - `covariance` (correlation matrix).
  - `goodnessOfFit` {df, r2, adjR2, ss, syx, rmse, aicc}. r2 and ss are wrapped in another hash layer.
  - `dataSummary`, `iterationCount` (not reproduced), plus the equation text and TeX.
- **Verified rules:**
  - **Profile likelihood** (`confidence.ciMethod` PROFILE_LIKELIHOOD; the other value is WALD): the limits are where the re-minimised SS reaches SS·(1 + F(level; 1, df)/df). We march outwards from the estimate in growing steps and take the first crossing. A limit with no crossing within 6 SE is "undefined": Prism's defined limits reach at most 4.3 SE, and its undefined ones cross only at 9.6 SE or beyond (batch 11h; 100 SE before).
  - **Transforms:** an ASYMMETRICAL one-parameter transform maps the CI endpoints. Otherwise the SE comes from the delta method, and under profile likelihood the CI is "undefined".
  - **Goodness of fit:** rmse = √(SS/(n−1)); AICc counts K = free parameters + 1; adjR2 uses df = n − free parameters.
  - **Constraints:** `model.constraints` = {name: {"type": T, "value": v}}, with T = CONST, GREATER or LESS. Nine other names and a per-data-set list form were all reset to UNKNOWN.
    - CONST: the parameter has status CONSTANT, se and CI are "undefined", and its covariance rows and columns are "undefined"; it does not count in df.
    - An active LESS bound gives the parameter status HIT_CONSTRAINT with no SE or CI, and the model status HIT_CONSTRAINT. It still counts in df and in the covariance.
    - Only when the bound is inactive do the fits agree.
- **Known, not reproduced:**
  - **Convergence:** Prism stops at its "medium" convergence criterion. The variable-slope and Gaussian fits therefore differ from the exact least-squares optimum in the 6th digit; our SS is lower or equal. Iteration counts differ.
  - **Active bound:** with a GREATER or an active LESS bound, Prism's fit stops just inside the bound with a larger SS than the constrained optimum (e.g. 164.3 vs 113.1). With GREATER on a straight line it did not re-optimise the slope at all (r² = −5). Profile intervals near a bound follow that optimiser: sometimes the bound, sometimes "undefined".
  - **Non-identifiable parameter** (HillSlope SE 4.0 > estimate 2.4): the profile is symmetric in its sign and Prism picks the far crossing (−1.034 rather than +1.034).
- **Writer fix:** `bundle_builder.fmt_cell` now converts numpy scalars to `float`. Under numpy 2 they were written to data.csv as "np.float64(2.158)", and Prism then reported INVALID_DATA.

## Phase 2 batch 10: mixed-effects model for repeated measures with missing values
When an RM one-way or two-way table has a missing value, Prism 11.1 fits a mixed model. The results key is `repeatedMeasuresRemlAnovaModel` instead of `repeatedMeasuresGlmAnovaModel`, and the analysis carries the warning MISSING_VALUES. Prism 11.1 has no denominator-df option, so it uses its "legacy" method. The rules come from `refract.stats.mixed` and `tools/mixed_parity.py`: 10 one-way and 10 two-way tables with 1–3 missing values, 4 + 15 configurations (Tukey, Dunnett, Holm-Šídák, sphericity assumed, rows/columns/cells and simple effects). **1420 field groups agree to 1e-5**; Prism's iterative fit leaves its variance components about 1e-6 from the optimum.
- **Model:** fixed effects are effect-coded with the interaction. The random intercepts are:
  - one-way: subject;
  - two-way with one repeated factor: subject;
  - both factors repeated: subject, subject × row and subject × column.

  The fit is REML, profiled over the variance ratios, which are ≥ 0.
- **Removed random effects:** components estimated at 0 are removed (`repeatedMeasures.removeNonPositiveRandomEffects`). The warning is RANDOM_EFFECT_REMOVED for one component and RANDOM_EFFECTS_REMOVED for two or more.
- **Results** (`fixedEffects.<term>`):
  - fTest: a Type III Wald F, b′(LCL′)⁻¹b/q.
  - `randomEffects` {sd, variance} per component, plus residual.
  - `matchingTest`: the REML likelihood ratio against the fixed-effects-only model, with df = number of random effects kept. It is {status: INVALID} when all were removed.
  - `differenceBetweenCol/RowMeans` from the least-squares means, with the t CI at the term's df. Its CI level is labelled with α.
  - `means` are least-squares means: cells are predictions, rows and columns are averages of cells.
  - `dataSummary` {colCount, rowCount, matchedCount, missingCount}; for one-way, {levelCount, matchedCount, missingCount}.
- **Denominator df (legacy error strata):**
  - Between-subject terms: subjects − groups.
  - Each repeated factor of a both-factors design: (levels − 1)(subjects − 1).
  - The within-subject residual stratum loses one df per missing value: (levels − 1)(subjects − groups) − missing, or (r − 1)(c − 1)(n − 1) − missing.
  - With every random effect removed, all terms use N − cells.
- **Geisser-Greenhouse ε** is computed from a covariance matrix of the repeated levels built from all available pairs, each level centred at the mean of all its values:
  - one-way: divided by (pairs − 1);
  - two-way: cross-products summed over the between-subject groups and divided by the number of pairs (not pairs − 1).

  This was verified on 6 one-way and 5 two-way missing-value patterns. It is applied as in the GLM path (dfNumerator and dfDenominator × ε).
- **Post tests:**
  - **Repeated factor and cells of a both-factors design:** paired t over the subjects with both values. df = pairs − 1, and the sample means and n are over those pairs. A pair with a single subject has status TOO_FEW_POINTS and carries only meansDifference and the samples.
  - **Between-subjects factor, and any factor when sphericity is assumed:** least-squares means and their covariance from the mixed model, with df = that factor's stratum df. The sample means are the LS means and n is the available count.
  - **Simple effects:** within-subject pairs are paired as above. Between-subject pairs use the LS covariance with df = N − cells when the repeated factor has two levels, and otherwise Welch on the available values.
- **Known, not reproduced:**
  - **Two or more random effects removed:** Prism's remaining estimate is not the REML optimum of the reduced model; our −log L is lower.
  - **Dunnett after a one-way mixed fit:** the correlation Prism uses is not found. The closest rule (paired n against the control's n) is exact for 4 of 10 sets; adjusted P values agree to about 3 %.

## Phase 2 batch 11a: table-output analyses, outliers, Bland-Altman
Parameter seeds come from Prism-converted documents in the local corpus. Enum names were found by retention probes (`tools/class_probe.py`): Prism resets unknown values to UNKNOWN or to the first enum value. The rules were verified with `tools/table_parity.py` (6 tables, 65 configurations, **371 field groups agree**, cell by cell at full stored precision) and `tools/outlier_parity.py` (12 tables with planted outliers, 10 configurations, **132 field groups agree**).
- **Result tables:** these analyses store only a status in results.json; the output is the ANALYSIS_VIEW table of the result sheet. `tools/table_oracle.py` reads it. The analysis class of Transform is `TRNSFORM`.
- **NORMALIZE** (per data set, on the row means):
  - **Values:** `calc.value_0.defineAs` is SMALLEST, FIRST or CUSTOM; `value_100.defineAs` is LARGEST, LAST, SUM_OF_VALUES (the sum of the row means) or CUSTOM. Every replicate becomes 100(y − v0)/(v100 − v0); `options.reportResultsAs` FRACTIONS drops the factor 100.
  - **Edge cases:** when FIRST > LAST, Prism swaps the two. A data set whose 0 % and 100 % coincide is copied unchanged. CUSTOM with an undefined value gives blanks.
- **TRNSFORM** (`calc.transformType` STANDARD; SPECIAL and USER_DEFINED_Y also exist):
  - **Y functions:** Y*K, Y+K, Y−K, Y/K, Y^2, Y^K, LOG10, LN, 10^Y, EXP, 1/Y, SQRT, LOGIT, ABS, Y*X, Y/X, Y−X, Y+X, K−Y, K/Y, LOG2, 2^Y, and PROBIT(Y) = Φ⁻¹(Y) + 5 (the classic probit).
  - **X functions:** the analogous set.
  - **Invalid results** (log of a negative, etc.) are blank.
- **REMOVE_BASELINE:**
  - **Expressions:** `calc.expression` DIFFERENCE "A − B", RATIO "A / B", PERCENT "100 * (A / B)", PERCENTAGE_DIFFERENCE "100 * ((A − B) / B)".
  - **Column baseline:** EVERY_OTHER_COLUMN_2_4_6 pairs A with B, C with D; _1_3_5 gives B / A.
  - **Means mode** (`treatSubcolumnsAs` MEANS): mean with a delta-method SE, format y_se. A single value has SE 0.
  - **Replicates mode** (REPLICATES): each replicate against the baseline's mean. Tables without replicates give y_single.
  - **Blank rows:** a row with no result loses its row title.
  - **Row baseline:** FIRST_ROW leaves the first row blank (title and X included); LAST_ROW drops the last row.
- **ROW_STATISTICS:**
  - **Scope:** `data.scope` TABLE takes the mean of each data set's replicates first, then the statistic across data sets. COLUMN works per data set across its replicates; a table without replicates always uses TABLE.
  - **Statistics:** MEAN_WITH_SD / _SEM / _CV / _CI (y_sd_n, y_se_n, y_cv_n, y_high_low), SUM, MEDIAN, MEDIAN_WITH_RANGE / _QUARTILES / _PERCENTILES.
  - **Quirk:** %CV tables store the SD.
  - **Edge cases:** a single value has SD 0 and a blank CI.
- **TRANSPOSE:** each original row becomes a data set titled with its X value, and each data set becomes a row. The new X is the old data-set titles (0 when not numeric).
- **IDENTIFY_OUTLIERS:**
  - **Grubbs:** GRUBBS_SINGLE reports G = max|x − x̄|/s with the critical value from t(α/2n, n − 2). GRUBBS_MULTIPLE ("Iterative Grubbs") repeats the test.
  - **ROUT** (`calc.q` in %) matches Prism in 160 of 160 parity columns with this rule:
    - RSDR = the 68.27th percentile of |residual| × n/(n − 1);
    - the centre is a Lorentzian fit with the scale fixed at the RSDR around the median;
    - each point gets a two-sided t P value with df n − 1;
    - Benjamini-Hochberg at Q flags the k largest residuals, where k is the largest rank with P(k) ≤ kQ/n.
  - **Results:** summary {method, alpha|q, totalOutlierCount} and per sample {grubbsG (single only), pointCount, outlierCount}.
  - **Tables:** "Cleaned data" blanks the outliers in place. "Outliers" has one row per outlier, titled "#row", with the value in its own column.
- **BLAND_ALTMAN:**
  - **Types:** `calc.type` A_MINUS_B, B_MINUS_A, A_DIV_B or B_DIV_A (batch 11g). A ratio type reports the mean and SD of the ratios, with the same ±1.96·sd limits, in a table "Ratio vs. average" (data set "Ratio"). No percent-difference type exists: about 40 candidate names were reset to UNKNOWN, which yields the mean of the averages.
  - **Results:** bias, sd, and limits of agreement bias ± **1.96**·sd.
  - **Table:** "Difference vs. average" keeps the rows aligned, blank where a value is missing.
- **Known, not reproduced:** iterative Grubbs on one n = 5 column. The single test flags a value (G 1.784 > 1.715) but the iterative test flags none.

## Phase 2 batch 11b: simple logistic regression (SIMPLE_LOGISTIC_REGRESSION)
Verified with `tools/logistic_parity.py`: 10 XY tables with 0/1 outcomes (n 15–80, two of them completely separated, some with missing Y) at 95 % and 90 %. **114 field groups agree**; the ROC area's SE and CI are not compared.
- **Fit:** maximum likelihood.
  - **Coefficient CIs** (β0, β1) are profile likelihood: where log L drops by χ²(level; 1)/2.
  - **X at 50 %** ("X when Y=50%") = −β0/β1, with a delta-method SE and a profile-likelihood CI (reparametrised β0 = −x50·β1).
  - **Odds ratios** = exp(β), with exp(profile CI).
- **Tests and goodness of fit:**
  - The significance test of β1 and the likelihoodRatioTest are both G² = 2(ℓ − ℓ0) against χ²(1).
  - goodnessOfFit: r2TJ (Tjur), r2CS = 1 − exp(−G²/n), deviance = −2ℓ.
  - P-value levels are 1 − confidenceLevel/100.
- **ROC area** of the fitted probabilities:
  - area = Mann-Whitney; CI = area ± z·SE, clipped at 1.
  - P is the Mann-Whitney normal approximation **without** tie correction or continuity correction.
  - **Not found:** the SE formula. DeLong comes within about 0.3 %, Hanley-McNeil does not.
- **Data summary and separation:**
  - dataSummary.rowsTotal counts only rows that have an outcome.
  - With complete separation, Prism reports warning NOT_CONVERGED and model status INTERRUPTED, with every estimate "undefined" and status INVALID for the tests and the ROC.
- **Reader fix:** an empty data table can have no `content.json` in a Prism-saved document; `prism_reader` now reads it as an empty table.

## Phase 2 batch 11c: multifactor ANOVA and multiple-variables tables
- **Writing multiple-variables tables:** `bundle_builder` can now write `multivariable` tables. Each variable is a `VariableDataSet` with `currentType` continuous or categorical. Categorical variables list their categories {id, firstRowIndex, usageCount, name} in order of first appearance, with levelsOrder "entry". The table storage version is 1, the sheet carries flag HIDE_ROW_TITLES, and data.csv holds the category text.
- **Data-set references:** `analysis_writer` now completes every {"col": {"idx": i}} in the parameters with the data set's title and uid (variable references in multivariable analyses).
- **MULTI_FACTOR_ANOVA:**
  - **Model:** `model.response`, `model.predictor.variables` (effectType FIXED) and `definition`. The definition lists the terms as lists of {varIdx}; an empty list is the intercept.
  - **Results:**
    - `parameters`: coefficients of the effect-coded model, levels in order of first appearance;
    - `ordinaryModel.anovaTable.fixedEffects[]`: {name "A : B", ss, df, ms, variation = SS/SST, partialEta2, CohenF = √(η²p/(1 − η²p)), fTest};
    - residuals, total, and dataSummary.pointCount.
  - **Verification:** Type III SS (`refract.stats.nway`) reproduces all 62 fields of a Prism-computed two-factor document.
- **Automation limit:** Prism 11.1 does **not compute MULTI_FACTOR_ANOVA under script automation**, even for its own document once the results are cleared. It also fails when the result sheets are revisited many times, when a second page is shown, and when the document is left open for several seconds between two scripts. Cox regression in a Prism-made document does compute. So larger multifactor designs cannot use Prism as an oracle; they rely on the general linear model. A Prism-made three-factor sample would confirm them.

## Phase 2 batch 11d: Cox proportional-hazards regression (MULTIPLE_COX_REGRESSION)
Verified with `tools/cox_parity.py`: 10 generated multiple-variables tables (n 30–120, 1–3 covariates, categorical with 2–3 levels or continuous, integer times with tied events), profile-likelihood and Wald CIs, every diagnostic switched on. **330 field groups agree** to 1e-6. Prism computes this class under automation on our generated tables.
- **Model:** Efron ties (`tiesMethod` EFRON) and Newton-Raphson on the partial likelihood. Each categorical covariate becomes indicators against its reference level; AUTO_FIRST_LEVEL is the first level in entry order. Parameters are named β1…, with variableName "Var[level]" or "Var".
- **Per-coefficient output:**
  - **SE and CI:** se is "undefined" with PROFILE_LIKELIHOOD (the CI is where log PL drops by χ²(level; 1)/2). With WALD the CI is b ± z·se.
  - **significanceTest:** |z| with a two-sided normal P under Wald; the likelihood ratio for dropping the term, against χ²(1), under profile likelihood.
  - **hazardRatios:** exp(b), se_HR = HR·se, CI = exp(CI).
- **Model-level output:**
  - **covariance** is the correlation matrix.
  - **multcollinearity:** r2 is from regressing each regressor on the others **without an intercept** (uncentred); vif = 1/(1 − r2). One covariate gives r2 0 and vif 1.
  - **modelDiagnostics** (null, selected):
    - parameterCount: n − 1 for the null model, n − p for the selected model;
    - aic: −2ℓ0, and −2ℓ + 2p;
    - logLikelihood is reported as **−ℓ**;
    - neg2logLikelihood;
    - pseudoR2 is Cox-Snell, 1 − exp(−LR/n).
  - **hypothesisTests:** likelihoodRatioTest, waldTest (b′Ib) and scoreTest, each against χ²(p).
  - **concordanceProbability.harrellC:** an event is comparable with every later time and with censored observations at the same time; tied risks count ½.
- **dataSummary:** tiesCount counts the events that share their time with another event.
- **Known, not reproduced:** the CI of Harrell's C. Its half-width is 1.5–5 % below the jackknife's, and its level is labelled 1.0.

## Phase 2 batch 11e: ROC, area under the curve, nested t test and nested one-way ANOVA
Parameter names and result layouts come from a Prism-made sample (`corpus/manual/batch3_samples.prism`), whose results are reproduced exactly. Rules were then checked on generated data: `tools/roc_parity.py` (8 ROC tables, 5 configurations; 6 XY tables, 6 AUC configurations) gives **423 field groups** agreeing, and `tools/nested_parity.py` (12 nested tables) gives **148**.
- **ROC area SE (also used by simple logistic regression):** Hanley & McNeil (1982) with Q1 and Q2 taken from the data and ties broken at random. Q1 is the mean over controls of g² + g·e + e²/3, where g and e are the fractions of patients above, and tied with, that control; Q2 is the same over patients. This replaces the DeLong approximation, and the logistic-regression parity now compares the ROC SE and CI as well (120 field groups).
- **ROC_CURVE:**
  - **Data:** `data.controlID` and `patientID` name the two columns.
  - **Options:** `options.confidenceMethod` WILSON_BROWN, WILSON or CLOPPER_PEARSON; `reportResultsAs` PERCENTAGE or FRACTION.
  - **Area:** with the CI clipped at 1. P uses the null SE √((n1 + n0 + 1)/(12·n1·n0)).
  - **Thresholds:** the smallest value (counted as lying just below it), then the midpoints of consecutive distinct values, then a value just above the largest. Sensitivity is the fraction of patients above the threshold; specificity is the fraction of controls below it. likelihoodRatio is "undefined" at specificity 1.
  - **dataSummary:** counts, and missing = blanks above the last value.
- **Wilson/Brown correction:** the Poisson end correction applies for x ≤ 2 below n = 50 and for x ≤ 3 from n = 50 (seen at n = 45 vs 50 and 55). This also changes the contingency proportions, whose parity still passes.
- **AREA_UNDER_CURVE:**
  - **Baseline:** a value, or the mean of the first/last rows.
  - **Segments:** the curve is split where it crosses the baseline (linear interpolation) and each segment is integrated by trapezoids. totalArea sums |area| over every segment.
  - **Peaks:** segments whose height reaches minimumAmplitudePercentage of the Y range; positive only unless `calcPositivePeaksOnly` is false. A peak reports firstX/lastX (the crossings), peakX/peakY (the largest |y − baseline|), area and areaPercentage of totalPeakArea. With negative peaks the summary adds positivePeakArea, negativePeakArea and netArea.
  - **Column tables:** row numbers are used as X (warning ROW_NUMBERS_AS_X).
- **NESTED_T_TEST / ONE_WAY_NESTED_ANOVA:**
  - **Model:** REML with a random nested factor (the subcolumns of each data set).
  - **Degrees of freedom:** df = subcolumns − groups.
  - **Nested t test:** t and F; differenceOfMeans is the second minus the first under `swapDirection` (the default); goodnessOfFit has df = n − p − 2 and remlCriterion = −log L_REML including the 2π term.
  - **Both:** nestingTest is the REML likelihood ratio (df 1); dataSummary {treatmentCount, matchedCount, pointCount}.
  - **Writer:** `bundle_builder` now writes nested tables (a SubColumnTitlesDataSet; flags DATASETS_USES_OWN_TITLES, HIDE_ROW_TITLES).
- **REML precision:** the profiled criterion is flat at its optimum, so minimising it alone stopped at about √eps. `mixed.Reml` now also solves the analytic gradient for zero. The nested results then agree with Prism to 1e-13, and the mixed-model parity improves to 1407 field groups at 1e-6.

## Phase 2 batch 11f: multiple linear and logistic regression, PCA, multifactor post tests
Parameter names and result layouts come from the Prism-made sample (`corpus/manual/batch3_samples.prism`), whose results are reproduced exactly, apart from the items listed as known below. Prism computes all three analyses under script automation (unlike MULTI_FACTOR_ANOVA). `tools/multreg_parity.py` (4 linear and 4 logistic tables with numeric and categorical predictors, 4 PCA tables; 2 + 2 + 6 configurations) gives **878 field groups** agreeing to 1e-6.
- **MULTIPLE_LINEAR_REGRESSION** (`refract.stats.multiple_regression.multiple_linear`):
  - **Fit and coefficients:** least squares. Coefficient CIs use t; se is "undefined" under PROFILE_LIKELIHOOD. Significance tests use |t|.
  - **Partial F tests:** one per model component (a categorical spans several regressors).
  - **VIF:** centred when the model has an intercept (β0 "undefined").
  - **Goodness of fit:** rmse = √(SS/(n − 1)); AICc counts K = p + 1. The normality tests are run on the residuals.
  - **Warning:** with `interpolation.fromData`, the warning INTERPOLATION_UNDEFINED_VARIABLE is raised when no row has a blank Y and complete predictors.
- **MULTIPLE_LOGISTIC_REGRESSION** (`multiple_logistic`):
  - **Outcome coding:** the outcome is coded by `model.outcome0/outcome1`, even when the outcome variable's auto reference level (first in the data) differs. Categorical predictors do take their first level in the data as the reference.
  - **Coefficients:** profile-likelihood or Wald CIs, and odds ratios.
  - **modelDiagnostics:** df n − 1 / n − p; AICc with K = 1 / p; logLikelihood reported as −ℓ.
  - **Pseudo-R² values:** Tjur, McFadden 1 − ℓ/ℓ0, Cox-Snell, and Nagelkerke (CS / (1 − exp(2ℓ0/n))).
  - **Classification and ROC:** a classification table at the cutoff, and the ROC area with the Hanley-McNeil SE.
  - **Hosmer-Lemeshow:** the groups are bounded by the **Weibull** ((n + 1)p) deciles of the fitted probabilities, with group i holding q_i < p ≤ q_(i+1), and df = groups − 2. Only this quantile rule fits both the tied sample (Titanic) and the 4 untied runs.
- **PCA** (`refract.stats.pca`):
  - **Data and decomposition:** `calc.transform` is STANDARDIZE_DATA (correlation matrix, n − 1 SD) or CENTER_DATA (covariance matrix).
    - Eigenvalues come with explainedVariance and its cumulative value (%).
    - Loadings = eigenvector·√eigenvalue; scores = transformed data × eigenvectors.
    - Result tables: "Loadings" and "PC scores", with the selected components only.
  - **`calc.method` values and their dataSummary.method labels:**

    | Method | Label | Components kept |
    | --- | --- | --- |
    | PARALLEL_ANALYSIS | "Parallel analysis" | |
    | KAISER_RULE | "Eigenvalue > 1 (Kaiser)" | eigenvalue > 1 |
    | EIGENVALUE_ABOVE_THRESHOLD | "Eigenvalue > {t} (Manual)" | eigenvalue > `eigenvalueThreshold` |
    | SPECIFIC_NUMBER | "Largest {n} eigenvalues" | `componentCount` |
    | TOTAL_EXPLAINED_VARIANCE | "{v} total explained variance" | the smallest count reaching `explainedVariance` % |
    | ALL_COMPONENTS | "Select all" | all |

    - An unknown value is stored as UNKNOWN, labelled "", and keeps all components.
    - The {t}/{v} placeholders hold only the **first character** of the number: 0.9 → "0", 75 → "7", 80 → "8".
  - **Orientation:** the signs of eigenvectors are arbitrary.
    - PC1's sign equals that of the LAPACK SVD of the transformed data in every case checked (9/9), so Refract orients by that SVD.
    - **Known, not reproduced:** the signs of PC2 onwards. No rule matched, including:
      - first, maximal-|·| or summed loading;
      - first, last or largest score;
      - LAPACK eigh drivers (ev/evd/evr/evx);
      - JAMA tred2/tql2;
      - Numerical Recipes Jacobi;
      - NIPALS start columns.
    - Parity compares their tables by absolute value.
  - **Known, not reproduced:** parallel analysis uses Prism's own random simulations (seeded by `parallelAnalysis.randomSeed`), so parallelAnalysisValue and the count it selects differ.
- **MULTI_FACTOR_ANOVA post tests** (`refract.stats.nway.post_tests`): `postTests.pairwiseTests.design` CONTROL_VS_ALL against one factor's control level.
  - **Estimates:** least-squares means (the average of cell predictions over the other factors). SEs come from MS_res·(X′X)⁻¹, with residual df.
  - **Dunnett P:** floored at 1e-15 (state P_VALUE_LESS).
  - **Sample means:** sample1/sample2 report raw means and n. Tests are keyed by uuid and identify levels by {response, factorList}.
  - **Result:** every value in the three-factor sample is reproduced, except that the Dunnett CI limits carry the known critical-value difference.

## Phase 2 batch 11g: Bland-Altman ratios, nonlinear ROUT and robust fitting
- **BLAND_ALTMAN:** A_DIV_B and B_DIV_A were found by retention probes; see batch 11a. `tools/outlier_parity.py` now gives **152 field groups** agreeing.
- **NONLINEAR_REGRESSION enum values** (retention probes):
  - **`method.outliers.method`:** DO_NOT_HANDLE or ELIMINATE. About 30 other names were reset to UNKNOWN.
  - **`method.fittingMethod`:** LS, ROBUST, or POISSON (error INVALID_DATA_POISSON on non-count data).
  - **`modelComparison.type`:** NO_COMPARISON or SHARED_PARAMETERS. SHARED_PARAMETERS alone gives an empty modelComparison: the parameters to compare, the second equation and the sharing settings sit in a structure that could not be guessed, so model comparison and global (shared) fits wait for a Prism-made sample.
- **RSDR** (robust SD of the residuals): the **exact** 68.2689th percentile (Φ(1) − Φ(−1)) of |residual|, with linear interpolation, × n/(n − K). It matches Prism's reported rsdr to 1e-15; 68.27 is off by up to 1e-4.
- **Robust fit (ROBUST):**
  - **Fit:** the Lorentzian fit, minimising Σ log(1 + (r/s)²), with the scale s equal to the RSDR of its **own** residuals. We iterate it to a fixed point from the least-squares fit. Fixing s at the least-squares RSDR misses Prism by up to 40 %.
  - **Results:** estimates only (transforms included), no SE, CI or covariance. goodnessOfFit is {ss = the Lorentzian merit at that s, rsdr, aicc "undefined"}.
- **ROUT elimination (ELIMINATE, `outliers.q` in %):**
  - **Rule:** the robust fit above, then for each point P = 2·t_sf(|r|/RSDR, n − K). Benjamini-Hochberg at Q flags the k largest residuals.
  - **Refit:** the ordinary fit of the remaining points.
  - **dataSummary:** still counts every point, and adds outliersCount.
  - **Result entry:** a top-level `outliers` entry per data set {status, q, outliersCount, trueOutliersCount (0 in every case seen), outliersList [{x, y, id: [data set, row, subcolumn]}]}.
- **Parity** (`tools/nl_outlier_parity.py`, the 14 nonlinear curves with 0–2 planted outliers per data set, at Q = 1 %, Q = 10 % and ROBUST):
  - The outlier decisions agree in **40 of 40** data sets. With the fixed-scale robust fit, 39 agreed.
  - 519 field groups agree to 1e-6, and the rest to 1e-3.
  - **Known:** the remainder are Prism's "medium" convergence, in robust fits (≈1e-4) and 4-parameter curves (as in batch 9).

## Phase 2 batch 11h: nonlinear model comparison and global fits (shared parameters)
The parameter layout comes from a Prism-made sample (`corpus/manual/batch4_samples.prism`): five analyses of two dose-response curves. Every modelComparison field is reproduced exactly. The rules were then checked on generated tables with `tools/nl_compare_parity.py` (8 generated tables of 2–3 curves × 7 configurations: two equations by F test and by AICc, a hypothetical HillSlope, one and two shared parameters, and two global fits): **1511 field groups agree to 1e-6**, and 237 more to 1e-3 (convergence, below).
- **Parameters:**
  - `modelComparison.type` is TWO_MODLES (sic: two equations), CONSTRAINED_PARAMETER (a parameter at a hypothetical value) or SHARED_PARAMETERS (does a parameter differ between data sets).
  - `method` is STAT_TEST (extra sum-of-squares F test) or AIC_TEST (AICc), plus `alpha`.
  - `modelComparison.options` names what is compared: {parameterName, hypoteticalValue (sic)} for CONSTRAINED_PARAMETER, and {sharedParameters: [...]} for SHARED_PARAMETERS. Prism builds the model titles from it. Without it, the fits are still computed but titled " = 0" or "0 parameters …".
  - The alternative model is `modelComparison.modelToCompare` = {equation, constraints, initialValues}. A hypothetical value is a CONST constraint there; "same for all data sets" is a **SHARE** constraint (`{"type": "SHARE", "value": "undefined"}`).
  - A global fit without a comparison is a SHARE constraint in `model.constraints`.
- **Models:** "Model 1" is the main fit and "Model 2" is modelToCompare. Each is fitted per data set (result id {col, model}), or as one global model (id {model} only) when it has a SHARE constraint. `modelDescription` is the model's title:
  - two equations: the equation names, or "Equation 1"/"Equation 2" when the names are equal;
  - CONSTRAINED_PARAMETER: "<P> unconstrained" / "<P> = <value>";
  - SHARED_PARAMETERS: "<P> different for at least one data set" / "<P> same for all data sets". With more than one parameter <P> is "N parameters".
- **Global model:**
  - **Fit:** one least-squares fit of all data sets with one copy of each shared parameter.
  - **Parameter entries:** hash layers keyed by data set ({} for a shared parameter), each with dsList. A transform is shared when every parameter it uses is shared.
  - **Covariance:** per data set, the correlation matrix of that data set's parameters, shared ones included.
  - **goodnessOfFit:**
    - df = all points − free parameters;
    - r2 = 1 − SS/SST about the grand mean, and per data set 1 − SS_i/SST_i;
    - ss: total and per data set;
    - adjR2 = 1 − (1 − r2)(n − 1)/df; syx = √(SS/df); rmse = √(SS/(n − 1));
    - aicc with n = all points and K = free parameters + 1.
- **Comparison** (`modelComparison`): one entry per data set when both models are per data set, otherwise one global entry (ids without col), in which a per-data-set model contributes the sums of its SS and df.
  - **F test:** the simple model is the one with more df. F = ((SS_s − SS_c)/(df_s − df_c))/(SS_c/df_c). The complex model is preferred when P < alpha. Equal df gives status MODELS_EQUAL_DF, f and P "undefined", dfNumerator 0, and Model 1 preferred.
  - **AICc:** aicDifference = AICc(simple) − AICc(complex); probability(simple) = 1/(1 + e^(Δ/2)). probabilitiesRatio is the larger probability over the smaller, and the preferred model is the more probable one.
- **Profile-likelihood limits:** a limit with no crossing within **6 SE** is "undefined". The sample has undefined limits at 9.6 and 92 SE, and the earlier parity has defined ones up to 4.3 SE. Profile refits are warm-started and use a 1e-12 tolerance, which brings a 3-curve global profile down from minutes to seconds.
- **Starts:** a single start can stop in a worse local minimum (one table: SS 3418 against Prism's 2760). The global fit therefore also starts from each data set's own estimates and from their mean for the shared parameters, and keeps the lowest SS.
- **UNSTABLE:** a parameter whose Jacobian column has vanished (a Hill slope run off to a step) has status UNSTABLE, se and CI "undefined", and is left out of the covariance, as Prism reports it.
- **Known:**
  - **Convergence:** in 4-parameter and weakly determined global fits, Prism stops at its medium convergence criterion, so estimates differ by up to ~1e-3 while our SS is lower or equal.
  - **Run-off parameter:** where a parameter runs off, Prism stops at its own iteration (a Hill slope of 1524; we reach 5e6), so the other SEs of that fit differ.
  - **Profile edge cases:**
    - the sign-symmetric Hill slope (Prism takes the far crossing, as in batch 9);
    - a lower limit at a data X where another curve's held profile becomes a step (Prism: undefined).

## Phase 3 batch 1: automatic axis range (linear)
Method: `tools/autoscale_probe.py` replaces the numbers of a seed graph's table with generated values (scales 1e-3–1e6; positive, negative, mixed, tight), lets Prism re-save every variant, and reads back what it drew (PCFF `0x8025` min/max/tick) plus its extent cache (`0x0017`).
- **Bar graphs** (grouped bars with mean ± SD, a grouped-bar seed): **30 of 30** reproduced by `refract.render.autoscale.auto_range`.
  1. The extent is that of everything plotted, here mean ± SD; it equals the `0x0017` cache.
  2. The top is raised by 5 % of the data span (max − min, before 0 is added) when it is above 0. The bottom gets no head-room: all-negative data end exactly at 0 and mixed data at the tick below min.
  3. 0 is then added to the range.
  4. The major tick is the smallest 1-2-5 value ≥ range/5.
  5. The ends are rounded outwards to whole ticks.

  Example: extent 68.6..146.21 → top 150.09 → 0..150.09 → tick 50 → 0..200. A two-pass guess (fit the data, then add 0) gets 29/30, and head-room on the span including 0 gets fewer.
- **XY graphs, both axes** (E-xyscale, revised 2026-11-14): **278 of 278**
  axes reproduced with style "xy" - the 40 dose-response variants (Y; their X
  never varied) and 100 variants of a Refract XY graph with random X and Y
  (`corpus/auto/as_xyx`, `as_xyx2`; the rule was fitted on 60 and checked
  on the other 40).
  - **Zero rule:** the axis starts at 0 when the data are on one side of 0 and
    min/max < 0.53 (observed 0.518 -> from 0, 0.540 -> not). Negative Y data
    the same (|max|/|min|: 0.525 -> to 0, 0.578 -> not). Negative X data
    only below about 0.27 (0.217 -> to 0, 0.327 -> not).
  - **Margins:** 5 % of the span on each free end, the span measured after 0
    is added (3.18e3..7.63e3 -> 0..1e4; this also explains dose variant v019,
    9.50..48.46 -> 0..60, which the earlier 3 % / 4 % data-span margins
    missed). Data that cross 0: each end moves out by 5 % of its own distance
    from 0 (-9.4..35.1 -> -10..40 and -489..477 -> -1000..1000 rule out any
    constant fraction of the span).
  - **Ticks and rounding:** as for bars.
  - The variants fix the top margin at 5.0 %, the bottom at 4.9-5.3 %, the
    positive ratio at 0.52-0.54 and the negative Y ratio at 0.53-0.57.
- **Column scatter graphs** (E-colscale, 40 variants of a Prism-saved default
  column graph): **40 of 40** reproduced with style "column".
  - **Margins:** 5.05 % of the data span at the top and 4 % at the bottom. Data
    that cross 0 get no bottom margin.
  - **Zero rule:** the axis starts at 0 when min/max < 0.56 (observed 0.516 → from
    0, 0.573 → not).
  - The variants allow a top margin of 4.2–5.1 %. Refract's sample (3.8..7.8,
    drawn 0..10 by Prism) needs more than 5 %.
- **Corpus caches:** the corpus caches are unreliable as evidence. "0..100" and "0..0" extents are stale `0x0017` values. The earlier fit (236/297) was partly tuned to them.
- **verified: Prism refreshes a graph's PCFF caches only when the graph is displayed.** This covers the `0x0017` extent and the drawn range and tick in `0x8025`. A re-save that never shows the graph keeps the old values while exports show the new data: the first dose-response probe re-saved 40 variants with the seed's axes. `tools/prism_auto.py` now visits every graph (`GoTo G i`) before saving. Graphs in real documents that were not displayed before their last save carry stale caches, which explains the corpus outliers.

## Phase 3 batch 2: Prism 11's default graph style (renderer)
Measured on the vector PDFs Prism exported from the default graphs in `corpus/manual/batch5_samples.prism` (XY, column, grouped and survival tables made from Prism's sample data). The tool was pdfium's page objects, i.e. stroke widths, bounds, fonts and per-character origins. `refract.render` (model, build, qt, style) reproduces the XY, column and grouped graphs. Measured PDF against PDF (pdfium, 300 dpi, top-left aligned), SSIM is **0.983 (XY), 0.930 (column) and 0.975 (grouped)** (`tests/test_render.py`). The remaining differences are sub-point (≤ 0.3 pt) offsets.
- **Page:** the PDF page is the content bounding box with a margin of about 5.2 pt, rounded to whole points. Prism's PNG export is 1.2 pt larger than its PDF in both directions.
  - **Left edge:** the leftmost element sets it: the Y-title line box, which is reserved even when the title is empty, or the graph title when it is wider than the plot.
- **Axes:**
  - **Lengths:** X is 215.87 pt for XY (3 in, about 0.12 pt short) and Y is 143.91 pt (2 in) in every family.
    - Grouped: X is 143.89 pt; bar pitch p = L/(groups·k + (groups − 1)·2/3 + 2·1/6), with gaps of 2/3 p between groups and 1/6 p at both ends.
    - Column: 28.73 pt per column; L = slot·(n + 1/3), with the first and last columns 2/3 slot in from the ends.
  - **Lines and ticks:** 1.44 pt black, butt caps. Ticks are outward, 5.4 pt long, starting at the axis line's far edge. The X axis starts at the Y axis.
- **Text:** Arial.
  - **Sizes:** tick labels bold 11 pt, axis titles bold 12, graph title bold 14, legend regular 12.
  - **Tracking:** titles, axis titles and legend are set **0.2 pt tighter per character** at any size, with kerning. Tick and category labels have no tracking (6.114 pt per 11 pt digit). Qt ignores `setLetterSpacing` in its PDF and raster engines, so tracked text is set character by character.
  - **Category labels:** rotated 45°, with the end of the baseline 2.6 pt right of the tick and 10.1 pt below its end.
- **Positions:**
  - Y tick labels end 3.1 pt before the tick and are centred on it by cap height. X tick labels' line box starts 3 pt below the tick.
  - The X title line box is 4 pt below the labels. The Y title line box is 5.5 pt left of the labels.
  - The title is centred on the X axis, its line box 9.2 pt above the Y axis.
  - Legend: symbol centre 40.5 pt right of the X axis end, text 16.3 pt further right; first baseline 14 pt below the Y axis top, rows every 20.15 pt.
  - Fonts must be measured against a 72-dpi device: Qt's offscreen screen is 96 dpi.
- **Data (defaults):**
  - **XY:** mean ± SD. Symbols: filled circle 6.32 pt and filled square 5.75 pt (Control, Treated), all black. Error bars 0.72 pt with 5.76 pt caps, drawn before the symbols.
  - **Column:** scatter of every value (filled circles 4.73 pt) with a **median** line (1.44 pt, 2/3 slot wide), no error bar. Autoscaled like bars (0..10 for 2.3..7.8).
  - **Grouped:**
    - Bars (mean) have a 2.16 pt black border. The rectangle is inset by half the border at the value end, so the border's outer edge sits at the mean.
    - Fills: 50 % black, and (176, 176, 179). Bar width 0.556 of the bar pitch.
    - Mean ± SD error bars are 0.72 pt with caps 0.6 × the bar width. The replicates are drawn as 6.32 pt circles.
    - The legend shows the point symbol.
  - **Point arrangement:** from the top (largest value) down, each point takes the first free slot of 0, +1, −1, +2, … A slot is taken by a placed point closer than one symbol in y. Each cluster of overlapping points is then centred on its slots. This reproduces all 24 points of the two graphs.
    - Slot step: 8.62 pt in the column scatter, 3.35 pt over grouped bars. One sample each; these probably depend on the column and bar widths.
- **Not yet rendered:** survival graphs.
  - Kaplan-Meier staircase, 0.72 pt.
  - Censor ticks: 1.44 pt, 2.88 pt high.
  - Minor ticks every 10 on Y, 2.7 pt long.
  - X axis −23.75..223.75 with ticks every 50 from 0: the axis starts one half-tick before 0.
  - Legend: a line with a censor tick.

## Phase 3 batch 3: survival graphs
Measured on Prism's default survival graph (batch5 sample), with the X axis checked on 30 Prism variants of the survival times (`tools/autoscale_probe.py --only-x --table 3 --graph 3`). `refract.render` reproduces the graph at **SSIM 0.948** against Prism's PDF. What remains is a uniform 0.3–0.4 pt offset.
- **Axes:**
  - **X:** the bar rule from 0 to the last time (5 % head-room, tick = smallest 1-2-5 ≥ range/5), then both ends widened by **0.475 of the major tick** (30 of 30 variants, times 0.04–930 000). Example: 0..150 → −23.75..223.75 / 50. Ticks are the multiples of the major tick within the range, so the axis starts between ticks.
  - **Y (percent):** fixed at 0..110 in all 30 variants. Major ticks every 50 are labelled (0, 50, 100); minor ticks every 10 are 2.7 pt long, up to the axis end at 110.
  - **Titles:** the Y title defaults to "Probability of Survival"; the X title is the table's X title.
- **Curves:**
  - One Kaplan-Meier staircase per data set, in percent, black, 0.72 pt, starting at (0, 100).
  - At each time: a horizontal run, then the drop for its deaths. A time with only censored subjects adds a vertex, and the line ends at the last time.
  - Censored subjects: a vertical tick rising 2.88 pt from the curve, 1.44 pt wide.
  - Legend: a 15.35 pt line with a censor tick, centred where the other legends put their symbols.
- **Layout correction (all families):** the title gap (3.15 pt) runs from the title's line box to the **topmost element**: the Y axis end, or the line box of a tick label centred near it. XY graphs labelled up to the axis end therefore sit 6 pt lower than a survival axis that continues 10 % past its last label.

## Phase 3/5 batch 4: graph styling read from the file
`refract.render.from_prism` builds a graph from its sheet: the bound data sets, Prism's default graph for the table type, then the decoded PCFF settings below. `tools/render_corpus.py` renders every exported graph of `corpus/auto/convert_xml` (converted user documents and Prism's bundled samples) and `corpus/auto/b5`, and compares each with Prism's PDF.
- **Result:** 292 of 366 graphs render. Median SSIM: column 0.63 (94), grouped 0.54 (162), XY 0.58 (34), survival 0.95 (2). The default graphs stay at 0.93–0.98.
- **Not rendered (74):** layouts, parts-of-whole graphs, and graphs of other analysis results.
- **Decoded (verified):**
  - **Axis length:** `0x8025` +30 u32 in **1/600 inch** (main segments X / Y / Y2). Defaults: XY 1800, 3-column 800, grouped 1200; Y 1200. Prism draws axes about 0.06 % short.
  - **Tick / category label font:** `0x8025` main segment +38 u16 size (84 of the 105 graphs whose labels are not 11 pt), +42 style bits (1 = bold: 96 of 96 bold graphs, 0 in 237 of 241 regular; 2 = italic), +44..46 colour as R, G, B. `0x00AD` +33 float repeats the size.
  - **Category label angle:** X `0x8025` +26 byte.
    - 0 → horizontal (107 of 107); 0x40 → 90° (4 of 4).
    - 0x80 → automatic. Prism draws 45° when the widest label exceeds about 0.9 of the category pitch and horizontal otherwise (E-compare: Prism's new graphs of Refract's tables turned at 0.97 and stayed horizontal at 0.86; on 128 corpus graphs with Prism's PDFs a threshold of 0.9-1.2 agrees with 88-94 of them, 0.4 with 83; the rest are unresolved: other rotated text in the PDF, 90° labels). The earlier 0.4 (about 90 % of 96 graphs) was replaced.
  - **Text objects:**
    - In stream order: graph title, X title, Y title, right Y title, then one legend entry per data set. "XTitle", "YTitle" and "Y1Title" are hidden placeholders.
    - Formatting is in `0x002D` runs: u16 run count; per run u16 attribute count, u32 start, then (u16 id, u32 value) pairs.
    - Attributes: 1 = size, 9 = size × 1000, 2 = style bits (1 bold, 2 italic), 4 = colour 0x00BBGGRR, 8 = colour 0xAARRGGBB, 6 = rotation in 0.1° (2700 on the right-axis title), 10 = code page (1252).
    - Each legend entry carries its own colour. No font family is stored for Arial.
  - **Colours:** Prism stores them in **Apple Generic RGB** (gamma 1.8) and exports sRGB. The conversion through the system profiles matches its PDFs to ±1 level; `refract.render.color` uses a fitted gamma-1.8011 + 3×3 model (max error 0.85/255) that needs no profile files. Per data set, `SEDObject_Array[i]/XYPlot_Map` gives fillcolor, symbolcolor, symbolBorderColor, errorcolor and BarBoxBordercolor.
- **Next (largest remaining differences in the corpus):**
  - Per-data-set plot settings: whether individual points are shown, bar border width, error-bar kind and direction, symbol shape and size.
  - Legend position, and swatch versus symbol.
  - Significance brackets and asterisks.
  - Axis offset from the origin.

## Phase 3/5 batch 5: per-data-set plot settings
Ground truth came from Prism's PDFs of 285 corpus graphs: drawn symbols, their size and shape, and bar stroke widths. It was correlated with the bytes of each data set's plot object (`0x8020` type 9, which holds a `0x8028` header and a `0x009c` record).
- **Graph objects:** `0x8020` objects under `0x8018`. The payload is a u16 type (9 = data-set plot; others are frames, texts and legend entries) followed by rectangles, probably positions (legend placement still to decode). Their number matches the property store's `SEDObject_Array`.
- **`0x009c` +133, plot style:**
  - 3: on column tables a scatter of the values (Prism's default column graph); on grouped tables bars with the values (its default grouped graph).
  - 7, 8: the mean as a symbol with error bars, without bars or individual values. The default detector had counted these mean symbols as "points".
  - 1, 2, 4, 5, 9: bars.
  - 0: XY.
- **`0x009c` +66, symbols drawn:** 0 = drawn, 255 = not. Over bars this decides whether the individual values are shown (68/70 and 176/181).
- **`0x009c` +81, symbol size code:** diameter ≈ 1.58 pt × code (3 → 4.73, 4 → 6.32, 5 → 7.9, 6 → 9.5, 7 → 11; 97 % pure).
- **`0x8028` +94, bar border (PROVISIONAL):** 0 = none, codes 8.. → (code − 7) × 0.72 pt. The default 10 → 2.16 pt. The PDF ground truth for thin borders is noisy (error-bar strokes).
- **Text roles by reference (verified on 4 graphs whose stream order differs):** `0x0013` +32 holds the graph-title text id, and each `0x0017` axis chunk +48 holds its axis-title text id (`0x802B` +0 = text object id). Legend entries are matched to data-set titles.
- **Corpus effect:** median SSIM grouped 0.540 → 0.557 (97 graphs better, 5 slightly worse), XY 0.582 → 0.587, column 0.625 → 0.622.
- **Not decoded yet:** connecting lines between means, error-bar kind (SD / SEM / CI) and direction, symbol shape (+66 is not the shape), legend position, axis offset from the origin.

## Phase 3/5 batch 6: error bars
Ground truth: Prism's PDF error-bar lengths. They were compared with SD, SEM and the 95 % CI of the data, drawn both ways or one way, at the graph's own stored Y scale (`0x8025` range and length). That labelled 43 of 59 replicate column/grouped graphs confidently.
- **`0x8028` (plot header):**
  - **+12, type:** 1 = SD (27 of 28), 2 = SEM. With n = 4, 2·SEM equals SD, so "SEM both ways" and "SD one way" look identical: the three conflicting graphs are such cases. 3 = CI and 0 are provisional (few, low-confidence labels).
  - **+8, direction:** 2 = both ways, 0 = away from the baseline only.
  - **+10 = 0:** no error bars (provisional).
  - Prism's default grouped graph has SD both ways (+12 = 1, +8 = 2).
- **Builder:** the 95 % CI uses t(0.975, n − 1)·SD/√n.
- **Renderer:** each error bar is now one path, the bar plus its caps, as Prism writes it.
- **Check:** the share of Prism's error bars that ours reproduce in length (±3 %), median over 59 graphs, rose from 0 % to 50 %, and 14 graphs now match completely. The rest are mostly graphs whose axis scale still differs.

## Phase 3/5 batch 7: object placement, hidden titles, cached ranges
- **Plot rectangle:** `0x0013` +0..+6 holds four i16 (x0, y0, x1, y1) in 1/600 inch, page coordinates, y down. Prism's default XY graph gives (1650, 2700, 3450, 3900): 3 × 2 in.
- **Graph objects:** every `0x8020` object has an i16 type at +0 and its box (x0, y0, x1, y1) at +2, in the same units. Types: 2 text, 8 axis, 9 data-set plot, 10 frame, 12 legend entry, 3 bracket line.
  - Text and legend boxes are the text's line box padded by about 7.5 pt.
  - In a legend entry, the symbol centre is 17.66 pt from the box's left edge.
  - Placed relative to the plot's top-right corner, these reproduce Prism's default legend to 0.05 pt.
  - A graph without legend objects has no legend.
- **Hidden text objects:** byte +28 of the object header has bit 0x02 for hidden titles ("32 03" against "30 01"). This also hides titles stored in other code pages (e.g. GBK).
- **Cached axis ranges:** for display, the stored `0x8025` range and tick are what Prism drew last (when the graph was shown before saving), so `from_prism.graph(use_cached=True)` uses them. `use_cached=False` recomputes them with the autoscale rules.
- **Layout:** without a title no title line box is reserved; the page starts at the topmost element.
- **Builder:** a grouped table with a single row is drawn with each data set as its own labelled category, as Prism shows it.
- **Corpus effect:** median SSIM grouped 0.558 → 0.688, XY 0.587 → 0.735, column 0.624 → 0.684.

## Phase 3/5 batch 8: annotations, file-placed titles, shapes, connecting lines
Ground truth: Prism's PDFs of the 292 renderable corpus graphs (text positions, axis lines, symbol paths matched to data sets by colour, line segments).
- **Brackets (`0x8020` type 3):** two `0x00d9` children hold the leg ends (u32 x at +4, u32 y at +8, 1/600 in, page coordinates); the bar runs 36 units below the box top; `0x0023` gives the line (+0 width code, coded like the bar border; +4 R G B). Verified on 3 brackets.
- **Free texts:** `0x8020` type 2 objects that are no title; the line box top is the box top + 62.5 units, centred on the box.
- **Text boxes and titles:**
  - **Axis titles:** placed from their stored boxes (line box = box − 62.5 units; the Y title's box is the rotated line box). The stored position is right for 42 of 46 X titles and 185 of 205 Y titles; the default rules for only 20 and 55.
  - **Graph title:** the stored height is often stale. Older files keep it 6–9 pt too high; Prism draws it by its own rule, 3.15 pt above the topmost element (127 of 146 titles within 1.5 pt, the stored box 73). So the stored centre x is used, and the stored height only when it is within 1.5 pt of the rule (`TITLE_SNAP`; there it is exact). Titles moved by hand (7 graphs) are missed; no flag separating them was found in the object, its children or `0x0013`.
  - **Empty titles:** placeholder titles (`XTitle`, `YTitle`) reserve their line; deleted (empty text) and hidden titles do not.
- **Layout:** everything (tick labels, titles, legend, annotations) is placed relative to the plot rectangle; the page is the bounding box plus the 5.2 pt margin. The default graphs keep their size, and the column one now matches Prism's height (251 pt).
- **Tick labels:** the zero label keeps the tick's decimals ("0.00"), as on 139 of 169 zero labels with decimal ticks.
- **Plot order:** XY and survival graphs store their plot objects (and `SEDObject_Array` plots) last data set first; grouped and column graphs in order (19 of 19 graphs, matched by legend colours; `0x009c` +313 does not give the order).
- **`0x009c` +34, symbol shape** (mirrored at +109 and `0x8028` +60): 1 square, 2 triangle up, 3 triangle down, 4 diamond, 5 circle; 6–10 the same shapes filled and stroked with the symbol-border colour (0.72 pt); an "open" symbol is that with a transparent fill. 0 = no symbol. From about 1,600 symbols matched by colour. Squares, triangles and diamonds fill a square of side 0.909 × the circle's diameter. Codes above 10 (rare) are not decoded.
- **`0x009c` +8 = 1, connecting line** (mirrored at `0x8028` +64): set on none of the graphs whose PDF has no such line. +145 (mirrored at `0x8028` +92) is its width, coded like the bar border ((code − 7) × 0.72 pt, 27 of 27). The colour is the plot's `PCFF_Plot::connectlinecolor`. Prism writes the line as separate two-point segments. In a column graph the line joins the data sets' means, left to right.
- **`0x8028` +112 bit 0x40:** error bars hidden (14 of 15 graphs without error bars; none of the 115 graphs with them).
- **Corpus effect (rc7 → rc14):** median SSIM column 0.684 → 0.750, grouped 0.688 → 0.752, XY 0.735 → 0.753, survival 0.949 → 0.981; 234 graphs better, 45 worse, mean +0.063.
- **Not decoded yet:** a flag for hand-moved titles, symbol codes above 10, axis offset from the origin.

## Phase 3/5 batch 9: data found through plot ids, pies, parts-of-whole bars
- **Axis offset:** no corpus graph uses offset axes. On 275 of 278 graphs the X axis line starts exactly at the Y axis; the other 3 have a Y axis crossing mid-range. Nothing to decode for now.
- **`0x009c` +313 (i32): the plotted data set's fen id.** It matches the input data sets' `fen` on 300 of 301 graphs. Graphs whose sheet has no `inputDataSets` (27 in the corpus, e.g. one document's family of copied graphs) find their data through it. −3 marks a plot whose data set was deleted; such plots are dropped, together with their entry in the property store's plot list (which runs parallel to the plot objects, deleted ones included). Graphs with only deleted plots (several in the corpus) stay unsupported: Prism draws them as empty axes.
- **Parts-of-whole tables:**
  - Plot style 9 (`0x009c` +133) is a pie. `0x8028` +99 (mirrored at `0x0031` +1) gives the chart type: 0 pie, 1 percentage dot plot (not drawn yet), 3 donut. The one corpus donut has a hole of 0.5 × the radius.
  - Other styles draw bars, with the rows as categories, as on a grouped table.
- **Pie geometry:** the pie fills the plot rectangle (`0x0013`; diameter 143.7 pt in a 144 pt square). The slices run clockwise from 12 o'clock in row order. Their fills are `PCFF_PieSlice::fillcolor` (`PCFF_PieSlice_Array` of the pie plot). Each slice also has a `0x00d7` record: +12 RGB, +20 index, +24 f32 fraction, +28 f32 value, +48/+56 the same as f64.
- **Pie legends:**
  - Entry texts are stored ready-made ("46%  Democratic", "5,820 Neo"), so the label format needn't be decoded.
  - `0x00db` +4 gives the slice an entry stands for.
  - The swatch is a 15.34 × 8.23 pt rectangle centred 17.6 pt into the entry box, its bottom on the text baseline; the text starts 34.4 pt in. Without a swatch the text starts 7.5 pt in. The swatch is hidden when `0x0084` byte 1 has bit 0x02 (PROVISIONAL: one pie).
- **Pie outline (PROVISIONAL):** `0x8028` +96 = 2 outlines the outer edge and the swatches (1.44 pt, `PCFF_PiePlotData::clOuterBorderColor`). 14 of 16 pies agree with the strokes in their PDFs. Slice edges are not stroked.
- **Free texts:** all lines are drawn, each centred, one line spacing apart (the donut's "1023 / Rejected").
- **Not decoded:** a pie slice Prism leaves blank (Pie_chart's "Not sure": its `0x00d7` +4/+8 read 6/0x0a against 10/0x1a; one sample), the percentage dot plot, a donut's hole size beyond the one sample.
- **Corpus effect:** 292 → 340 graphs rendered. Pies have a median SSIM of 0.800 (16 graphs); the other families are unchanged (column 0.750, grouped 0.750, XY 0.753, survival 0.981). The 26 still unsupported are 21 graphs of analysis results or with only deleted data, 4 Cox-regression graphs whose blob is no PCFF, and 1 percentage dot plot.

## Excluded values and other row-keyed cell metadata (phase 4 batch 2)
- **Exclusion (verified, experiment E-excl):** Prism stores an excluded value in its data set's replicate as `"cellAttributes": [{"rows": "<r>", "attributes": ["EXCLUDED"]}]`. The probe was a corpus `.pzfx` copy with two values marked `Excluded="1"`, opened and re-saved as `.prism` by Prism through `tools/prism_auto.py`. Both marks came back on the right rows (row 1 of the first data set, row 0 of the second); the CSV shows them with a trailing `*`.
- **Row-keyed fields of a replicate** (from about 1,100 corpus replicates):
  - `cellAttributes`: a list of `{"rows": "a" | "a~b", "attributes": [...]}`. Names seen: SECTION_TITLE, SCI_NOTATION, FLOAT/POSITIVE/NUMERIC, CENSORED, BAD_VALUE, EXCLUDED.
  - `cellAlignments`: a list of `{"rows", "attributes": "left"}`.
  - `cellTextFormats`: a dict from the row (as a string) to the cell's text formatting.
  - Key order: `…, significantDigitsCount, cellAlignments, cellTextFormats, cellAttributes, lastRow, firstRow`.
- **Reader and writer:**
  - The reader keeps all three fields per cell (`DataSet.cell_attributes`, `cell_alignments`, `cell_text_formats`), so inserted or deleted rows can move them.
  - The writer (`refract.formats.cellmeta`) re-encodes a field only when its content changed. Consecutive rows of equal value become one `a~b` run, and a new key goes in Prism's position. A replicate range is split into one range per subcolumn only when its subcolumns come to differ. An unchanged file still saves byte-identically.

## Analyses created and edited outside Prism (phase 4 batch 3)
- **New analyses (verified, experiment E-ui-analyses):** `analysis_writer.add_analysis` with a full parameter set and an empty `results.json` is enough. In a copy of a sample project, 22 analyses were added the way the Analyze dialog adds them (11 classes: descriptive statistics, four two-sample designs, five one-way designs and post tests, two one-sample tests, normality, three two-way designs, multiple t tests, linear regression, Spearman correlation, survival, Fisher and chi-square). Prism 11.1 opened the file, computed all 22 (status VALID) and re-saved them with their parameters unchanged. Its values equal Refract's in 21 analyses. The other one differs only in the Dunnett CI limits (relative difference 7e-5), the known critical-value difference of phase 2.
- **Post-test control:** `controlID.col.idx` is the index among the analysed data sets. `add_analysis` resolves it against those inputs, and `_fill_col_refs` now leaves a reference that is already resolved alone. Before, with a subset of data sets, it was overwritten by the table's data set at that index.
- **Changed parameters (verified):** replacing `parameters.json` `content` (new `parameters.dt` token) and emptying `results.json` makes Prism compute the analysis with the new parameters (ordinary ANOVA changed to Kruskal-Wallis with Dunn; Prism's 75 values equal Refract's).
- **Removing an analysis we added** (no result sheets yet): delete its `analyses/<uid>/` entries, its uid in `document.json` `sheets.analyses` and its `sheetAttributesMap` entry.
- **Inputs from tables** (`refract.stats.inputs`; the stored results of the local corpus as the reference, `tools/recompute_corpus.py`):
  - Column analyses take each data set's single subcolumn, without trailing blanks.
  - Survival analyses keep every row (the X column holds the times).
  - Grouped and XY analyses take every replicate subcolumn.
  - Tables entered as mean with SD/SEM/N give the means only.
  - Excluded values are missing.
  - Stored results key entries by uids; comparing them by their `id` (column, row and model indices) pairs them with ours.

## New data tables in an existing bundle (phase 4 batch 5)
- **fenID range of data sheets (verified, experiment E-new-tables):** analysis result tables are data sheets too (`data/sheets/<uid>/sheet.json`, listed in the analysis's `resultSheets`, not in `document.json` `sheets.data`). They share the fenID range with the listed data tables: in the sample project, tables 0–3 and the survival analysis's six result tables 4–9. Six new tables given fenIDs 4–9 were silently dropped by Prism on open; with fenIDs after the largest of *all* data sheets every table opened. Data-set fenIDs likewise continue after the largest in `data/sets/`.
- **Inserting** (`bundle_builder.insert_table`): the entries `table_entries` writes for a new bundle, plus the sheet uid appended to `sheets.data`, its `sheetAttributesMap` title and `uiSettings.nextDataSheetNumber` + 1. Cells typed in the grid are written as typed (`bundle_builder.Num`), not through floats.
- **Verified:** 38 tables (8 kinds, every data format each kind offers, empty and with sample data) in a new project, and 19 inserted into a copy of the sample project, came back from Prism's re-save cell for cell, with their kind, data format, replicate count, data-set and X titles. Analyses of them (linear regression, one-way and two-way ANOVA, contingency, survival) computed in Prism and agree with Refract value for value.
- **Removing** a table we added (`bundle_builder.remove_table`): its sheet, table and data-set entries, its uid in `sheets.data`, its `sheetAttributesMap` entry, and `uiSettings.currentSheets.data` if it pointed at it.

## Structural table edits and Refract's own graphs (phase 4 batch 6)
- **Data sets added, removed, renamed; tables renamed (verified, experiment E-structure):** in a copy of the sample project, a data set appended to the XY table (with values), one inserted first in the grouped table, the middle one of the column table deleted, a data set and a table renamed. Prism re-saved all of it as written (titles, order, cells). The writer (`prism_writer._structure`):
  - Adds a `data/sets/<uid>.json` for each new data set (the entry a new bundle has: `bundle_builder.dataset_json`; fenID after the largest in use).
  - Deletes the entries of removed data sets.
  - Rewrites `sheet.json` (`table.dataSets` in model order, `title`) and the `document.json` `sheetAttributesMap` title.
  - Keeps the stored form of a data set's title (plain string or `{"string", "version"}`).
  - Nested tables are left out: their subcolumn titles are kept per data set.
- **Refract's graphs (verified, experiment E-acceptance):** kept in the private entry `x-refract/graphs.json` as `{"version": 1, "graphs": [{"title", "table": <sheet uid>, "style", "error", "stars", "show_ns"}]}`. Prism 11.1 opened a file holding one, computed its analysis, and re-saved the entry byte for byte with the same table uid. Refract reads it back and links it to the same table. The entry is removed when no graphs remain.

## Prism layouts (phase 4 batch 8)
- **Sheet:** `layouts/<uid>/sheet.json` is a `FENLayoutSheet` with `linkedGraphSheets` (graph sheet uids) and `mediaCollection`; the drawing is a PCFF blob in `data.bin`.
- **Placed graphs (verified against Prism's own PDF exports):** one `0x8020` container per placed object.
  - Its payload is a u16 (11 in every sample) and three rectangles of 4 × i16 (left, top, right, bottom) in 1/600 inch; the first is the object's frame.
  - Child `0x002f` (u16) is the placed graph's fenID.
  - Child `0x0030` (2 × u16) is the graph's own size in 1/600 inch.
  - The graph is drawn at frame ÷ own size with its top-left corner at the frame's. The scale is the same both ways: median difference 1.8 % over 98 corpus objects, with a few outliers. Objects with no `0x002f` are other content (pictures, texts, tables), not decoded.
- **Check (`tools/layout_corpus.py`):** Prism exported the 32 layouts of 27 corpus files (`tools/prism_auto.py` now visits layouts with `GoTo L`). The 26 that hold graphs Refract can draw were drawn at these places and compared after cropping both to their content: median SSIM 0.70 (0.51–0.86). The placement agrees; what differs is the graphs themselves, the same gap as single graphs (phase 5). Prism's PDF export of a layout is cropped to its content.
- **Refract's layouts:** kept in the private entry `x-refract/layouts.json`: `{"version": 1, "layouts": [{"title", "width", "height", "uid", "items": [{"graph": "prism:<sheet uid>" | "refract:<graph uid>", "x", "y", "w", "h"}]}]}` in points. Refract graphs now carry a `uid` in `graphs.json`. Prism 11.1 re-saved both entries byte for byte; every item still resolved afterwards, those naming Prism graphs included.

## Graphs written for Prism: seed and patch (phase 6 batch 1)
- **`0x0014` is the graph's table link (verified):** it lists the sheet fenIDs of the tables a graph plots. This holds for 2098 of 2145 corpus graphs, 154 of which plot several tables. `graph_copy` had set it to "maximum + 1", which happens to be the new table of a DuplicateFamily. A transplanted graph needs the target table's fenID. Otherwise Prism adds every data set of whichever table has that fenID to the graph on open (E-seed, first run).
- **Seeds bound to other tables (verified, E-seed):** Prism's default column, grouped and XY graphs were copied into a Refract-made project with `graph_transplant` and bound to tables with as many, more or fewer data sets than the seed's table (3/2/5 columns, 2/3/1 grouped, 2/4/1 XY). Prism kept all 9.
  - With more data sets, it adds the plots itself, with its own default colours and symbols.
  - Seed plots beyond the table's data sets, bound to the deleted marker (fenID −3, u16 0xFFFD), are dropped.
  - Every graph re-saved with exactly one plot and one input per data set of its table.
- **Survival graphs** plot the survival analysis's result table (their `0x0014` names it), not the data table. Writing one needs the analysis and its result sheets as well; see the next section.
- **Colour store layout:** `SEDObject_Array` holds every graph object (frames, texts, legend entries). The data-set plots are the entries with an `XYPlot_Map`, in data-set order for column and grouped graphs and last data set first for XY (verified on the drawn colours, E-writeback). Colours are written in Generic RGB (`refract.render.color.from_srgb`, the inverse of the fitted model; round trip ±1 level in gamut).
- **Patches verified by Prism's rendering (E-writeback):**
  - Manual Y range 0–50 with tick 10 (`0x00A5` flags `0xC | 0x10000` plus the `0x8025` main segment).
  - Log10 Y (scale 1/1, exponents in `0x8025`).
  - Grouped bar fills.
  - XY symbol colour.
- **Agreement:** Prism's drawing of the written graphs against Refract's own reached SSIM 0.96 (grouped), 0.94 (XY) and 0.71–0.75 (column). The column gap comes from the autoscale of column scatter graphs: Prism 0–10, Refract 0–8 for data 3.8–7.8. That is a renderer rule to revisit (Prism may take the head-room from the span including 0 for column scatters).
- **Patched in place (level A, verified, E-inplace):** graphs of a Prism file formatted in Refract keep everything else byte for byte. Only their `data.bin` is rewritten, always from the blob as opened. Prism renders and re-saves the written range, tick, log10 and colours. `from_prism` now reads log10 axes: `0x8025` +28 set, with the range stored as exponents.

## Survival graphs written for Prism (phase 6 batch 3, E-survival)
- **What a survival graph plots (verified):** the Y data sets of the "Survival proportions" result table of a SURVIVAL analysis. `0x0014` holds that result sheet's fenID and `inputDataSets` its Y data sets. The data table is not referenced.
- **Result tables:** data sheets that document.json does not list. Their sheet flags are `HIDE_ROW_TITLES` and `ANALYSIS_VIEW`. The analysis reaches them through views in `analyses/<uid>/result_sheets/<view>.json` (`AnalysisView`: `dataSheet`, `name`, `viewIdx`, `isVisible`, …), which `sheet.json` lists under `resultSheets`.
- **Kaplan-Meier table layout (batch5 sample, Prism 11.1):**
  - XY table; X holds every distinct time of any group, starting at 0.
  - Each Y data set has values only on the rows of its own subjects' times.
  - Values are percentages (100 on the first row) when `probabilityAs` is PERCENTAGE.
  - Rows where subjects were censored carry the cell attribute `CENSORED`. The ranges are inclusive, "4~5" meaning rows 4 and 5, and the attribute is set even when an event happened at the same time.
- **A partial result is accepted (verified):** an analysis written with only its Survival proportions view and table, filled or empty, is kept by Prism with the same view, sheet and data-set uids. Prism adds the other five views (# at risk, Curve comparison, Data summary, # deaths/events, # censored subjects) and recomputes the values. It computes them to draw the graph too, so a graph opened straight away shows the curves.
- **Survival-only chunks (Prism 10.5+, survival DuplicateFamily diff):**
  - `0x2018`: +4 is the graph fenID.
  - `0x201a`, the number-at-risk cache: the header is u32 header size, 0, graph fen, record count n, group count g, record size. Then come n records, each starting with the group's data-set fen; then g name entries of 24 bytes (fen, 0, string offset, 0, string length, −1); then the names.
  - `0x2019`: +20 follows the graph fen in Prism's copy, but Prism resets it on later saves (it was 3 on graphs with fen 1 and 7), so it is not strictly the fen. It ends with one 20-byte entry per group (fen first) and a closing entry whose fen is −1.
  - All data-set fields here are u32, and a deleted set is written as −3.
  - Copying a survival graph without renumbering the graph fen in these chunks makes Prism refuse to open a file that holds two such copies: it hangs on open.
  - With these fields mapped, our copy of the sample's survival graph matches Prism's DuplicateFamily copy byte for byte in all three chunks.
  - Prism leaves both caches header-only in a graph it has not drawn yet, and fills them when it draws.
- **Colours:** a survival curve's line is `PCFF_Plot::connectlinecolor`, and its censor ticks use the symbol colour. A data set's colour now writes both (verified in Prism's rendering).
- **Legend:** Prism shows no legend on a one-group survival graph made from the six-plot seed, whereas a one-set XY graph keeps its legend (E-seed). Refract now draws survival graphs the same way.

## Pie graphs written for Prism (phase 6, E-pie)

- A pie graph plots one data set, the first of its parts-of-whole table, one slice
  per row. Its sheet's `inputDataSets` names only that set. Prism rebuilds the
  slices and the legend from the table when it draws the graph, including more
  slices than the seed had: extra slices get the next colours of Prism's own
  palette. Blank and zero rows get no slice and no legend entry. Without row
  titles, the legend reads "Legend".
- **0x80d6, the pie's plot data** (one per pie graph, 612 bytes), u16 fields:
  - +4: an id unique in the document. It is renumbered like the other counted
    namespaces (document maximum + 2); Prism's own DuplicateFamily of a pie gives
    the same value.
  - +8: the graph's own fenID (21 of 21 corpus pies).
  - +12: the pie's plot id (21 of 21).
  - +24: a text id, always in the graph's text range (16 of 21 point at an
    existing text object).

  A copy that keeps the seed's values claims the seed's graph. The first such pie
  in the document is then drawn blank: only the seed's cached legend and labels
  show. Another graph with the claimed fenID is drawn with the copy's settings.
  `refract.formats.pcff.idmap` maps all four fields.
- Prism does not rewrite a pie's blob when it re-saves a file. That stays true
  after `SetAxisLimits`, `SetGraphTitle` or `ApplyColorScheme` on the graph. So
  the cached legend texts, the slice fills and labels such as "Total=…" stay as
  written until the pie is edited in Prism. A seed's cached texts therefore
  reach every copy made from it.
- `refract.formats.graph_transplant.is_pie`: a parts-of-whole graph drawn as a
  pie has the 0x80d6 block; one drawn as bars does not.
- Prism 11's default pie (the shipped seed): greyscale fills by row index, nine in
  turn: black, (176,176,179), (147,147,146), (221,220,220), (116,115,115),
  (176,176,179), (116,115,115), (237,237,237), (176,176,179). Rows 7-9 were read
  from Prism's PDF of a 15-row pie. It has a 1.44 pt black outline, no title
  shown, one legend entry per drawn slice, and a bold "Total=<sum>" text below
  the pie. A row's colour follows its row number, also when earlier rows have no
  slice.

## Titles, label text and symbols written for Prism (phase 6, E-axes)

- **Text objects Prism derives itself:** `0x802B` +8 bit 0x4000. Examples are a
  graph title that follows the graph's name, an XY graph's X title that follows
  the X column's title, and the "XTitle"/"YTitle" placeholders. Prism ignores
  their stored text (`0x002C`) and draws its own. With the bit cleared, Prism
  draws the stored text as written and lays it out itself. Fixed titles in
  users' files have 0x8000. `refract.formats.pcff.texts` writes the text (code
  page 1252), its length (+6) and the size runs (`0x002D` attributes 1 and 9).
- **Tick / category label size:** Prism reads it from the `0x00AD` that follows
  each `0x8025` axis setting (+33, f32), 12 chunks after it in the shipped seeds.
  A re-save restores `0x8025` +38 from it. Each axis has three `0x8025`
  settings, X then Y then right Y; all three are written.
- **Category label angle:** `0x8025` +26 has a copy in every `0x0103` entry (u32
  count, then 8-byte entries; the angle is the entry's byte +4) between that
  setting and the next one. With only +26 changed, Prism restores the angle from
  `0x0103`. Values: 0 horizontal, 0x40 90°, 0x80 automatic; the corpus also has
  0x20 and 0x10, which are not decoded.
- **Symbol shape:** `0x009C` +34 and +109 and `0x8028` +60 (codes in
  `from_prism.SHAPES`). Writing all three is enough.
- **Symbol size:** `0x009C` +81 (u16 at +80 = code × 256) and `0x8028` +62
  (+61) both equal the size code (99.8 % of 1206 corpus plots), but they are
  derived. The setting is the f32 at `0x009C` +289: the size code when it is
  set, -3 when the plot uses Prism's default (corpus: +289 = +81 or -3 on
  every plot). Writing only +81 and +62 was undone by Prism; with +289 written
  too, Prism draws the size (E-pairs, see below).
- **Individual values over bars:** they come with the plot style (`0x009C` +133:
  3 and 7 draw them, 1 does not; +66 = 0 or 255 follows the style). The style
  has copies at +181 and +297.

## One-property pairs and plot styles written for Prism (phase 6, E-pairs)

From graphs a user made in Prism from neutral tables
(`corpus/manual/style_seed_tables.prism`, local only): Prism's own default
graphs of each style, and XY copies that differ in one property.

- **Minor ticks:** the axis's main `0x8025` setting (the first of its three)
  +52 = minor intervals per major tick (5: four minor ticks), and bit 0 of
  +29 in the `0x00AD` after it cleared (7 -> 6). With the bit set Prism
  chooses the minor ticks itself and overwrites +52 (E-misc: +52 alone was
  reset; a 3-inch axis got +52 = 10 by itself). Refract reads +52 back as
  the minor ticks Prism draws.
- **Object count:** `0x8018` +0 is the graph's index in the document, +4 the
  number of graph objects (`0x8020` directly inside it), on 10 of 10 graphs.
- **Property store:** `SEDObject_Array` in `0x0852` holds one entry per graph
  object, in stream order (data-set plots are the ones with an `XYPlot_Map`,
  the XY legend's row titles have a `RowTitleList_Map`).
- **Legend:** `0x8028` +58 bit 0x02 = the data set has a legend entry (set on
  every plot of graphs with a legend except 41 of 892 grouped plots, never on
  graphs without one). Prism's own hidden legend (a grouped pair): the legend
  entries (`0x8020` type 12) are gone, `0x8018` +4 counts the objects left,
  +58 bit 0x02 is cleared, and bit 0x08 is set at `0x8028` +113 and
  `0x009C` +113 on every plot - without that bit Prism rebuilds the legend
  on grouped graphs and on re-bound copies (it is set on every plot of the
  585 column-graph plots, which never get a legend). The property-store
  entries of the removed objects go too. Verified: XY, grouped and survival
  copies, grouped in place.
- **Error bars:** `0x8028` +12 = 1 SD, 2 SEM (0 in Prism's default column
  scatter, which draws the mean only); +59 = 4 means no error bars (the mean
  only), 0 error bars. Writing +12 (and +59 = 0 for column bars) draws SEM.
- **Bars over the points:** Prism's column "bars with individual values" is
  the scatter style (`0x009C` +133 = 3) with +15 bit 0x10 set; the grouped
  default has it too (+15 = 20). Setting the bit turns the default column
  scatter into bars with points.
- **Bars without the points:** plot style 1 (grouped) or 5 (column) in all
  seven style copies (`0x009C` +67, +129, +133, +177, +181, +293, +297),
  +15 = 0, +66 = +212 = +224 = 0xFF, +85 and `0x8028` +96 = 2 + the data
  set's index, `0x8028` +110 = 5 (column: +126 = 5 too). E-style changed only
  +133, +181 and +297 and had no effect. Per data set: a column graph can mix
  bars with and without points.
- **Column bar autoscale:** like Prism's bars but with the column scatter's
  margins - 5.05 % of the data span on top, 4 % below when the data go below
  0, always from 0 (24 of 24 variants; the bar rule's 5 % gives 0..8 where
  Prism draws Refract's sample 3.8..7.8 as 0..10).
- **Mean and error as symbols (column):** plot style 7 in all seven copies,
  +15 = 0, error bars on (`0x8028` +59 = 0), and with it `0x8028` +94 = 0 (no
  bar border), +110 = 4, +122 = 9, +126 = 7, `0x009C` +149 = 0, +153 = 9, the
  f32s at +265 = 0 and +269 = 12. Prism's own sample cycles the symbol shapes;
  the shipped seed and Refract keep circles.
- **Axis length:** the axis's main `0x8025` +30 (1/600 inch; 2400 = 4 in), its
  `0x0017` cache +42 (u16), the plot rectangle (`0x0013` +0: x0, y0, x1, y1)
  and `0x009E` +94 = 0. With +94 = 1 (the default) Prism keeps the graph's
  proportions and scales everything (E-misc's 3-inch Y axis). Text sizes stay.
- **Font:** `misc/used_fonts.bin` is the document's font table ("PCFF " magic,
  u32 count, record size 44, names offset 32, names length, records offset
  and length; the names concatenated; per record i32 index, i32 flag (1 on
  the first), name offset and length, weight at +32, 400 or 700). Graph
  texts point into it: text-run attribute 0 (attribute 2 = 1: bold, with the
  weight-700 record) and `0x8025` +34 for tick labels (+42 = 1: bold).
  Prism's "change all fonts" rewrote every run's index and both settings.
  A bundle Refract builds has no table; Prism's defaults are Arial 400 and
  700 at indices 0 and 1. Written tables round-trip byte for byte.
- **Not found yet:** means as symbols on grouped graphs (no sample), the
  donut (Refract has no donut).

## What Prism rebuilds on open (phase 6, level C, E-levelc)

One variant per chunk tag of a Refract-written column graph, with that tag
removed, opened, exported and re-saved by Prism (`tools/levelc_probe.py`):

- **Rebuilt, drawing unchanged (42 of 59 tags):** among them 0x8028/0x009C (plot
  headers and records), 0x00DB, 0x00A9, 0x0078, 0x0084 (object caches), 0x0852
  (property store), 0x00A5 (axis modes), 0x0014 (table link: Prism takes the
  `inputDataSets` of `sheet.json`), 0x80AD, 0x8080/0x00ED, 0x8003, and on
  grouped graphs 0x00AE (36 chunks, 47 KB).
- **Required (the graph is dropped):** 0x0013, 0x0017, 0x8012, 0x8018.
- **Content (the drawing changes):** text objects (0x802B/0x002C/0x002D) and
  their placement (0x002F, 0x0030, 0x0031, 0x0022, 0x002A), the objects
  (0x8020), axis settings (0x8025), 0x009E, 0x00A1.
- **Together:** with all rebuilt tags removed except 0x00AD, 0x0023 and 0x0021
  (needed in combination: without them the title box is drawn black and the
  ticks thicker), a column graph of 99 chunks and 3.4 KB opens as the full
  graph (SSIM 0.980-0.988; grouped 0.986, XY 0.987). Plot objects (type 9),
  legend entries (12) and type 14 objects can go too: Prism creates them from
  the graph's input data sets.
- **Not enough alone:** survival graphs (without plot records Prism draws XY
  symbols and its own X title) and pies ("Total=100" drawn twice).
- **Close markers:** a close marker implicitly closes children left open
  (0x8003 has none), so a container's extent ends at its own marker or at an
  enclosing one (`walker.subtree_end`).

## Graphs built from a skeleton (phase 6, level C, E-levelc2)

`refract.formats.pcff.skeleton` builds column, grouped and XY graphs from a
per-kind skeleton (`skeleton_data.py`, generated by `tools/make_skeleton.py`
from the shipped seeds) instead of a whole seed graph; `graph_transplant`
and `graph_patch` do the rest as for a seeded copy.

- **Kept beyond the E-levelc minimum:** the plot list 0x0015 with any plot
  objects (without it Prism treats the graph as having none and replaces
  them, formatting lost), 0x0027 (plot data-set link), the table link 0x0014
  and the text extents 0x002E (without them a re-bound XY graph keeps its
  cached axis ranges, its automatic X title reads "X" and the graph title
  is laid out small), 0x00A5 and 0x0103 (written by the patches).
- **Plot objects only when needed:** an unformatted graph has none and Prism
  makes them; style, error bars, data-set formats or a hidden legend keep
  plot objects for the first data sets (up to the skeleton's six).
- **Caches:** the skeleton's axis caches are the defaults'. Prism did not
  refresh them on every graph, so the resolved automatic range (Refract's
  autoscale, which matches Prism's) is written into the main 0x8025 setting
  and 0x0017, not marked manual.
- **Verified:** the 22 graphs of the writeback probes, built both ways, are
  drawn identically by Prism (same SSIM to Refract's drawing on every graph).
- **Survival (E-levelc3):** 0x2018 is required (not rebuilt). Prism crashed
  opening a survival graph without 0x000A, and re-saving one with plot
  objects but without the text objects' 0x0071; with both kept it opens,
  draws and re-saves (SSIM 0.998 to the seeded graph). Without plot objects
  Prism makes its own staircase plots (0.988).
- **Pies:** the pie data 0x80D6 is in the plot object. Without it Prism adds
  a pie plot of its own, with a second "Total=N" text; a pie skeleton keeps
  its plot and all its objects.
- **All five kinds** are now built from skeletons and drawn as their seeded
  copies (survival with formatting better: 0.952 vs 0.879).

## Automatic minor ticks (phase 6, E-minor)

- With the minor ticks automatic (0x00AD +29 bit 0 set), Prism writes its
  own choice into the axis's main 0x8025 +52 when it displays the graph: 10
  minor intervals (nine minor ticks) once the major ticks are more than 0.75
  inch apart (axis length 0x8025 +30 x tick / range), else 0. Corpus: 1418 of
  1440 automatic linear axes of displayed graphs (2748 axes; segmented axes
  with a garbage length and single-interval axes left out). Exactly 0.75 inch
  (four intervals on a 3-inch axis) gets none.
- Not reproduced (22): small integer ranges, where Prism chose 5 (0..15 tick
  5, 35..50 tick 5) or none (0..6 tick 2, -7..-4 tick 1) instead of 10.
- Refract: `autoscale.auto_minor` for graphs it makes (both axes; X minor ticks
  are drawn below the axis like its major ticks); a Prism graph keeps the
  value in its file; a minor-tick setting turns the automatic choice off.
  Skeleton graphs get the value in +52 (still automatic).

## Grouped means as symbols (phase 6, E-gmeans)

- From 94 plots of Prism's own grouped graphs drawn as mean and error
  symbols (local corpus copies): plot style 7 at 0x009C +133, +181 and +297
  only; +67, +129, +177 and +293 hold the grouped base style 1. Bar flag +15
  = 0, 0x8028 +110 = 3; the border (+94), +122, +149, +153 and the f32s at
  +265/+269 keep the grouped defaults (unlike column means). Written, Prism
  draws Refract's grouped means with SEM as Refract does (SSIM 0.986).
- **Symbol cycle:** Prism gives data sets the shapes 5, 1, 2, 3, 4, 10
  (circle, square, triangle, triangle down, diamond, bordered circle) - in
  these graphs and in the XY seed (stored last data set first).
  `build.SYMBOLS` follows it now (it had a diamond fourth).

## Donut (phase 6, E-donut)

- Prism's own pie and donut of the same neutral table (the user's sample)
  differ, beyond ids, in 0x80D6 +20 only: 1 pie, 2 donut (corpus: also 5
  for a percentage dot plot, and 4 not decoded). Writing 2 into a pie makes
  Prism draw a donut; 0x009E +50/+74/+124 (also 1 -> 2 in the sample) do not.
  0x8028 +99 (3 on the one earlier corpus donut, 0 on these) is not the
  setting; `from_prism` reads +20 now.
- The hole's radius is half the outer radius (measured on Prism's export
  with the 1.44 pt outlines allowed for), and Prism outlines the hole too.
- The 0x80D6 of the shipped pie seed holds nonzero bytes from +64 on that
  look like in-memory values; Prism's donut has zeros there. They do not
  change the drawing.

## Label angle and the other axis length on new graphs (phase 6, E-layoutfix)

- **90° labels:** on a graph Prism re-lays out (a new graph), 0x8025 +26 =
  0x40 with its 0x0103 copies is not enough: Prism set the main X setting
  back to 0x80 (automatic). The 0x00AD after it carries the switch: +29 bit
  0x04 = the angle is automatic (bit 0x01: the minor ticks), and +41 = 1 on
  every corpus axis at 90° (4 of 4; 0 on 841 others). With bit 0x04 cleared
  and +41 = 1, Prism keeps 90° (Column titled 0.750 -> 0.820). A level-A
  graph in place had kept 90° without them (E-axes).
- **Skeleton angle:** the grouped seed stores 0 (horizontal), which Prism
  keeps once an axis length is set; Prism's own default graphs carry 0x80
  after a re-save. Column and grouped skeletons now store 0x80.
- **One axis length set:** the other axis keeps the skeleton's length (3 in
  on the grouped one, from six data sets), not Prism's default for the
  graph. Refract writes both, the unset one from its own layout (Prism's
  default rules: 2 in for 3 groups x 2 sets). Grouped Georgia 0.667 -> 0.886.


## Plot style codes, whiskers, centres and horizontal graphs (phase 7, E-compare)

Found by writing Refract graphs with one field forced per graph and having
Prism export each (tools/prism_auto.py, `--no-resave`); docs/experiments.md
E-compare has the probes.

- **0x0013 +29 bit 0x80:** the graph is horizontal (categories down the
  left). 7 of 7 horizontal bundled sample graphs, 0 of 96 others. The value
  range is on the stored X axis (axis 0) and the plot keeps its shape: the
  values take the bottom length, the categories the left. The first
  category is drawn at the bottom. Prism keeps it on column graphs only: on
  re-save it cleared the bit of a grouped graph. A horizontal graph's value
  axis is re-autoscaled from the 0x0017 extent cache without the bars'
  baseline (bars of 4.3..7 drew 4..8), so Refract writes the drawn range as
  the cached extent.
- **0x009C +133 style codes** (with the copies at 67, 129, 177, 181, 293,
  297 on column plots; grouped plots take the code at 133/181/297 with the
  grouped base code 1 at +67):
  - column: 0, 1, 2, 9, 10, 12 draw nothing; 3 scatter; 4 box and whiskers;
    5 and 6 bars only; 7 mean and error; 8 the values without a centre line
    (with +8 = 1: a line to the next data set, before-after); 11 violin.
  - grouped: 0, 1, 2, 5 interleaved bars; 3 interleaved scatter; 4 box (drawn
    narrow: the width field is not known, 15 candidate bytes tried); 6 bars
    lying on their side inside the upright frame; 7 means; 8 the values only
    (with +8 = 1: each row's values joined to the next data set's, not the
    replicates across rows); 11 violins; 9, 10, 12 nothing.
- **0x009C +8 = 1** on a means plot (code 7) connects the means, on column
  and grouped graphs.
- **0x009C +125:** box whiskers. 0 min to max (what Prism draws when the
  field is 0, as in Refract's seeds), 1 Tukey (the values beyond as dots),
  2 10-90 percentile, 3 5-95 percentile. The bundled box sample (10-90) has
  2. 4 drew like min to max on 25 values (2.5-97.5 or 1-99: not told apart).
- **0x8028 +59 and +12:** the centre and the error bars. +59: 0-3 the mean,
  4-7 the median. +12 with the mean: 0 none, 1 SD, 2 SEM, 3 95 % CI (t),
  4 range, 5-9 none. With the median: 0 none, 3 interquartile range, 4 and
  7 range (7: perhaps the median's CI, the same as the range on 6 values),
  others none. The earlier reading of +59 = 4 as "mean only" (E-pairs) was
  the median: on the E-pairs data the two coincided.
- **Quantiles:** Prism's quartiles and percentiles are at rank (n+1)p
  (box of 3.8 3.9 4.1 4.3 4.6 5.0 sample values; IQR 3.5..7.5 of
  2 4 4.5 5 6 12), as refract.stats.descriptive.percentile.
- **Violins:** the density is drawn to about two bandwidths past the
  extremes (1.89-1.96 Silverman bandwidths on three sample columns), with a
  heavy outline and thin solid lines at the quartiles and the median.
- **Bars only, grouped:** Prism fills the second data set 143,143,147
  (bars with the values: 160,160,164).
- **Broken (segmented) axes:** the 0x8025 settings after an axis's main one
  (positions 3w+1, 3w+2) are segments when their object ids differ from
  their positions (default ones have id = position and 0..100 by 10). On the
  bundled asterisks box sample the Y main setting holds the bottom segment
  (0..40, tick 50, 109/600 in) and position 4 the top one (50..80, tick 10;
  +30 low 16 bits = 1089/600 in, the high bits are set). Refract draws the
  segment that holds the data, without the break.
- **Pairwise comparison brackets from an analysis:** their text object
  stores "???"; Prism fills in the summary (***) from the analysis and hides
  the brackets of comparisons not shown. Refract draws the stored text and
  every bracket: still to do.
- **Violins (refit, E-compare probe 8):** Prism's density uses about half
  Silverman's bandwidth (0.47-0.57 of 1.06 sd n^-1/5 on six violins of 6, 12
  and 25 values) and is drawn out to about 3.6 bandwidths past the extremes;
  every violin has the same widest width; the outline is 2.16 pt, the
  quartile and median lines 0.72 pt.
- **Box whiskers +125 = 6:** min to max with every value drawn over the box
  (the bundled asterisks sample). The values over a box are drawn 0.72 pt per
  +81 size step (size 4: 2.7-2.9 pt in both box samples), not 1.58.
- **XY plots:** +8 = 1 joins the points (with +4..+7 = FF); with the symbol
  shape 0 (+34, +109 and 0x8028 +60) only the line is drawn; 0x8028 +59 = 8
  fills the area below the line, opaque, in the plot's colour, the first
  data set on top. XY style codes 1, 2, 4, 5 draw bars between consecutive
  data sets or nothing (not Refract's "bars at each X").
- **Grouped arrangement:** a separated graph (bundled spacing sample g8) has
  0x0013 +42 = 3, +24 = the number of category positions (12 = 3 rows x 4
  data sets) and one 0x0027 label chunk per position; setting +42 and +24
  alone draws interleaved bars. Stacked bars: 0x0013 +38/+40 = 2 with every
  plot copy 2 draws full-height bars, not stacks. Neither is written yet.
- **Default fills of new graphs:** Prism 11 fills the second data set
  160,160,164 (PDF and PNG exports of Refract's graphs); 176,176,179 is in
  older corpus files.
- **Contingency tables** are drawn by Prism on the grouped skeleton as its
  grouped graph (rows as groups); a nested table on the column skeleton is
  drawn with its subcolumns averaged as replicates (not written).
- **Floating bars:** not found (style codes 4-6 with the range error codes
  draw boxes or bars with error bars).
- **Pairwise comparison brackets** (0x8020 type 3 with 0x80D8 +4 / 0x2010:
  the comparison's index; header +28 bit 0x02: hidden, as on text objects)
  are each followed by a text object storing "???": Prism draws the
  comparison's P value summary there (the analysis results; *** on the
  asterisks sample, the two ns comparisons hidden).

## Graph types from Prism's own graphs (phase 7, E-types)

Prism's scripts cannot choose a graph type, so the user made one graph per
missing type by hand in Prism on Refract's sample tables
(corpus/manual/type_reference.prism, 28 graphs). tools/type_templates.py
compares each with Refract's skeleton field by field; the types are written
from seeds made of those graphs (tools/make_type_seeds.py: written on
neutral tables, re-saved by Prism, checked for sample text) and read back
by these fields:

- **0x009C +32: the arrangement of a grouped plot with the next data set:**
  interleaved 0, 1, 1, ...; separated 0, 0, ...; stacked 2, ..., 2, 0. The
  graph header 0x0013 +42 (3 separated, 2 stacked, ...) and +24 (category
  positions) follow it but do not make it: written alone they drew
  interleaved bars. Kept only with Prism's rebuilt chunks, which the level-C
  skeleton drops - hence seeds for these types. 0x009C +28 is not the
  stacking (3 on the reference, 4 after Prism's re-save of the seed).
- **Floating bars:** box code 4 with 0x009C +24..27, +105..108 and the
  whisker field +125..128 all FF (-1). The bundled overlay sample's
  floating bars have the same.
- **XY each replicate:** 0x8028 +58 bit 0x10; with +8 = 1 a line through
  the means, with 0x009C +12 = 1 a line per replicate. Grouped "each
  replicate connected across rows": style 0, +8 = 1, +12 = 1.
- **XY bars:** symbol shape 15 (0x8028 +60): a bar from the axis; every
  data set's bar at its X, the first on top.
- **Horizontal grouped graphs:** written from Prism's own (style code 2 in
  every copy, 0x0013 +38/+40 = 2): Prism keeps them on their side.
- **Parts-of-whole stacked bar:** the pie's chart kind 0x80D6 +20 = 4 (1
  pie, 2 donut); one bar half the square's width, the parts top down.
- **Nested graphs:** Prism labels every group with the first title row
  (untitled: the first data set's title and a number) and autoscales a
  nested scatter by the XY rule (4..9 for 4.4..8.1).
- **Survival** points and deaths: written from seeds. Prism has no
  staircase without ticks (its wizard: round 2); the type stays Refract's.
- **Heat map:** seeding one this way made Prism quit while it drew it; not
  written. Read: a grouped plot with 0x009C +15 bit 0x02.
- **100 % stacked:** Prism's wizard has none (round 2). The first sample
  table's rows summed to 100, so its reference showed no 100 % stacking (only a probability Y scale: 0x00A5 +64/+66 = 3,
  with copies in 0x0017 +46, 0x8025 +86 and 0x0103). Not written.
- **Default look of these types** (Prism's own): first data set black;
  separated and nested symbols from the square; stacked bars without
  borders, the legend top down, spaced as a column graph; no Y title on a
  contingency table's stacked graph.

### Second reference batch (E-types round 2)

The user made a second set by hand (corpus/manual/type_reference2.prism, 14
graphs); Prism's Create New Graph window has no staircase without censor
ticks and no contingency bars stacked to 100 %, and its trial allows two
Multiple-variables graphs only (the user's screenshots, 2026-11-16).

- **0x0013 +42 of a survival graph is the wizard's choice:** 11 staircase
  with ticks (Prism's default), 12 points at each step joined, 14 staircase
  with a symbol at each step, 16 deaths with ticks, 17 deaths at each step
  joined. 0x009C +8: 1 points joined straight, 2 a staircase; +34 = 14 the
  censor tick, else the step symbol. A staircase with symbols draws the
  symbol at each step and at each censored subject; its legend shows the
  symbol.
- **Horizontal bars' style code is 2** (upright 1) in every copy. A
  horizontal grouped box plot keeps 2 in the base copies +129, +177, +293
  and 0x8028 +126, the plot's own style in +133, +181, +297 and +67 (upright
  1 and 4); h110 = 3. Means, violins and floating bars on their side are
  written on Prism's own horizontal bars and box seeds that way (means: 7 in
  +133/+181/+297, +67 = 2; violin: +67 = +297 = 11; floating: the FF
  fields): Prism draws all four on their side. A level-C skeleton with the
  horizontal bit alone stays upright.
- **Horizontal stacked bars and floating bars:** the value axis is 3 in
  (216 pt), not the upright type's X length; the category axis 2 in.
- **Parts-of-whole stacked bar on its side:** 0x80D6 +20 = 3; the bar is the
  square's width and half its height, the parts left to right.
- **Nested box, floating bars, violin:** box code 4 (floating: the FF
  fields), violin 11; box and floating bars autoscale by the XY rule (4..9),
  the violin from 0.
- **Seeds without the violin cache:** 0x00AE (rebuilt, skeleton.REBUILT)
  holds a violin's curves, megabytes per graph; the seeds are kept without
  it (the shipped seeds 4.2 -> 1.5 MB) and Prism draws them the same.
- Reference graphs not taken: "Interleaved symbols, horizontal" came out as
  Prism's horizontal bars (grp_bars_h).

## Multiple-variables graphs (phase 7, E-mv)

Prism stores a graph of a Multiple-variables table as JSON in its graph
sheet (graphs/<uid>/sheet.json, "graph": {"@class": "MVGraph"}); its
data.bin is empty or not PCFF. xVariables / yVariables name the variables
by data-set uid, dataSheet the table; gdoTypes.defaults the figures
("symbols", "lines"); gdoSettings.<figure>: colorVariable and colormap
(SingleColormap color; CategoricalColormap colorSchemeID - a Prism scheme,
not one colour per category; GradientColormap colorScheme, e.g. "Viridis",
and colorsTransparencyPercent), sizeVariable and sizeEvaluator
(SymbolSizeEvaluator symbolSize; CategoricalSizeEvaluator sizesDictionary
by lower-case category; ContinuousSizeEvaluator symbolSize ..
largestSymbolSize); width / height: the plot in points; axisX / axisY
titles and segments (lowerLimit, upperLimit, interval). Legends:
GradientColorLegend (a colour bar), CategoricalSymbolsLegend,
ContinuousSizesLegend. Refract reads them (refract.render.mv_prism) as
points with per-point sizes, a colour bar for a gradient, and writes its
bubble and scatter graphs as such sheets (refract.formats.mv_writer).
Verified in Prism: a sheet with only the plot's place and size, the title,
the axes, the variables and one symbols figure is drawn, Prism adding the
legends and data limits itself; a CategoricalColormap takes its colours
written out (colorSchemeColors and colorsDictionary by lower-case
category: the bundled Wine sample stores them so), a colorSchemeID picks a
Prism scheme (0: all black). ContinuousSizeEvaluator: the area in
proportion to the value from customMinimalValue (symbolSize there), at
most largestSymbolSize (Dose 10, 20, 30 -> 3.9, 5.5, 7.0 pt).

Prism's own default bubble graph (the two the trial allows: coloured by a
number, and also sized by it) is a viridis gradient 50 % clear and sizes
6 .. 16 pt from the smallest value. Its legends, measured at 300 dpi: a
colour bar 20 pt wide, 18 pt right of the plot, as tall as the plot, ticked
by 1 for 1.8 .. 5.9 (a finer rule than the heat map's), its title 8.6 pt
above the plot, left-aligned on the bar; a sizes legend in the next column,
18 pt after the colour bar's column (the wider of its title and the bar
with its labels): the smallest, the geometric middle and the largest value
in two decimals (1.80, 3.26, 5.90 at 6, 8.07, 10.86 pt), rows 18.5 pt apart
from 8.7 pt below the plot's top; the graph title's baseline 28.8 pt above
the plot. Refract draws its own bubble graphs from the same settings it
writes (refract.formats.mv_writer.figure read by mv_prism.read_table), so
both programs draw one graph: Refract's reading of Prism's two scores ink
0.87 and 0.94. Some MV graphs plot an analysis's output table, which
Refract does not read yet.

## Graph elements formatted one by one (phase 7, E-elements)

Refract's Format panel sets each data set's fill, hatch pattern, border,
error bars, symbols and line, a significance bracket's line and place, and
draws lines, arrows, boxes, ellipses and text boxes (formatting "sets",
"texts" bracket.<j>, "shapes", "notes"). The stored forms come from a
reference file the user made in Prism with one change per graph
(corpus/manual/elements_reference.prism, 14 graphs), Prism's PDF stroke
widths, and probes drawn by Prism:

- **Widths** are stored three times: a code in the 0x8028 header, its copy
  in the 0x009C record, and the width in 1/600 inch (f32) - bar border
  +94 / +149 / +265, connecting line +92 / +145 / +261, error bars +122 /
  +153 / +269 (-3: Prism's default). Code 0 none, else 7 + width / 0.72 pt
  (PDF strokes: 8 -> 0.72, 10 -> 2.16, 11 -> 2.88, 12 -> 3.6 pt). Written
  in one copy only, Prism drew the old width; in all three, the new one.
- **Hatch patterns:** 0x8028 +96 = 0x009C +85 the pattern (Prism numbers
  the data sets' plain fills 2, 3, 4, ...), drawn only when
  PCFF_Plot::patterncolor in the store is opaque (none: ffffff00), with
  copies at 0x8028 +80 (R G B 0) and 0x009C +221 (R G B FF). Codes, each
  drawn by Prism: 1 fine dots, 2 checkerboard, 3 large checkerboard, 4
  horizontal, 5 vertical, 6 "/", 7 "\\", 8 grid, 9 diamond grid, 10-15 the
  bold "\\", "/", vertical, horizontal, grid, diamond grid, 16 dark bricks,
  17 bricks, 18 scattered dots, 19 texture; 0 and 20+ none. The lines are
  the pattern colour over the bar's fill.
- **Drawn objects** are graph objects (0x8020 in the object list, with a
  property-store entry each in SEDObject_Array): type 3 line or arrow, 1
  rectangle, 6 ellipse, 2 text. 0x8020 +2 holds three boxes - the
  object's box widened by 36 page units, the box, the box narrowed by 24
  (a text box's words wrap inside it) - copied as 32-bit numbers at
  0x00DB +162, where Prism places the object from. A line's ends: two
  0x00D9 (+4 x, +8 y); its style 0x0023: +0 width code, +4 R G B, +8 = 1
  an arrow head, f32 +22 the width; a box's border 0x0022 (+0 code, f32
  +16), fill 0x0021 (+2 R G B, then 0; none FF). Colours in the store:
  PCFF_LineStyle::linecolor, PCFF_BorderStyle::bordercolor,
  PCFF_FillStyle::fillcolor (alpha 0: none). A text: 0x802B +0 its id, +6
  its length (Prism shows that many characters), 0x002C the words, 0x002E
  +2 the last index and +10 the line's width. Written from templates of
  the reference objects (seed_graphs/objects.json,
  tools/make_object_templates.py), Prism drew all five as Refract does.
- **Pairwise comparisons** in Prism 11 are type-3 lines with two points
  (0x80D8 +24 = 2): Prism draws them straight, without legs; the bundled
  sample's brackets have three points (+24 = 3: the legs' ends and the
  label's anchor) and legs. Refract now reads a two-point line straight.
- Reading back: your reference graphs drawn by Refract score ink 0.85-0.94
  against Prism's (the rectangle 0.40 -> 0.94, the ellipse 0.49 -> 0.93
  once objects outside the plot count for the page); the 72 bundled
  samples are unchanged (one 0.65 -> 0.67).

## Heat maps written for Prism (E-heat)

Written from Prism's own heat map (the user's reference, re-saved by Prism
on a neutral 6 x 5 table: seed_graphs/types/grp_heat_viridis.pcff).

- **Why Prism quit:** a heat map's 0x80F4 +8 and 0x00F8 +8 hold its graph's
  fenID (as a pie's 0x80D6 +8). The copy gave the graph a new fenID but left
  these at the seed's; Prism quit drawing it (four times). Set to the new
  fenID (graph_copy.HEAT_GRAPH_FEN), Prism draws it. Its other fields
  (0x80F6 +8, 0x00F7 +8, 0x009C +141, 0x80F4 +4 / +152..) are ids as a pie's
  and are renumbered: kept as the seed's, a second heat map in the file was
  drawn in rainbow colours instead of viridis.
- **Pies beside heat maps:** a pie's plot names its pie data (0x009C +141 =
  0x80D6 +4). With the heat maps' 0x009C +141 in the count, the two parted
  and Prism drew the pie blank; they are now numbered together. Prism's own
  copies of the older pies number the chart id (0x80F4 +4) apart (the
  DuplicateFamily sample stays byte-exact).
- **Its cache, sized for the table:** 0x80F4 +20 the colour range (middle,
  lowest, highest cell mean, twice, f64), +68 / +72 the rows and columns; per
  column a 0x80F6 with +40 its rows and a 20-byte record per row (1, RGBA,
  the cell's mean f64, the row). Written with the table's counts and blank
  records, Prism computes the values and colours itself (2 x 3, 2 x 5, 6 x 5
  checked); it adds the columns beyond the seed's two.
- **Prism's default heat map:** rows numbered, columns lettered, no title,
  square cells min(216 / rows, 216 / columns) pt; Refract draws it so (ink
  0.36 -> 0.996). The colour map is not found in the blob, the store or the
  sheet; Refract's other colour maps are written as viridis (the report says
  so).

## Analyses offered and checked in phase 8 (E-stats8)

- **The New Analysis dialog** offers 13 more of the analyses Refract
  computes: frequency distribution, identify outliers, Bland-Altman, ROC
  curve, area under curve, simple logistic regression, nested t test and
  one-way ANOVA, multiple linear and logistic regression, Cox regression,
  PCA and multifactor ANOVA. Their parameters start from Prism-written
  sets (refract/stats/defaults.json, tools/make_defaults.py) without the
  parts that name data sets or variables; those are built from the table
  analysed (refract.stats.catalog.build): the two data sets of
  Bland-Altman and ROC, and a Multiple-variables table's dependent
  variable, predictors (the chosen variables) and variableInfo
  (CONTINUOUS, or CATEGORICAL with AUTO_FIRST_LEVEL, its first level,
  levelCount, levelOrderType VISUAL), a two-valued outcome's outcome0 /
  outcome1. Created as the dialog does and computed by Prism (re-save),
  13 matched value for value; Prism does not compute a multifactor ANOVA
  under scripting (its results stay empty).
- **Cox regression:** the parameters' correlation matrix
  (model.covariance) is reported whatever diagnostics.parCorrelation says
  (corpus cases with it off have it); a numeric event column is matched
  as text ("1" and 1.0 alike).
- **Entered mean, SD (or SEM) and N:** Prism's t tests (unpaired, Welch)
  and one-way ANOVA of such column tables depend on the summaries alone:
  Refract computes them from values with exactly those means and SDs.
  Prism's results add each group's n, mean, SD, SEM and CI to a t test,
  and leave the Brown-Forsythe and Bartlett tests and the medians and
  quartiles out of an ANOVA. All fields matched on three tables.
- **Compact letter display** (results compactLetterDisplay: letterCount,
  sampleCount, a letter string per data set): Prism reports it for every
  two-group test and for one-way ANOVA with all pairs compared (not FDR).
  Insert-and-absorb, letters from the largest mean down, gives Prism's
  letters in 875 of 879 t tests and 861 of 920 one-way ANOVAs of the
  corpus (the rest: P values at the threshold, older stored results
  without letters, and a few groupings where several letterings are
  valid). Two-way ANOVA's letters are not written yet.
- **Fit spline / LOWESS (phase 8: first findings; see phase 8c):** the curve is a results table
  (view) whose X is a series from the first to the last X, 4 points per
  data point (Prism sets calc.curve.segmentCount so). CUBIC_SPLINE is a
  natural cubic spline through the points and AKIMA_SPLINE Akima's spline
  (both exact against scipy); LOWESS FINE joins the data when there are
  few points. SMOOTHING_SPLINE (knotCount) and LOWESS MEDIUM / COARSE are
  not reproduced yet (natural regression splines come within 0.01-0.03;
  Cleveland's LOWESS over every span, with up to three robustness steps,
  within 0.02-0.08). Point-to-point is not POINT_TO_POINT (Prism reads it
  as UNKNOWN).
- **Not in Prism 11.1:** no McNemar test (the chi-square dialog has none;
  its phi coefficient needs a licence the trial lacks) and no multiple
  Poisson regression. Fraction of total, observed vs expected, prune rows
  and select / remove columns were not made in the reference file and
  stay open.

## Analyses added in phase 8b (E-stats8b)

From the reference analyses the user made in Prism on Refract's sample
tables (corpus/manual/analysis_reference_tables.prism), each checked on
generated tables computed by Prism (tools/table_oracle.py: results and
every result-table cell):

- **Correlation matrix** (CORRELATION of a column or Multiple-variables
  table, or of an XY table's Y data sets with pairwiseDesign.type
  ALL_VS_ALL): pearsonTestModel / spearmanTestModel nested per pair,
  {colI: {colJ: test}} for J >= I, keyed by each data set's index in the
  table. The diagonal is status PERFECT_LINE, r = 1, CI 1 to 1, P 0, n the
  variable's own count (Spearman adds pValueExact / pValueApproximate 0,
  no r2). A text (categorical) variable is left out, the others keep
  their indices. options.excludeIncompleteRows uses only rows where
  every variable has a value; a one-tailed P is half the two-tailed one
  (exact and approximate alike). Result tables: Pearson r / Spearman r
  (full, symmetric), P values (blank diagonal), P value type (Spearman:
  Exact up to n = 17, then Approximate), Sample size, Confidence interval
  of r / rs as text, four significant digits with trailing zeros kept
  ("-0.008400 to 0.04440"; Spearman's interval blank for n <= 10).
  2299 of 2299 values and every cell of 44 analyses matched.
- **Deming regression, "Line" table:** one X series over all data sets'
  X (101 points for one data set, 201 for more), each data set's line
  blank outside its own X range. dataSummary.xValues counts the table's
  rows with an X up to the data set's last value; pointsSkipped the
  blanks among them. All variants matched (50/50 values per pair of sets).
- **Standard-curve interpolation** (INTERPOLATION): the same fit as a
  nonlinear regression of the rows with an X, with asymptotic
  (symmetrical) intervals; dataSummary per data set at the top level;
  runsTest when diagnostics.runsTest and the X values are distinct;
  with replicates instead a replicates (lack-of-fit) test: sdReplicates
  (pure error), sdLackOfFit, F with df (X values - parameters, points -
  X values). Unknowns are the rows with a Y and no X; X is read off
  within the standards' X range extended by half of it on each side,
  never below zero when every standard's X is >= 0 (Y beyond a
  sigmoid's plateaus: blank). The curve itself spans only the data.
  Tables, data sets stacked one below the other: "Interpolated X values"
  (single Y), or "Interpolated X mean values" and "Interpolated  X
  replicates" (two spaces, Prism's title). Line, quadratic and 4PL
  matched on every value and cell.
- **Perfect fits** (no scatter): status PERFECT_FIT, estimates without
  SE or interval, the parameter correlation from the fit's shape alone,
  ss 0, aicc "undefined"; the runs test is INVALID with zero counts.
- **Initial values:** an initialValues entry with isAuto true takes the
  equation's rule, not its stored value (0.0 in a new analysis); a 4PL
  started from 0 had converged to the mirrored solution.
- **The dialog** now also offers correlation matrices (column and
  Multiple-variables tables; XY: X with each Y or every pair of Y data
  sets, with one-tailed P and complete-rows options), analyze a stack of
  P values (BKY / BH / BY with Q in percent, Holm-Šídák, Šídák),
  relative frequency distributions, Deming regression, smooth /
  derivative / integral, nonlinear regression and standard curves with
  Refract's own list of seven models (refract/stats/equations.py:
  straight line, second-order polynomial, 3- and 4-parameter log
  dose-response, one-site binding, one-phase decay, Gaussian). Created
  as the dialog does and computed by Prism, all matched (843 and 507
  values); nonlinear results differ only in layout (Prism 11.1 puts
  dataSummary at the top level and adds dsList and iterationCount).
- **Not yet:** smoothing splines (see phase 8c).

## Analyses added in phase 8c (E-stats8c)

Each checked on generated tables computed by Prism 11.1, every value and
result-table cell:

- **Fitted curves** (nonlinear regression and standard curves): a
  "Curve" result table on a linear X series of graph.curve.pointCount
  points (1000) from the smallest X (defaultMinCurveX "X=0": from zero)
  to the largest, or the set range when minX / maxX are not isAuto; one
  column per data set. A standard curve's table is y_plus_minus: the
  fitted Y and the half-width of its confidence band twice (t at the
  fit's df times the SE of the fitted value, from the asymptotic
  covariance; graph.curveBands.level). Prism stores a second, log-spaced
  curve sheet (from the smallest positive X; empty when X <= 0) for log
  axes; Refract shows the linear one. 31 analyses matched (rel 1e-8).
- **Deming regression with replicates:** data.handleReplicatesAs
  INDIVIDUAL fits every replicate as a point (xValues = rows x replicates,
  yReplicates = replicates, pointsSkipped = the blank slots); AVERAGE
  fits the row means (xValues = rows, yReplicates 1). With replicates the
  Line table has 101 points even for several data sets.
- **Selected pairs** (one-way ANOVA, pairwiseDesign SELECTED_VS_SELECTED
  with selectedPairIDList): offered with Šídák, Holm-Šídák, Fisher's LSD
  and FDR (Dunn for Kruskal-Wallis and Friedman, the Brown-Forsythe
  methods for Welch ANOVA); 8 designs matched, 801 values.
- **Tables made from tables** in the dialog (refract.stats.transforms,
  checked earlier by tools/table_parity.py): Transform, Normalize, Remove
  baseline, Row statistics and Transpose; their output is shown as a
  result table. 17 dialog-built cases on column, grouped and XY tables
  matched cell by cell.
- **Fit spline / LOWESS:** the curve has 4 points per data row (Prism
  sets calc.curve.segmentCount so) from the table's smallest to largest
  X, one X series, each data set's curve blank outside its own X range;
  replicates are averaged. LOWESS is, at each data X, a straight line fit
  with tricube weights and no robustness steps over a window of
  half-width FINE 1/20, MEDIUM 1/10 or COARSE 1/5 of the data set's X
  range, the curve joining those values with straight lines; a data set
  with fewer than 12 points gets the natural cubic spline instead (5 to
  11 points verified, the cut-off counts the data set's own points). 31
  curves from 5 to 40 points matched to 1e-14. SMOOTHING_SPLINE is close
  to a natural cubic regression spline with knotCount knots at the X
  quantiles (median 0.01) but not exact, also not a penalized smoothing
  spline: not computed yet. Point-to-point stays unknown (Prism reads
  POINT_TO_POINT as UNKNOWN).
- **Compare observed distribution with expected** (CHI2, Prism's Parts
  of whole analyses): see phase 8e.

## Analyses added in phase 8d (E-stats8d)

From Prism's own parameter sets (the user's reference file), each checked
on generated tables computed by Prism, every cell (61 analyses, the
dialog-built ones included):

- **Fraction of total** (FRACTION_OF_TOTAL): calc.type COLUMN, ROW, GRAND
  (each value over its column's, row's or the table's total, blanks left
  out) or ALL: a text table, "Data analyzed" (the values as entered, each
  column's total), then the fractions of column, row and grand total
  ("Fraction of ..." with four significant digits, halves rounded up, 0
  as "0.000"; with percentages "Percentage of ..." to two decimals and
  "%"), a last column of row totals; rows titled "Row 1"... when the table
  has none. calc.ci.calculate gives y_high_low: the fraction, then the
  distances to the upper and lower limits (Wilson/Brown or
  Clopper-Pearson of value out of its total), blank unless both are whole
  counts. Other type names are UNKNOWN (an empty table); a table with
  replicates is INVALID_DATA_FORMAT_SUBCOLUMNS.
- **Prune rows** (PRUNE_ROWS): calc.pruneByRange keeps the rows with X in
  xRangeToKeep (ends included). Otherwise rows are averaged in groups:
  averageType EVERY_OTHER_ROW pairs (n ignored), EVERY_NTH_ROW (and
  UNKNOWN) n rows; X is the group's mean X, each value the mean of the
  group's values, rows left over at the end are dropped.
  averageOnly.greaterThan keeps the rows with X up to xThreshold as they
  are. With replicates, a group whose last row is blank in a subcolumn
  gives a blank (single values: the mean of the others).
- **Select and transform** (SELECT_TRANSFORM, Multiple-variables tables):
  one output variable per enabled entry of transforms, titled with its
  title, its definition evaluated per row in Prism's syntax (A, B, C...
  the table's variables in order; log = log10, ln natural); a text
  variable passes through. rowFilters.range keeps rows from..to (1-based,
  inclusive; 0 counts as 1; -1: all). Prism rewrites definitions ("2 * A",
  "(C)^2") and appends disabled plain entries for the variables not kept
  as they are. Filters by variable values are not reproduced yet.

## Analyses added in phase 8e (E-stats8e)

- **Compare observed distribution with expected** (CHI2): one column of
  counts (data.datasetID), one outcome per row in calc.outcomes. Expected
  values are expectedCount (data.expectedValuesType COUNTS) or
  expectedPercentage of the observed total (PERCENTAGES); Prism reports
  both for every outcome, plus a total. When they do not add up to the
  observed total (or 100 %), Prism still computes, with the status
  INVALID_PARAMETER_EXPECTED_COUNTS / _PERCENTAGES. CHI_SQUARE_TEST:
  sum (O - E)^2 / E with outcomes - 1 df (chiSquareTest). BINOMIAL_TEST
  with two outcomes: the exact binomial test of the first outcome
  (pValueOneTailed in the direction observed, pValueTwoTailed adding the
  outcomes no more likely than the one observed) and each outcome's
  ciOfObserved in percent (calc.ciMethod
  CI_PROPORTION_METHOD_WILSON_BROWN / _CLOPPER_PEARSON). With more than
  two outcomes Prism's binomial test uses the first two rows for the
  one-tailed P, its two-tailed P follows no rule found: not computed.
  Other test names are UNKNOWN (no results). 17 analyses matched, the
  dialog-built ones included; fraction of total also on Parts of whole
  tables.

## Drawn objects: one id per line (E-elements2)

- A drawn line's or arrow's 0x80D8 +4 is its own id, not an arrow flag
  (Prism's arrow head is 0x0023 +8 and 0x80D8 +28): Prism keeps only one of
  the lines that share an id when it opens a file (three lines from the
  template came back as one; rectangles, ellipses and a line with an arrow
  were all kept). refract.formats.graph_objects now gives each line the
  next free id of the graph; with that, Prism kept and drew every kind of
  the Draw menu written as its primitives (two brackets with text, a line
  with end bars, a double arrow, a square bracket with text, a rounded
  rectangle as a rectangle, a circle, an elbow arrow), and four lines in a
  row. This also fixed graphs with several lines drawn in Refract.

## Column analyses of XY and grouped tables (E-kinds)

- Prism runs the column analyses (descriptive statistics, t tests,
  one-way ANOVA, one-sample tests, normality tests, frequency
  distributions, outliers, correlation matrix, fraction of total) on XY and
  grouped tables too, each data set being one column. With replicates, each
  row's mean of its replicates is analysed (every value matched; pooling
  the replicates did not). A t test of such a table adds descriptiveStatistics
  for each group (n, mean, SD, SEM, CI, minimum, quartiles, median, maximum;
  meanRanks for Mann-Whitney) and, paired, the second group minus the first
  ("differences", its id a list of the two data sets). A frequency
  distribution of an XY table with replicates takes its automatic bin width
  from every replicate value, its first and last centres from the row means
  (grouped tables: everything from the row means). 4 table layouts x 9
  analyses, 2019 values matched.


## Clustering, Extract and rearrange, Multiple-variables designs (E-extract, E-cluster, E-mv)

- **The trial computes none of these but Extract and rearrange:** analyses
  of class HIERARCHICAL_CLUSTERING, K_MEANS_CLUSTERING and any analysis with
  `variableDesign` (a t test, curve fit or survival analysis of a
  Multiple-variables table) get result sheets but no results when the trial
  Prism opens a file, nor with the script command `RecalcAll`, even Prism's
  own templates with their results removed (`isCalculated` stays false).
  Probably licence-locked; not pursued. The reference is the results Prism
  stored in its own bundled templates, read in place (tools/template_parity.py):
  10,355 values and cells, all equal.
- **Prism saves unknown enum names as written:** guessed linkage, distance and
  algorithm names all came back unchanged, so a re-save does not tell a real
  name from a guess. Only names seen in Prism's own files are offered.
- **EXTRACT_REARRANGE** (parameters 0.0.1; computed by the trial, 15 cases
  cell for cell): `resultTableFormat` GROUPED takes
  `dataArrangement.responseVariable`, `rowFactorVariable` and
  `columnFactorVariable`: the row factor's levels are the rows, the column
  factor's the data sets, each cell's responses its replicates in table order
  (replicate k holds every row's k-th value); the replicate count is the
  largest cell. COLUMN takes `groupingVariable` (a data set per level, padded
  to the largest group); without one the response is a single column, and
  `rowTitles` {type VARIABLE} titles its rows. Rows with a blank response or
  factor are left out; levels keep their first-appearance order;
  `includeVarNamePrefix` titles a level `Name = "level"`. XY (`xVariable`,
  `x`, `xValuesVariable` tried) and CONTINGENCY gave INVALID_VARIABLE_DEFINITION;
  SURVIVAL crashed Prism. The reader now tolerates a result table storing fewer
  columns than its format implies (Prism trims empty trailing replicates).
- **HIERARCHICAL_CLUSTERING** (sheet minRequiredVersion 10.3): agglomerative
  linkage of the transformed data equals scipy's (GROUP_AVERAGE = average,
  COMPLETE = complete; EUCLIDIAN; `columnTransform` STANDARDIZE = z with
  SD (n-1), `rowTransform` CENTER = less each row's mean). `data.inputType`
  ROWS_COLUMNS also clusters the variables (results `columns`). Results
  `rows`/`columns`: `dendrogram` (per merge node1, node2, distance, cluster
  {id n + j, "Cluster j+1"}; leaves are rows, labelled by `data.label`),
  `copheneticCorrelation`, `clusters` (a cut, `defineClusters`
  NUMBER_OF_CLUSTERS), `clusteringDetails` (WCSS for 1..n-1 clusters, with the
  ELBOW_PLOT graph). **Node order:** Prism keeps its clusters in a list; a merge
  puts the new cluster where the later of the two was and drops the earlier
  one, which is node1 (42/42 merges). **Cluster order of a cut:** the roots as
  they appear in the last k-1 merges. Result tables: Clustered data, Distance
  matrix (lower triangle unless `outputFullMatrix`; full: diagonal 0),
  Cophenetic distances (diagonal blank), Merge map, Elbow plot,
  Standardized/centered data. Not found: the heatmap's row order (neither
  node-first walk, height, size, weights nor optimal leaf ordering).
- **K_MEANS_CLUSTERING**: Prism starts each k from one random partition
  (`randomSeed`) and stops at local optima at times (WCSS above the best
  for k = 2, 4-7 in its sample); its clusters cannot be reproduced. Given
  Prism's own partitions every index matches but Krzanowski-Lai:
  calinskiHarabasz, daviesBouldin (spread = RMS distance to the centroid),
  cIndex, ratkowsky = sqrt(mean(BSS_v/TSS_v)/k), ballHall = W/k, gamma,
  gplus = 2 s- / (nt (nt-1)), tau = (s+ - s-) / (nt (nt-1)/2), dunn,
  ptbiserial (SD n-1), hartigan = (W_k/W_k+1 - 1)(n-k-1), mcclain, frey,
  silhouetteScore, percentOfTotalVariation = 100 W/T. Krzanowski-Lai fits no
  single exponent of the usual form. The gap statistic's expected log W
  matches uniform reference sets over the principal components' ranges
  (8.681 against Prism's 8.676; Prism's draws are not reproduced).
  `optimalClustering`: max (CH, Dunn, Gamma, KL, Ptbiserial, Ratkowsky,
  Silhouette, Tau), min (DB, C index, G+, McClain-Rao), largest drop
  (Ball-Hall, Hartigan), largest second difference (Trace W), first value
  below 1 (Frey), Tibshirani's rule (Gap), over k >= 2; the count is the
  majority. ANOVA per variable (SS between, F (k-1, n-k)).
- **variableDesign** (responseList, factorList, x, subject): the analysis of
  the table Prism builds - a column table with a data set per level (paired:
  rows matched by subject), an XY or survival table with X from the x
  variable. Groups are named `{"var": {"response", "factorList": [{"var",
  "value": level}]}}` where a table's data set has `{"col"}`. A t test adds
  descriptiveStatistics with `sample1` the second level and `sample2` the
  first, and `report.effectSizes` (paired: cohenD = mean/SD of the
  differences, hedgesG = d (1 - 3/(4 df - 1))). A curve fit puts each group's
  dataSummary beside the models. A survival analysis runs `postTests`:
  log-rank chi-square of each pair, Holm-Šídák (BONFERRONI and SIDAK are not
  its names: Prism stores UNKNOWN), `sample1`/`sample2` median and n = the
  group's events.
- **Column tables:** a t test with `report.descriptiveStatistics` adds the
  same descriptiveStatistics (Wilcoxon: the differences with no id);
  `report.effectSizes` adds nothing, and a survival table runs no postTests
  (checked with the trial, every value matched).
- **SELECT_TRANSFORM** `rowFilters.variableValue`: [{variableIdx, logic,
  value}], all must hold; a definition may give text (`if(E<=100, "Normal",
  ...)`), a categorical variable.

## Three-way ANOVA, smoothing spline, descriptive statistics (E-three-way, E-spline2, E-mv)

From the user's third reference set (corpus/manual/analysis_reference3_清单.md), then generated
tables computed by the trial Prism; every value matched.
- **THREE_WAY_ANOVA** (two_way-style parameters 0.0.1, grouped table with four data sets):
  "AB vs CD" (A, B against C, D), "AC vs BD", and the rows. ordinaryAnovaModel.anovaTable holds
  rowFactor, colABCDFactor, colACBDFactor, their three two-way and one three-way interactions
  (keys rowFactorVsColABCDFactor ... rowFactorVsColABCDFactorVsColACBDFactor, each with name, ss,
  df, ms, variation, fTest) and residual. Sums of squares are Type III (effect coding: full model
  against the model without the term), also unbalanced; variation = 100 SS / the total corrected
  SS of the data. report.means adds means (total, rows, colsABCD, colsACBD, colsABCDRows,
  colsACBDRows, colsABCDColsACBD, cells): unweighted means of the cell means; a level of
  AB vs CD is named by data set A or C, of AC vs BD by A or B. One value per cell:
  INVALID_DATA_TABLE_FORMAT_NO_REPLICATES. Seven cases (2 or 3 rows, 1 to 5 replicates,
  missing values), 67 to 103 values each. report.goodnessOfFit and effectSizes add nothing.
- **FIT_SPLINE_LOWESS SMOOTHING_SPLINE** (calc.curve.knotCount): a natural cubic regression
  spline by least squares. Knots: 2 = a straight line; 3 to 7 at Harrell's percentiles (Hmisc
  rcspline: .1/.5/.9; .05/.35/.65/.95; .05/.275/.5/.725/.95; .05/.23/.41/.59/.77/.95;
  .025/.1833/.3417/.5/.6583/.8167/.975); 8 or more at evenly spaced percentiles 0..1; a
  percentile p is the value at rank p (n + 1) (NumPy "weibull"). No curve with more knots than
  points, nor with 8 or more knots and as many points (6 knots on 6 points are drawn, 10 on 10
  are not). resolution has no effect. 38 curves within 1e-10 but one (20 knots on 30 points,
  1.3e-7: ill-conditioned).
- **DESCRIPTIVE_STATISTICS** (a Multiple-variables table): per numeric variable (text variables
  left out) the column statistics' descriptives plus iqr {iqr, q1MinusIQR, q3PlusIQR} (Tukey's
  fences), without the geometric mean unless calc.geometricMean. calc.medianCI: the narrowest
  pair of order statistics whose exact binomial level is at least the confidence level, reported
  at its own level (98.828125 for n = 11 at 95 %); harmonicMean (positive values; CI: the t
  interval of the reciprocals, inverted) and quadraticMean (CI: the square root of the t interval
  of the squares, lower end at least 0).
