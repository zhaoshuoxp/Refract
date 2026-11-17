# Refract User Guide

Refract makes scientific graphs and runs the statistics behind them. It opens and saves `.prism` project files and `.pzfx` files, so you can share projects with colleagues who use Prism.

## Projects and sheets

A project holds **data tables**, **info sheets**, **results** (one sheet per analysis), **graphs** and **layouts**. The navigator on the left lists them by section. Click a sheet to show it. View ▸ Group Sheets by Family lists each data table with the analyses and graphs that use it.

- **New project** (Ctrl+N) starts with a data table of the kind you choose.
- **Open** (Ctrl+O) reads `.prism` and `.pzfx` files. Anything Refract could not read is reported in the status bar.
- **Save** (Ctrl+S) writes the file back in its own format. Parts of an existing file you did not change are written back exactly as they were.
- **Save As** (Ctrl+Shift+S) can also turn a `.pzfx` file into a `.prism` file (see Working with Prism).
- **Open Recent** lists the last eight files.

On macOS you can also open a project from Finder with **Open With ▸ Refract**. Installing Refract does not change which application opens these files by default.

## Data tables

Choose the table kind from File ▸ New Data Table (Ctrl+T). The window shows what each kind is for, a sketch of its table and a small graph, and the kind's options: for XY, Column and Grouped tables, whether you enter one value per point, several replicates side by side, or means with their error (SD and N, SD, or SEM) computed elsewhere; for Nested tables, how many subcolumns each group has. You can start with an empty table or with sample data.

| Kind | Use it for |
|---|---|
| XY | Y values measured at numeric X values: curves, regression, correlation |
| Column | One group per column: t tests, one-way ANOVA, descriptive statistics |
| Grouped | Two factors (rows and data sets): two-way ANOVA, multiple t tests |
| Contingency | Counts of subjects per group and outcome |
| Survival | Time to event per subject, 1 for an event and 0 for censored |
| Parts of whole | Values that add up to a total: pie and donut charts |
| Multiple variables | One row per observation, one column per variable |
| Nested | Groups with subgroups |

Type into the grid or paste a block copied from a spreadsheet. Right-click a cell for row and data-set commands. To leave a value out of analyses and graphs without deleting it, select it and press Ctrl+Shift+E; excluded values are shown in blue italics. Every edit can be undone with Ctrl+Z.

## Analyses

With a data table shown, choose Analysis ▸ Analyze (Ctrl+Shift+A). Analyses that do not fit the table are greyed out. Tick the data sets to analyse, set the options and click OK. The results sheet updates by itself when the data change. Change Parameters (Ctrl+Shift+P) reopens the options.

For an analysis read from a Prism file, the results sheet can show the values Prism stored, Refract's own computation, and a comparison of the two.

## Graphs

Every new table comes with a graph sheet. The first time you open it, Refract asks how to graph the table: choose the graph family, then the kind of graph from the pictures (bars, scatter, box and whiskers, violins, heat maps, stacked bars and more), and what it shows (for example mean with SD, or median with range). The preview shows your own data as you choose. Tick "Make … the default" to start future tables of that kind with your choice. Graph ▸ Change Graph Type (Ctrl+Shift+T) changes it later; Graph ▸ New Graph of This Table (Ctrl+G) adds another graph.

- **Format Graph** (Ctrl+Shift+G) sets the colours, symbols, error bars, style (points, bars, means), title, font, legend and size.
- **Format Axes** (Ctrl+Shift+X) sets the range, ticks, log scale, titles and label angle of each axis.
- Double-click a part of a graph to format that part.
- Significance stars come from the table's first analysis with pairwise comparisons.
- **Export** (Ctrl+E) saves the shown graph as PDF, SVG or PNG (300 dpi). Edit ▸ Copy Graph puts it on the clipboard as a picture; File ▸ Print prints it.

A graph sheet shows the graph on a Letter page, as it will print. Pinch on the trackpad (or hold Ctrl/Cmd and scroll) to zoom; scroll to move around; hold Option and drag to move the page. Click the graph, or drag a box around it, to select it whole and drag it to another place on the page; the arrow keys nudge what is selected.

### Texts on the graph

Every text on a graph is an object you can work with directly: the title, the axis titles, the legend entries, the significance labels and P values, and text boxes.

- **Click** a text to select it (a dashed box appears). **Drag** it to move it; you see it move as you drag.
- The first click on the legend selects the whole legend; click again to select one entry.
- **Double-click** it, or press Return, to type over it. Return keeps the new text; Escape leaves it as it was.
- With a text selected, the **Text** group of the toolbar changes its font, size, bold, italic and underline (or use Ctrl+B, Ctrl+I, Ctrl+U).
- **Delete** removes a text box, or empties a title.
- **Graph ▸ Add Text** (the Draw group) adds a text box in the middle of the plot.

