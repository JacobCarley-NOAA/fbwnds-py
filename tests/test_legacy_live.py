"""Live comparison with the compiled Fortran program.

Skipped unless ``FBWNDGFS_LEGACY_DIR`` points at a build made by
``tests/legacy/build_legacy.sh``.  Each case generates fresh random fields,
runs both programs and requires identical output files.
"""

import datetime as dt

import pytest

import run_legacy
import synthetic
from fbwndgfs import run

pytestmark = [pytest.mark.legacy, pytest.mark.grib]

CASES = [
    # seed, grid, cycle, station list fixture, legacy_grid_dims, tenths
    (101, synthetic.LEGACY_SIZED, dt.datetime(2026, 1, 31, 0), "stress_stnlist", None, False),
    (102, synthetic.LEGACY_SIZED, dt.datetime(2028, 2, 29, 6), "stress_stnlist", None, False),
    (103, synthetic.LEGACY_SIZED, dt.datetime(2026, 12, 31, 12), "stress_stnlist", None, False),
    (104, synthetic.LEGACY_SIZED, dt.datetime(2026, 6, 30, 18), "stress_stnlist", None, False),
    (105, synthetic.LEGACY_SIZED, dt.datetime(2026, 7, 4, 12), "pacific_stnlist", None, False),
    (201, synthetic.QUARTER_DEGREE, dt.datetime(2026, 3, 9, 0), "pacific_stnlist", (1760, 880), False),
    (202, synthetic.QUARTER_DEGREE, dt.datetime(2026, 9, 30, 18), "pacific_stnlist", (1760, 880), False),
    # fields with 0.1 precision, packed with decimal scale 1 like real GFS output
    (301, synthetic.LEGACY_SIZED, dt.datetime(2026, 5, 5, 12), "stress_stnlist", None, True),
    (302, synthetic.QUARTER_DEGREE, dt.datetime(2026, 5, 5, 6), "pacific_stnlist", (1760, 880), True),
]


@pytest.mark.parametrize(
    "seed, spec, cycle, stations, dims, tenths", CASES, ids=[f"seed{c[0]}" for c in CASES]
)
def test_python_matches_fortran(seed, spec, cycle, stations, dims, tenths, tmp_path, request):
    station_list = request.getfixturevalue(stations)
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    reference = run_legacy.run_legacy(str(legacy_dir), station_list, seed, spec, cycle, tenths=tenths)

    grib_dir = tmp_path / "grib2"
    grib_dir.mkdir()
    files = synthetic.write_grib2(str(grib_dir), seed, spec, cycle, tenths=tenths)
    tran = run(station_list, files, transmit_time=run_legacy.transmit_time_of(reference), legacy_grid_dims=dims)
    assert tran == reference
