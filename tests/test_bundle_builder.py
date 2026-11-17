"""Builder output must be a valid ZIP our lossless reader round-trips, with
the column layout prismbinder documents (row titles, X, then data sets)."""

import io
import json
import zipfile

from refract.formats.bundle_builder import (
    BundleBuilder,
    DataSet,
    TableSpec,
    decimals_of,
    set_seed,
)
from refract.formats.zipio import ZipArchive


def _build():
    set_seed(1)
    b = BundleBuilder(full_ui=True)
    b.add_info()
    b.add_table(TableSpec("g", "grouped", "y_replicates",
                          [DataSet("A", [[1.5, 2.0], [3.25, None], [5.0, 6.0]])], row_titles=["r1", "r2"], replicates=3))
    b.add_table(TableSpec("xy", "xy", "y_single", [DataSet("Y", [[0.1, 0.2]])], x_title="X", x_values=[1, 2]))
    return b.build().to_bytes()


def test_builder_zip_valid_and_roundtrips():
    raw = _build()
    assert zipfile.ZipFile(io.BytesIO(raw)).testzip() is None
    assert ZipArchive.from_bytes(raw).to_bytes() == raw


def test_builder_is_deterministic_apart_from_timestamps():
    a, b = ZipArchive.from_bytes(_build()), ZipArchive.from_bytes(_build())
    assert a.names() == b.names()


def test_csv_column_order_and_decimals():
    z = ZipArchive.from_bytes(_build())
    doc = json.loads(z.read("document.json"))
    sheets = [json.loads(z.read(f"data/sheets/{u}/sheet.json")) for u in doc["sheets"]["data"]]
    g, xy = sheets
    assert z.read(f"data/tables/{g['table']['uid']}/data.csv") == b"r1,1.5,3.25,5\nr2,2,,6\n"
    assert z.read(f"data/tables/{xy['table']['uid']}/data.csv") == b"1,0.1\n2,0.2\n"
    ds = json.loads(z.read(f"data/sets/{g['table']['dataSets'][0]}.json"))
    assert ds["replicate ranges"][0]["replicate"]["decimalsLength"] == 2
    assert decimals_of([1, 2.5, 0.125, None, "x"]) == 3


def test_fmt_cell_numpy_scalars():
    import numpy as np

    from refract.formats.bundle_builder import fmt_cell

    # numpy 2 reprs floats as "np.float64(...)"; Prism then reads the cell as text
    assert fmt_cell(np.float64(2.158)) == "2.158"
    assert fmt_cell(np.float64(3.0)) == "3"
    assert fmt_cell(np.int64(4)) == "4"
