# Refract UI specification

The interface follows the workflow that users of Prism-compatible software already know: a project holds data tables, info sheets, analysis results, graphs and layouts; each is a "sheet"; a navigator lists them; the main area shows the selected sheet. This spec is written from general knowledge of that workflow, in our own words. It copies no help text, icons or sample files (PLAN §6.7).

Status legend: **done** (implemented and tested), **partial**, **planned**.

## 1. Main window

| Region | Content | Status |
|---|---|---|
| Navigator (left) | Sections Data Tables, Info, Results, Graphs, Layouts, each listing its sheets in document order; a count after each section name; clicking a sheet shows it. Each section ends with New Data Table…, New Analysis…, New Graph…, New Layout…. Clicking the Results heading while a table without analyses is shown opens Analyze | done |
| Sheet area (centre) | One view per sheet kind (§3) | partial |
| Toolbar | Commands in labelled groups, each a small grid of icon buttons with tooltips (refract.ui.ribbon): File (New Project, Open, Save, Save As), Sheet (New Data Table, New Graph, New Layout, previous / next sheet), Undo (Undo, Redo), Clipboard (Cut, Copy, Paste on the grid; Copy Graph as a 300 dpi picture), Analysis (Analyze, Change Parameters), Change (Format Graph, Format Axes, Color Scheme menu, Magic), Text (font, size, bold, italic, underline, larger, smaller: for the text selected on the graph), Draw (Add Text; Line, Arrow, Significance bracket, Rectangle; a palette of every shape, line and line with text, as in the Draw menu), Export (Export Graph, Print), Help (User Guide). Icons drawn in code. Cloud and sharing commands are left out | done |
| Menus | File (New Project, New Data Table, Open, Open Recent, Save, Save As, Close, Export, Print), Edit (Undo, Redo, Cut, Copy, Paste, Copy Graph), Table (the shown grid's actions), Analysis (Analyze, Change Parameters), Graph (New Graph of This Table, Format Graph, Format Axes, Color Scheme, Magic, Save Style as Template, Add Text and the text styles, New Layout, Export), View (previous / next sheet), Help (User Guide, About with the non-affiliation notice; About sits in the application menu on macOS) | done |
| Start page | With no project open: New project, Open, and the recent files | done |
| Status bar | File name, sheet kind, warnings from reading the file | done |
| Colour scheme | Light and dark palettes follow the system setting and switch while running; every colour the window sets comes from the same palette as its text (contrast tested). Graph pages stay white, as exported. `REFRACT_THEME=light|dark` forces one | done |
| Window title | `Refract — <file name>` with `*` while there are unsaved changes | done |

View ▸ Group Sheets by Family shows the navigator by family instead: Info, then each data table with the analyses that read it and the graphs that plot it (Prism's and Refract's), then sheets that belong to no table, then the layouts (they mix families). The choice is remembered. **done**

## 2. Files

| Action | Behaviour | Status |
|---|---|---|
| New project (Ctrl+N) | The New Data Table dialog, then a new untitled project with that table and an info sheet. Saving it the first time asks for a file name | done |
| Open (Ctrl+O) | `.prism` and `.pzfx`; reading warnings go to the status bar | done |
| Save (Ctrl+S) | `.prism` sources: table edits are written into the original bundle (lossless pass-through, PLAN §2.4 level A); everything not edited stays byte-identical. `.pzfx` sources: table edits (cells, exclusions, titles, data sets added or removed) are written into the XML in place, everything else byte-identical, the Template included (refract.formats.pzfx_writer, E-pzfxsave). What a `.pzfx` cannot hold (tables, analyses, graphs or layouts made in Refract; edits to typed Multiple-variables columns) is refused with an offer to Save As `.prism` | done |
| Save As (Ctrl+Shift+S) | As Save, to a new path. A `.pzfx` source can be saved as `.pzfx` or `.prism`; `.prism` converts it (a new bundle: every data table, its excluded values, display decimals and Multiple-variables types, and the first info sheet), after a confirmation that lists what stays behind (the Template's graphs, analyses and layouts; further info sheets). The `.pzfx` is not changed (E-pzfxconvert) | done |
| Export graph | The shown graph as PDF, SVG or PNG (300 dpi) | done |
| Unsaved changes on close or open | Ask to save, discard or cancel | done |
| Recent files | Up to 8, on the start page and under File ▸ Open Recent | done |
| Close (Ctrl+W) | Back to the start page, asking to save first | done |
| Open from the system | Finder's Open With / a document dropped on the Dock icon (file-open events, also the one that launches the app), a path on the command line (Windows Open with); Refract is listed as an alternative handler only, never the default (PLAN phase 7, E-package) | done |

## 3. Sheet views

### 3.1 Data table
- A grid with a two-row header: the data-set (column group) title once over all its subcolumns, the subcolumn labels below. Subcolumn labels follow the table's data format: `Y1, Y2, …` for replicates, `Mean, SD, N` and the like for entered statistics, `X` for X columns. **done**
- Optional first columns: row titles, then X. Rows numbered from 1 on the left. **done**
- Excluded values are shown in blue italics. **done**
- Cells can be edited; each edit is one undoable step. Text is stored as typed, never routed through floats (document model rule). **done**
- Changing a table marks the graphs and analyses that use it as out of date (§5). **done**
- Copy, cut and paste a tab-separated block (as spreadsheets exchange it), starting at the current cell; values beyond the last column are left out and reported. Clear the selection with Delete or Backspace. **done**
- Insert rows above or below the selection, delete the selected rows. Excluded marks and stored cell formatting move with their rows. **done**
- Exclude and include the selected values (Ctrl+Shift+E; Y columns only). They are saved the way Prism stores them. **done**
- All of these are in the right-click menu and the Table menu; each is one undo step. **done**
- Insert a data set after the selection (Ctrl+Shift+D), delete the selected data sets (one stays), rename a data set (double-click its header), rename the table (Table ▸ Rename Table). Each is one undo step; analyses keep the data sets they read when columns move. Saved into existing bundles as well (new data/sets entries, removed ones deleted, sheet and document titles; verified in Prism, E-structure). Not yet for nested tables. **done**

### 3.2 Info sheet
Constants as a two-column table (name, value) and the notes text below. Read-only for now. **done**

### 3.3 Results
- A bar on top names the analysis and the data sets it reads, says whether the values shown are current, and has Change Parameters. **done**
- Results laid out for reading (refract.stats.report), one tab per page: Summary (what was analysed, then the tests), and tables where the results have that shape: the ANOVA table, multiple comparisons (one row per pair), data sets side by side (descriptive statistics, per-data-set tests and fits), one row per item (multiple t tests, hazard ratios). **done**
  - Numbers use the analysis's significant digits (output settings, 4 by default); P values its P value style (GP: 4 decimals, `<0.0001`, ns/*/**/***/****; APA, NEJM, full precision), with the summary and "Significant (P < α)?" after each main P value. Confidence intervals read "a to b"; F is given with its df as "F (DFn, DFd)", t as "t, df". **done**
  - Labels are our own wording built from the result keys, so every analysis class gets a page (the 5,414 stored results of the local corpus all lay out). Ctrl+C copies the selection as tab-separated text. **done**
  - "All values" keeps the complete tree of values. **done**
- For an analysis read from a file whose stored results are current, a switch on top chooses Prism's stored results or Refract's. **done**
- Analyses created in Refract: Refract's results, computed from the current data. **done**
- Analyses read from a file, while their data and parameters are unchanged: Prism's stored results and result tables, Refract's recomputation, and a Compare tab listing every value both have (stored, Refract, agreement within 1e-6; "only differences" filter). Once the data or parameters change, only Refract's recomputed results are shown. **done**
- The analysis's parameters are listed (class, inputs). **done**
- Hand-tuned pages per analysis (order and wording of the main rows), and results exported to a file. **planned**

### 3.4 Graph
- The graph drawn by `refract.render`, centred on a white US Letter page (portrait; landscape when the graph is too wide), as a graph sheet shows it; exports and Copy Graph hold the graph alone. A zoom bar offers Fit (the whole page) and 50–200 %, and shows the graph's and the page's size in inches. **done**
- Text objects (refract.render.qt.text_items): the graph title, axis titles, legend entries, significance labels, texts placed in Prism, text boxes added in Refract, and the tick-label groups. A click selects one (dashed box); dragging moves it; a double-click (or Return) types over it in place, Return keeps and Escape leaves the text; Delete empties a title or removes a text box. The toolbar's Text group shows and changes the selected text's font, size, bold, italic and underline. Graph ▸ Add Text puts a text box in the middle of the plot, open for typing. Every change is one undo step, stored as overrides (formatting "texts", "notes"); the graph title's and axis titles' words and sizes go to the keys that are written for Prism, the rest is listed in the compatibility report. **done**
- Every graph object on its own (refract.render.qt.object_at / object_box; refract.ui.object_panel): a click on a bar, box or symbol selects its data set ("set.<i>"), on a significance bracket's line the bracket ("bracket.<j>", moved with its label), on a drawn object that object ("shape.<n>"). The Format panel beside the graph shows the selection's settings - a data set's fill, hatch pattern (formatting.PATTERNS) and its colour, border colour and width, error-bar colour and width, symbol and line; a bracket's line colour and width; a drawn object's line colour, width, dashes and fill; a text's colour and size; with nothing selected the background, plotting area and axis colours. The Draw tools draw lines, arrows, rectangles and ellipses by dragging (Shift: 45° steps, squares, circles); a drawn object moves by dragging, each end by its handle, Delete removes it. Stored as formatting "sets", "texts" ("bracket.<j>") and "shapes"; written for Prism: colours, widths, Prism's 19 hatch patterns (refract.formats.graph_patch), drawn objects and text boxes as Prism's own objects (refract.formats.graph_objects); dashes, text-box fonts and bracket changes are listed in the compatibility report. Objects drawn in Prism (lines, arrows, rectangles, ellipses, framed text boxes) are drawn by Refract from the file. **done**
- Phase 8 editing (2026-11-16): **right-click** any object (refract.ui.context_menu): a bar - Format This Bar (its own fill, pattern, pattern colour, border colour and thickness: formatting SET "bars" {"<k>": ...}, drawn by Refract only), Format Entire Data Set, Format All Data Sets (symbol colour, shape and size; fill colour; Fill Pattern with a swatch of every pattern; pattern colour; border colour and thickness; error bar colour and thickness; line colour and thickness; items that do not apply are greyed), Reset; a bracket (line colour and thickness, Delete); a drawn object; a text (colour, size, bold, italic, edit, delete); the graph (background, plotting area, axis colours); and Format Graph, Format Axes, Color Scheme and Draw. The Format panel's pattern list shows the same swatches. **Brackets placed in Prism** ("abr.<annotation>") are selected, moved, stretched by their end handles, recoloured and hidden like Refract's own significance brackets ("bracket.<j>", whose ends now stretch too: texts "dl", "dr"). **Draw menu** (menu bar) and the toolbar's palette: Shapes (ellipse, circle, rectangle, square, rounded rectangle, elbow connector, elbow arrow), Lines (line, arrow, double arrow, line with end bars, line with an end bar, brackets with legs down or up, square brackets), Lines with text (each line kind with a text, starting "*": the significance bracket drawn by hand); refract.render.shape_kinds makes every kind from Prism's line, arrow, rectangle and ellipse, so Prism shows them too (a rounded rectangle as a rectangle; a line's text as a text box). **Colours** (refract.ui.color_menu): every colour button and menu offers the graph's colour scheme first (formatting "scheme", set by Color Scheme), then every other scheme's colours, then a custom colour. Objects and texts beyond the graph's box (a drawn bracket's text above the title, objects placed in Prism, a wide title) are drawn on the canvas, copied and exported too (refract.render.qt.overflow). The toolbar's groups wrap onto further rows instead of hiding behind an overflow button. A selected bracket has four handles: its ends (wider, narrower) and the tips of its legs (each leg longer or shorter; the nearest handle is taken). Shift- or Cmd-click chooses several data sets; the Format panel and Format Selected Data Sets apply to each, one undo step. **done**
- Color Scheme (toolbar and Graph menu): built-in schemes (our own picks, Misty Blue and Peach from the user's colour picture, colour-blind-safe palettes, samples of the viridis family), the five recently used; RColorBrewer (submenus Qualitative, Sequential, Diverging) and ggsci (Journals, Science tools, Universities and UI, TV and film, Continuous palettes split by family) as submenus; Your Schemes (submenu): the user's own, New Color Scheme (from the shown graph's colours), Customize an Existing Scheme (start from any scheme), Import Colors (a file of hex codes: a list, CSS, an R vector, a GIMP palette), Edit (rename, change, reorder) and Delete; the scheme dialog also pastes hex codes from text. Set the Default Color Scheme (new Refract graphs start with it), and the background, plotting area and axis colours. **done**
- Graph types (Graph ▸ Change Graph Type, Ctrl+Shift+T; the graph sheet's bar): a new data table comes with its graph sheet, but the graph waits for its type; the first time the sheet is shown (and from New Graph) the Change Graph Type window opens. It offers the families the table can be drawn as (an XY table also as columns, its data sets' values pooled, or grouped, its X values as rows; a grouped table also as columns; and so on), the family's types in tabs as fixed icons (our own line drawings in the window's palette, so they follow the light or dark theme; only the preview shows the table's data), the type's Plot option (mean with SD / SEM / 95% CI, mean only, median with range or IQR; box whiskers Tukey, min-max, percentiles; floating bars' line; survival fractions or percents; Multiple-variables X, Y, colour and size variables), "make it the default for this kind of table", and a preview of this table as that type, redrawn at every change. 97 types (refract.render.graph_types):
  - XY: points, points and line, each replicate, replicates with a line through the means, line only, each replicate as its own line, bars at each X, filled area.
  - Column: scatter, scatter with bar, before-after (with or without bars), floating bars, box and whiskers, violin, bars, symbols, connected symbols; most also horizontal.
  - Grouped: interleaved or separated (grouped by data set) scatter, bars with values, bars and symbols; each replicate, replicates joined across rows; stacked bars; heat maps in eight colour maps with a colour bar; three-way graphs in two panels; interleaved or separated box, floating bars and violins; horizontal versions.
  - Contingency: interleaved, separated, stacked and 100 % stacked bars, also horizontal.
  - Survival: staircases with or without censor ticks or with a symbol at each step, points; the same as deaths (rising); fractions or percents; error bars none, SE (Greenwood) or the 95% CI (log(-log), as the survival analysis), drawn as dotted bounds on staircases and as error bars on points.
  - Parts of whole: pie, donut, stacked bar (upright or horizontal), waffle.
  - Nested: scatter, scatter with bars, bars, floating bars, boxes and violins by subgroup.
  - Multiple variables: bubble plot, two-variable scatter, heat map of the variables (z scores), and scatter, means, bars (with or without the values), boxes, violins or before-after lines (a line per group of a third variable, optionally over bars) of one variable by the categories of another.
  - Three-way graphs list each pairing once in the legend.

  Choosing a type updates the window's commands at once. Types Prism's own style does not reproduce are written for Prism as its default graph of the table, and the compatibility report says so. **done**
- Empty axis titles show a faint "X title" / "Y title" on screen (never in exports or prints): double-click to type one. Horizontal graphs' title, axis titles and legend entries are text objects too.
- Estimation plots from Prism files follow edits of their analysis's data: the groups, the differences and the confidence interval are recomputed (paired; unpaired with the pooled SD; Welch). **done**
- Moving on the page: click the graph (or drag a box over it) to select it whole and drag it anywhere on the page; arrow keys nudge the selection (1 pt, 10 with Shift). A first click on the legend takes the whole legend (moved and styled together), the next click one entry. While dragging, the graph is redrawn with the text where it will land. **done**
- Zoom and pan: pinch on the trackpad or Ctrl/Cmd + wheel zooms about the pointer (10–800 %, shown in the zoom box); scrolling pans; Option-drag or the middle button drags the page. **done**
- Magic (toolbar, Graph menu, Ctrl+Shift+M): step 1 shows thumbnails of the project's other graphs, or of the saved style templates previewed on this graph; step 2 chooses what to copy (colours and symbols, fonts and text sizes, axis lengths, axis ranges, titles' words, legend, background colours) and whether to change this graph or every graph of its kind. Graph ▸ Save Style as Template keeps the shown graph's look (without its words and ranges) for later. One undo step (refract.render.magic). **done**
- Estimation plots of t tests (from Prism files): the two groups (paired: each subject's values joined), dotted lines at both means, and the difference with its mean and confidence interval on a right axis whose zero is the first group's mean (E-estimation). **done**
- Graphs whose data cannot be resolved show the reason instead. **done**
- Graphs made in Refract (listed under Graphs after Prism's): one is made with every new table, as Prism does, and Analysis ▸ New Graph of This Table (Ctrl+G) adds more. They are drawn from the table's current data in Prism's default style for the kind (column tables as bars with the points), with a bar for style (default, bars, mean and error as symbols), error bars (SD, SEM) and stars. **done**
- Significance stars: brackets between the compared columns (column tables) or the compared bars of a row (grouped tables), from the table's first analysis with pairwise comparisons; labels by the GP style (ns hidden unless chosen); stacked so that no bracket crosses another or the data, and the Y axis range includes them. They follow edits of the data and the analysis's parameters. **done**
- Refract's graphs are saved in the bundle's private entry `x-refract/graphs.json` (their table named by sheet uid). Prism keeps the entry when it re-saves (E5, E-acceptance) but does not show these graphs: writing them as Prism graphs is phase 6. **done**
- Double-click an object of a graph to format it (qt.hit on the laid-out page): a data set's bars, symbols or legend entry open Format Graph on that data set, an axis Format Axes on that axis, the title or anything else Format Graph's Graph page. **done**
- Graphs from Prism files are formatted with the same dialogs (PLAN §2.4 level A): Refract shows them with the overrides applied, and the save patches the graph's own PCFF, always from the blob as opened, with what is verified (axis range, tick, log10, data-set colours); the rest goes in the compatibility report. Only the formatted graphs are rewritten; undoing every change and saving restores their original bytes (E-inplace). **done**
- Format Graph (Ctrl+Shift+G): per data set fill, border/symbol/line colour, symbol shape and size, the individual values shown or not, connecting line (XY), reset to default; the graph's title, title size, font, legend, axis lengths. Format Axes (Ctrl+Shift+X): per axis title, title and label sizes, minimum, maximum and major tick (blank: automatic, shown as a hint), log10 scale, minor ticks, category label angle. The dialogs show the values in effect and record only what changes, as overrides stored with the graph (refract.render.formatting); each OK is one undo step. **done**
- Log10 axes in the renderer: major ticks at the powers of ten, 2–9 as minor ticks, automatic range in whole decades; significance brackets are stacked in decades there. **done**

### 3.5 Layout
- Prism layouts: a preview of the graphs placed on it, drawn by Refract where Prism places them (refract.render.prism_layout); other objects (pictures, texts, tables) are listed as not drawn. Export works; Copy as Refract Layout makes an editable copy with the same graphs in the same places. **done**
- Refract layouts (Graph ▸ New Layout, Ctrl+L, with the shown graph): a page (Letter or A4, portrait or landscape) of graphs, each fitted to its box and centred. Add a graph (any of the project's, Prism's or Refract's), arrange in a grid of N columns, drag to move, drag the corner handle to resize, Delete or Remove to take one off; every change is one undo step. The graphs follow their data, analyses and formats. Exported as PDF, SVG or PNG; saved in `x-refract/layouts.json` (graphs named by sheet uid or Refract graph uid), which Prism keeps when it re-saves. **done**
- Text boxes and pictures on Refract layouts; Prism layouts' own text and drawing objects. **planned**

## 4. Editing and undo
- One undo stack per project; undo and redo through Ctrl+Z / Ctrl+Shift+Z and the toolbar. **done**
- Every edit to a model object goes through an undo command, so undo always restores the stored text exactly. **done**

## 5. Linked updates
- A data edit invalidates the graphs that plot that table. On their next display they are rebuilt from the edited data, with axes autoscaled by Prism's rules instead of the ranges cached in the file. **done**
- Analyses that use the table are recomputed and their result sheets refreshed. **done**

## 6. Dialogs
| Dialog | Behaviour | Status |
|---|---|---|
| Analyze (Ctrl+Shift+A) | Analyses grouped by table kind; those that do not apply to the table shown are greyed with the kind they need. The data sets to analyse are ticked; OK is enabled only for a count the analysis accepts. Works from a data table or from a result sheet (its table) | done |
| Parameters | The analysis's options on tabs (Options; Multiple comparisons for ANOVAs). The method list follows the design and comparison chosen; the control column is enabled only for comparisons with a control | done |
| Change Parameters (Ctrl+Shift+P) | The same dialog, filled from the analysis's stored parameters; for new and stored analyses alike; one undo step | done |
| New Data Table (Ctrl+T); the Welcome window for a new project | The eight table kinds listed on the left (with Open a File… for a new project). On the right: a sentence on what the kind is for, a drawn preview of its table layout and a small graph (our own), start empty or with our own sample data, then the kind's options: XY: X as numbers (X errors, dates and elapsed times shown, not available yet) and Y as one value, N replicates side by side, or mean and error computed elsewhere (Mean, SD and N; Mean and SD; Mean and SEM); Column: replicates stacked in columns, or paired / repeated measures one subject per row, or error values; Grouped: one value, N replicates, or error values; Survival: times as numbers (start and end dates not yet); Nested: subcolumns per group; the others start empty. The number of data sets and the table name below. Create puts the table after the other data tables, one undo step; with no project open a new one is started | done |
| Format Graph, Format Axes, Preferences | | planned |

Analyses offered so far (refract.stats.catalog): descriptive statistics, t and nonparametric two-column tests, one-way ANOVA family with post tests, one-sample tests, normality tests; two-way ANOVA family with post tests, multiple t tests; simple linear regression, correlation; survival; contingency tests. New analyses start from `refract/stats/defaults.json` (parameter sets Prism wrote in our probe documents, data-set names removed; tools/make_defaults.py).

### Saving Refract's graphs for Prism (PLAN §2.4 level B)
- On save, each Refract graph of a column, grouped or XY table is also written as a real Prism graph: a seed graph Prism made (refract.formats.seeds; a local file, not shipped) is copied in with its ids renumbered and bound to the table (refract.formats.graph_transplant), then patched with what is verified: Y (and XY's X) range, major tick and log10, data-set fill and line colours (refract.formats.graph_patch). Prism draws it from the table's data, adds plots for data sets beyond the seed's and drops the seed's extra ones (E-seed, E-writeback). **done**
- The Prism copy is rewritten only when the graph's options, title or data sets change (Prism redraws data edits by itself); it is removed when its Refract graph is. Reopened, it is listed once, as the Refract graph. **done**
- Compatibility report (File ▸ Prism Compatibility Report; summarised in the status bar after a save): what Prism shows differently, per graph: styles other than Prism's default, SEM error bars, significance stars, symbols, axis titles and text sizes, colours of data sets beyond the seed's, graphs of other kinds (survival, pie) not written. **done**
- Survival and parts-of-whole graphs, other styles (no seed yet), stars as Prism objects. **planned**

### Saving new tables
- A new table is inserted into the bundle on save (bundle_builder.insert_table, cells written as typed); afterwards its edits are saved like any other table's. A table undone after a save is removed from the bundle on the next save, and inserted afresh if redone. Verified in Prism (E-new-tables). **done**

### Saving analyses
- A new analysis is added to the bundle with its parameters and empty results; Prism computes it when it opens the file (E-ui-analyses: all 22 test analyses open and agree with Refract). An analysis removed by undo after a save is removed from the bundle on the next save. **done**
- Changed parameters of a stored analysis are written into its `parameters.json` and its stored results emptied (Prism recomputes on open; verified). **done**

## 7. Keyboard
| Keys | Action |
|---|---|
| Ctrl+N / Ctrl+T | New project / New data table |
| Ctrl+O / Ctrl+S / Ctrl+Shift+S | Open / Save / Save As |
| Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) | Undo / Redo |
| Ctrl+E | Export the shown graph |
| Ctrl+W | Close the project |
| Ctrl+C / Ctrl+X / Ctrl+V, Delete | Copy / cut / paste / clear cells |
| Ctrl+Shift+I, Ctrl+Shift+Backspace | Insert row above / delete rows |
| Ctrl+Shift+E | Exclude values |
| Ctrl+Shift+A / Ctrl+Shift+P | Analyze / Change parameters |
| Ctrl+Shift+D / Ctrl+G | Insert data set / New graph of this table |
| Ctrl+Shift+G / Ctrl+Shift+X | Format graph / Format axes |
| Ctrl+L | New layout |
| Ctrl+Page Up / Page Down | Previous / next sheet in the navigator |

(Ctrl is Cmd on macOS.)

## 8. Acceptance scenario (PLAN §4, phase 4)
New Grouped table → paste data → two-way ANOVA with Tukey → the graph shows significance stars → export PDF → save .prism → reopen: the same tables, analysis and graph. Driven through the window in `tests/test_acceptance.py`; the saved file opened in Prism (E-acceptance): table unchanged, the analysis computed by Prism and equal to Refract's in all 101 values, the private graph entry kept and still naming its table. **done**
