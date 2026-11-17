"""Prism 11 default graph style, in points, measured on the vector PDFs Prism
exported from its own default graphs (corpus/manual/batch5_samples.prism:
XY, column, grouped and survival tables created from sample data;
docs/format/findings.md, phase 3 batch 2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    # axes
    # nominal 3 in / 2 in; Prism's drawn lengths are ~0.12 pt short (measured)
    xy_x_length: float = 215.87  # XY / survival
    y_length: float = 143.91  # every family
    grouped_x_length: float = 143.89  # grouped
    column_slot: float = 28.73  # column: X length = slot * (columns + 1/3) (95.76 for 3)
    axis_width: float = 1.44
    tick_length: float = 5.4  # outward
    minor_tick_length: float = 2.7  # survival
    # text (Arial; bold except the legend)
    tick_label_size: float = 11.0
    axis_title_size: float = 12.0
    title_size: float = 14.0
    legend_size: float = 12.0
    y_label_gap: float = 3.1  # tick end -> right of the Y tick labels
    x_label_gap: float = 3.0  # tick end -> top of the X tick labels' line box
    x_title_gap: float = 4.0  # X tick labels' line box -> X title line box
    y_title_gap: float = 5.5  # Y title line box -> left of the Y tick labels (space kept when empty)
    title_gap: float = 3.15  # title line box -> topmost element (Y axis end or the top tick label's line box)
    label_angle: float = 45.0  # column / grouped category labels
    # legend
    legend_symbol_dx: float = 40.5  # end of the X axis -> centre of the legend symbol
    legend_text_dx: float = 16.3  # symbol centre -> text
    legend_first_baseline: float = 14.0  # below the top of the Y axis
    legend_pitch: float = 20.15
    # page
    margin: float = 5.2
    # data
    symbol_size: float = 6.32  # circle diameter (square side 5.75)
    column_symbol_size: float = 4.73
    error_width: float = 0.72
    xy_cap_width: float = 5.76
    bar_cap_fraction: float = 0.6  # of the bar width
    bar_border: float = 2.16
    mean_line_fraction: float = 2 / 3  # column scatter: of a slot
    grouped_bar_fraction: float = 0.556  # bar width / bar pitch
    grouped_gap: float = 2 / 3  # between groups, in bar pitches
    grouped_end: float = 1 / 6  # at both ends, in bar pitches
    censor_width: float = 1.44  # survival: censor ticks
    censor_height: float = 2.88
    legend_line: float = 15.35  # survival legend: line length
    scatter_step: float = 0.91  # column scatter: horizontal step, fraction of the symbol size


DEFAULT = Style()

# fills of grouped bars, by data set: Prism 11's new graphs (E-compare: its PDF and PNG exports of
# Refract's graphs fill the second data set 160,160,164; older corpus files have 176,176,179)
BAR_FILLS = [(0, 0, 0, 128), (160, 160, 164, 255)]
# grouped bars without the values: Prism draws the second data set darker (E-compare, its export of
# Refract's grouped "bars only" graph: 143,143,147 where bars with the values get 160,160,164)
BARS_ONLY_FILLS = [(0, 0, 0, 128), (143, 143, 147, 255)]