Clicking the tick labels selects all of them, to change their size and style.

### Every element of the graph: the Format panel

The **Format** panel on the right of a graph sheet shows the settings of whatever you selected, as in a slide editor:

- **A bar, a box or a symbol** (click it): its data set's fill colour, hatch pattern and pattern colour, border colour and width, error-bar colour and width, symbol shape, size and border, and its connecting line. **Reset to default** gives the data set back its default look.
- **A significance bracket** (click its line): its line colour and width. Drag it to move it together with its P value or stars; the label itself can still be moved, retyped and restyled on its own.
- **A text**: its colour and size (the Text group has the font and styles).
- **Nothing selected**: the graph's background, plotting area and axis colours.

The **Draw** group draws **lines, arrows, rectangles and ellipses**: choose the tool, then drag on the graph (hold Shift for straight 45° steps, squares and circles); Escape or a second click on the tool goes back to selecting. A drawn object is selected when it is drawn: drag it to move it, drag one of its round handles to move that end (or corner), set its line colour, width, dashes and (boxes, ellipses) fill in the panel, and press Delete to remove it.

Every change is one undo step. When the project is saved as a .prism file, Prism's graph gets them too: colours, border, error-bar and line widths, Prism's 19 hatch patterns, and the lines, arrows, rectangles, ellipses and text boxes you drew (as Prism's own drawing objects, which can be edited there). Dashed drawn lines, text boxes' fonts and moved or restyled significance brackets stay in Refract: the compatibility report lists them.

### Colors and Magic

- **Graph ▸ Color Scheme** colours the data sets from a scheme: built-in ones, colour-blind-safe ones, the palettes of the R packages RColorBrewer and ggsci (each in its own submenu), or your own (Your Schemes: make a new one, start from any existing scheme, import a file of hex codes such as #6F91B8, paste codes, edit or delete). Set the Default Color Scheme to start every new graph with it. The same menu sets the background, plotting area and axis colours.
- **Graph ▸ Magic** (Ctrl+Shift+M) makes this graph look like another one: pick a graph of the project or a saved template, then choose what to copy (colours, fonts, sizes, axis lengths, ranges, titles, legend, background), for this graph or every graph of its kind.
- **Graph ▸ Save Style as Template** keeps the shown graph's look, without its titles and ranges, so Magic can apply it to other graphs later, in any project.

## Layouts

Graph ▸ New Layout (Ctrl+L) places graphs on a Letter or A4 page. Drag a graph to move it and drag its corner to resize it. Layouts export like graphs.

## Working with Prism

When you save, Refract writes its own graphs of Column, Grouped, XY, Survival and Parts-of-whole tables as real Prism graphs. Your colleagues can open and edit them in Prism. File ▸ Prism Compatibility Report lists anything Prism will show differently, for example significance stars, which Prism does not add by itself.

Graphs that came from a Prism file keep their own formatting. Formatting you change in Refract is written back into them where that is supported, and the report lists the rest.

### .pzfx files

A `.pzfx` file keeps its graphs, analyses and layouts in a part only Prism can write. Refract saves your changes to its data tables (values, excluded values, titles, added data sets) into that file and leaves everything else as it was, so Prism redraws the graphs and recalculates the analyses from the new data when it opens the file.

Tables, analyses, graphs and layouts you make in Refract need a `.prism` file: Refract offers File ▸ Save As `.prism` when you save. The `.prism` file holds the data tables, the info sheet and everything made in Refract; the `.pzfx` file's own graphs, analyses and layouts are not carried over, and Refract tells you so before it saves. The `.pzfx` file itself is not changed.

## Privacy

Refract works offline. It sends nothing over the network and collects no usage data. The command `refract anonymize FILE OUT` clears account names and personal info-sheet fields before you share a file.

## Keyboard

| Keys | Action |
|---|---|
| Ctrl+N / Ctrl+T | New project / new data table |
| Ctrl+O / Ctrl+S / Ctrl+Shift+S | Open / save / save as |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo |
| Ctrl+E | Export the shown graph |
| Ctrl+Shift+A / Ctrl+Shift+P | Analyze / change parameters |
| Ctrl+G / Ctrl+L | New graph / new layout |
| Ctrl+Shift+G / Ctrl+Shift+X | Format graph / format axes |
| Ctrl+Page Up / Ctrl+Page Down | Previous / next sheet |

On macOS, Ctrl is the Cmd key.

## About Refract

Refract is an independent project. It is not affiliated with, endorsed by or sponsored by GraphPad Software, LLC or Dotmatics. GraphPad and Prism are trademarks of GraphPad Software, LLC; they are used here only to say which files Refract can open and save.

## License

Refract is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for details.

The license text and Refract's complete source code are included with the app, in its LICENSES/Refract folder.
