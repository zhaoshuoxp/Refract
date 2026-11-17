"""`refract selftest`: a quick end-to-end check of an installation, mainly the
packaged app (tools/packaging): it runs NumPy/SciPy statistics, Qt drawing
offscreen, saving and reopening a .prism file. Only generated sample tables
are used. Prints one line per step (also written to selftest.txt in the
output folder: a windowed Windows build has no console); exit status 0 when
all pass."""

from __future__ import annotations

import os
import tempfile
import time


def run(keep: str | None = None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    t0 = time.time()
    failures: list[str] = []
    lines: list[str] = []
    out = keep or tempfile.mkdtemp(prefix="refract-selftest-")
    os.makedirs(out, exist_ok=True)

    def say(line: str) -> None:
        lines.append(line)
        print(line, flush=True)

    def step(name, fn):
        try:
            res = fn()
            say(f"  ok    {name}{': ' + res if res else ''}")
        except Exception as e:  # noqa: BLE001 - report every failure and go on
            failures.append(name)
            say(f"  FAIL  {name}: {type(e).__name__}: {e}")

    from . import about
    say(f"{about.APP_NAME} {about.VERSION} self-test")

    from .render import qt
    step("Qt", lambda: (qt.ensure_app(), "offscreen platform")[1])

    from .model import templates as T
    from .stats import catalog
    from .ui.document import Document

    doc = Document.new()
    for k in T.KINDS:
        step(f"table {k.key}", lambda k=k: (doc.add_table(T.make(k.key, f"Sample {k.label}", sample=True)), "")[1])
    tables = {t.kind: t for t in doc.project.tables}

    def analyse(kind, key):
        choice = catalog.by_key(key)
        a = doc.add_analysis(tables[kind], choice, catalog.initial(choice))
        res = doc.results(a)
        if not res:
            raise RuntimeError("no results")
        return f"{len(res)} result groups"

    step("one-way ANOVA (column)", lambda: analyse("column", "one_way"))
    step("two-way ANOVA (grouped)", lambda: analyse("grouped", "two_way"))
    step("linear regression (xy)", lambda: analyse("xy", "linear"))
    step("survival (survival)", lambda: analyse("survival", "survival"))

    from .render import native

    def draw():
        n = 0
        for i, ng in enumerate(doc.project.native_graphs):
            g = native.graph(doc.project, ng, doc.results, doc.source_of)
            qt.to_pdf(g, os.path.join(out, f"graph_{i + 1}.pdf"))
            qt.to_png(g, os.path.join(out, f"graph_{i + 1}.png"))
            n += 1
        return f"{n} graphs as PDF and PNG"

    step("draw graphs", draw)
    path = os.path.join(out, "selftest.prism")
    step("save .prism", lambda: (doc.save(path), f"{os.path.getsize(path)} bytes")[1])

    def reopen():
        back = Document.open(path)
        if len(back.project.tables) != len(doc.project.tables):
            raise RuntimeError(f"{len(back.project.tables)} tables read back, {len(doc.project.tables)} saved")
        return f"{len(back.project.tables)} tables, {len(back.project.analyses)} analyses, " \
               f"{len(back.project.graphs)} graphs"

    step("reopen", reopen)
    say(f"{'passed' if not failures else 'FAILED: ' + ', '.join(failures)} in {time.time() - t0:.1f} s"
        f" (files in {out})")
    with open(os.path.join(out, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 1 if failures else 0
