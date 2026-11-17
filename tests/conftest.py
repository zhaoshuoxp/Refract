"""A test that needs a file of the local corpus (corpus/ is git-ignored: Prism-made
probes and parameter seeds that are not distributed) is skipped, not failed, in a
checkout without it."""

from __future__ import annotations

import os

import pytest

CORPUS = os.sep + "corpus" + os.sep


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    exc = call.excinfo
    if report.failed and exc is not None and exc.errisinstance(FileNotFoundError) and CORPUS in str(exc.value):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0, "Skipped: needs the local corpus (not distributed)")
