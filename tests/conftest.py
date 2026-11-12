"""Shared fixtures.

Test tiers
----------
* plain unit tests need only NumPy;
* tests marked ``grib`` need grib2io (NCEPLIBS-g2c) and are skipped without it;
* tests marked ``legacy`` run the compiled Fortran program and are skipped
  unless ``FBWNDGFS_LEGACY_DIR`` points at the build made by
  ``tests/legacy/build_legacy.sh``.
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "legacy"))

DATA = os.path.join(HERE, "data")
PACIFIC_STNLIST = os.path.join(os.path.dirname(HERE), "parm", "fbwnd_pacific.stnlist")
STRESS_STNLIST = os.path.join(DATA, "stress.stnlist")

try:
    import grib2io  # noqa: F401

    HAVE_GRIB2IO = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_GRIB2IO = False


def pytest_collection_modifyitems(config, items):
    import run_legacy

    skip_grib = pytest.mark.skip(reason="grib2io is not installed")
    skip_legacy = pytest.mark.skip(reason="FBWNDGFS_LEGACY_DIR not set (Fortran reference not built)")
    have_legacy = run_legacy.legacy_dir() is not None
    for item in items:
        if "grib" in item.keywords and not HAVE_GRIB2IO:
            item.add_marker(skip_grib)
        if "legacy" in item.keywords and not (have_legacy and HAVE_GRIB2IO):
            item.add_marker(skip_legacy)


@pytest.fixture(scope="session")
def pacific_stnlist() -> str:
    return PACIFIC_STNLIST


@pytest.fixture(scope="session")
def stress_stnlist() -> str:
    return STRESS_STNLIST
