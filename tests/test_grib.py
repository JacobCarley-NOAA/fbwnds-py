"""GRIB2 input through grib2io, the command line, and the Fortran golden files."""

import datetime as dt
import os
import subprocess
import sys

import numpy as np
import pytest

import run_legacy
import synthetic
import fbwndgfs
from fbwndgfs import Grib2Source, interpolate_tau, read_station_list, run
from fbwndgfs.cli import main
from fbwndgfs.constants import LEVELS, TAUS, TMP, UGRD, VGRD
from fbwndgfs.errors import GribReadError, MissingFieldError

pytestmark = pytest.mark.grib

CYCLE = dt.datetime(2026, 11, 11, 6)
SPEC = synthetic.ONE_DEGREE
SEED = 7


@pytest.fixture(scope="module")
def grib_files(tmp_path_factory):
    return synthetic.write_grib2(str(tmp_path_factory.mktemp("grib")), SEED, SPEC, CYCLE)


def test_files_are_split_like_pres_a_and_pres_b(grib_files):
    assert sorted(grib_files) == [6, 12, 24]
    assert [os.path.basename(p) for p in grib_files[6]] == [
        "gfs.t06z.pres_a.f006.grib2",
        "gfs.t06z.pres_b.f006.grib2",
    ]


def test_source_returns_requested_fields(grib_files):
    expected = {(tau, p.name, ilev): v for tau, p, ilev, _l, v in synthetic.all_fields(SEED, SPEC)}
    with Grib2Source(grib_files[12]) as src:
        for param in (UGRD, VGRD, TMP):
            for ilev, level in enumerate(LEVELS):
                fld = src.get(param, level, 12)
                assert fld.values.dtype == np.float64
                assert fld.values.shape == (SPEC.ny, SPEC.nx)
                np.testing.assert_array_equal(fld.values, expected[(12, param.name, ilev)])
                assert fld.reference_time == CYCLE
                assert fld.grid == SPEC.grid()


def test_both_files_are_needed(grib_files):
    a_only = [p for p in grib_files[6] if "pres_a" in p]
    with Grib2Source(a_only) as src:
        src.get(UGRD, LEVELS[4], 6)  # 1829 m is in pres_a
        with pytest.raises(MissingFieldError, match="UGRD:305 m above mean sea level:6 hour fcst"):
            src.get(UGRD, LEVELS[0], 6)
    assert isinstance(a_only[0], str)
    with Grib2Source(a_only[0]) as src:  # a single path is accepted
        src.get(TMP, LEVELS[14], 6)


def test_wrong_forecast_hour_is_not_matched(grib_files):
    with Grib2Source(grib_files[6]) as src:
        with pytest.raises(MissingFieldError, match="12 hour fcst"):
            src.get(TMP, LEVELS[10], 12)


def test_first_match_wins_and_other_products_are_ignored(tmp_path):
    import grib2io

    level, shape = LEVELS[9], (SPEC.ny, SPEC.nx)
    path = str(tmp_path / "dups.grib2")
    with grib2io.open(path, mode="w") as fh:
        # a time-averaged product (template 4.8) of the same parameter must be skipped
        avg = synthetic.grib2_message(SPEC, CYCLE, 6, TMP, level, np.full(shape, 111.0), pdtn=8)
        fh.write(avg)
        fh.write(synthetic.grib2_message(SPEC, CYCLE, 6, TMP, level, np.full(shape, 250.0)))
        fh.write(synthetic.grib2_message(SPEC, CYCLE, 6, TMP, level, np.full(shape, 260.0)))
        # same parameter on another surface type (height above ground)
        other = synthetic.grib2_message(SPEC, CYCLE, 6, TMP, LEVELS[0], np.full(shape, 270.0))
        other.typeOfFirstFixedSurface = 103
        other.pack()
        fh.write(other)
    with Grib2Source(path) as src:
        assert src.get(TMP, level, 6).values[0, 0] == 250.0
        with pytest.raises(MissingFieldError):
            src.get(TMP, LEVELS[0], 6)


def test_unreadable_inputs(tmp_path):
    with pytest.raises(GribReadError, match="cannot open"):
        Grib2Source(str(tmp_path / "missing.grib2"))
    junk = tmp_path / "junk.grib2"
    junk.write_bytes(b"this is not a GRIB file\n" * 10)
    with pytest.raises(GribReadError):
        Grib2Source(str(junk))
    with pytest.raises(GribReadError, match="no GRIB2 files"):
        Grib2Source([])


def test_run_end_to_end(grib_files, pacific_stnlist, tmp_path):
    out = tmp_path / "tran.fbwnd_pacific"
    stamp = dt.datetime(2026, 11, 11, 9, 41)
    tran = run(pacific_stnlist, grib_files, output=out, transmit_time=stamp)
    assert out.read_bytes() == tran
    assert len(tran) == 6 * 1281
    text = fbwndgfs.tran_to_text(tran)
    assert text.startswith("FBOC31 KWNO 110941\nFD1OC1\nDATA BASED ON 110600Z\nVALID 111200Z   FOR USE 0800-1500Z.")
    assert text.count("\nJON ") == 6 and text.count("\nT11 ") == 6
    # run() must agree with the step-by-step API
    stations = read_station_list(pacific_stnlist)
    results = []
    for tau in TAUS:
        with Grib2Source(grib_files[tau]) as src:
            results.append(interpolate_tau(src, stations, tau))
    assert fbwndgfs.build_tran(stations, results, stamp) == tran


def test_run_defaults_to_current_time(grib_files, pacific_stnlist):
    before = dt.datetime.now(dt.timezone.utc)
    tran = run(pacific_stnlist, grib_files)
    after = dt.datetime.now(dt.timezone.utc)
    stamp = tran[52:58].decode()
    assert stamp in {f"{t.day:02d}{t.hour:02d}{t.minute:02d}" for t in (before, after)}


def test_run_requires_all_forecast_hours(grib_files, pacific_stnlist):
    with pytest.raises(ValueError, match=r"\[24\]"):
        run(pacific_stnlist, {6: grib_files[6], 12: grib_files[12]})


def test_run_rejects_files_from_different_cycles(grib_files, pacific_stnlist, tmp_path):
    other = synthetic.write_grib2(str(tmp_path), SEED, SPEC, CYCLE + dt.timedelta(hours=6))
    mixed = {6: grib_files[6], 12: grib_files[12], 24: other[24]}
    with pytest.raises(fbwndgfs.InconsistentInputError):
        run(pacific_stnlist, mixed)


# ---- command line --------------------------------------------------------------
def _cli_args(grib_files, stations, out):
    args = ["--stations", stations, "--output", str(out), "--transmit-time", "202611110941"]
    for tau in TAUS:
        args += [f"--f{tau:03d}", *grib_files[tau]]
    return args


def test_cli(grib_files, pacific_stnlist, tmp_path, capsys):
    out, txt = tmp_path / "tran", tmp_path / "bulletins.txt"
    assert main(_cli_args(grib_files, pacific_stnlist, out) + ["--text", str(txt), "-v"]) == 0
    expected = run(pacific_stnlist, grib_files, transmit_time=dt.datetime(2026, 11, 11, 9, 41))
    assert out.read_bytes() == expected
    assert txt.read_text() == fbwndgfs.tran_to_text(expected)
    assert main(_cli_args(grib_files, pacific_stnlist, out) + ["--text", "-"]) == 0
    assert capsys.readouterr().out == fbwndgfs.tran_to_text(expected)


def test_cli_reads_station_list_from_stdin_like_the_fortran(grib_files, pacific_stnlist, tmp_path):
    out = tmp_path / "tran"
    args = _cli_args(grib_files, pacific_stnlist, out)[2:]  # drop --stations
    with open(pacific_stnlist, "rb") as stdin:
        proc = subprocess.run([sys.executable, "-m", "fbwndgfs", *args], stdin=stdin, capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode()
    assert out.read_bytes() == run(pacific_stnlist, grib_files, transmit_time=dt.datetime(2026, 11, 11, 9, 41))


def test_cli_exit_codes(grib_files, pacific_stnlist, tmp_path, capsys):
    out = tmp_path / "tran"
    good = _cli_args(grib_files, pacific_stnlist, out)
    # station list missing -> 10
    assert main(["--stations", str(tmp_path / "nope")] + good[2:]) == 10
    assert "cannot read station list" in capsys.readouterr().err
    # GRIB file missing -> 60
    bad = [str(tmp_path / "nope.grib2") if a.endswith(".f024.grib2") else a for a in good]
    assert main(bad) == 60
    # field missing (pres_b left out) -> 80
    only_a = _cli_args({t: [p for p in f if "pres_a" in p] for t, f in grib_files.items()}, pacific_stnlist, out)
    assert main(only_a) == 80
    assert "record not found" in capsys.readouterr().err
    assert not out.exists()
    # bad command line -> 2 (argparse)
    for extra in (["--transmit-time", "yesterday"], ["--legacy-grid-dims", "big"], ["--legacy-grid-dims", "2x2"]):
        with pytest.raises(SystemExit) as exc:
            main(good + extra)
        assert exc.value.code == 2


# ---- golden files produced by the Fortran program -------------------------------
@pytest.mark.parametrize("name", sorted(run_legacy.GOLDEN))
def test_matches_fortran_golden_output(name, tmp_path):
    """Byte-for-byte agreement with output of the compiled fbwndgfs.F.

    The golden files were written by the Fortran executable (see
    tests/legacy) from the same synthetic fields, delivered as GRIB1.
    """
    seed, spec, cycle, stations, legacy_dims = run_legacy.GOLDEN[name]
    with open(os.path.join(run_legacy.DATA, name + ".tran"), "rb") as fh:
        golden = fh.read()
    files = synthetic.write_grib2(str(tmp_path), seed, spec, cycle)
    tran = run(stations, files, transmit_time=run_legacy.transmit_time_of(golden), legacy_grid_dims=legacy_dims)
    if tran != golden:  # show the first differing lines rather than a byte dump
        ours = tran.decode().replace("\n", "").split("<<@")
        theirs = golden.decode("latin-1").replace("\n", "").split("<<@")
        diffs = [(a, b) for a, b in zip(ours, theirs) if a != b][:5]
        pytest.fail(f"{name}: output differs from the Fortran reference, first differences: {diffs}")


def test_default_mode_differs_from_fortran_on_quarter_degree_grid(tmp_path):
    """On the operational 0.25 degree grid the port deliberately does NOT
    reproduce the Fortran: the Fortran mis-indexes that grid."""
    seed, spec, cycle, stations, _ = run_legacy.GOLDEN["golden_0p25_legacy_dims"]
    with open(os.path.join(run_legacy.DATA, "golden_0p25_legacy_dims.tran"), "rb") as fh:
        golden = fh.read()
    files = synthetic.write_grib2(str(tmp_path), seed, spec, cycle)
    tran = run(stations, files, transmit_time=run_legacy.transmit_time_of(golden))
    assert len(tran) == len(golden)
    ours = tran.decode().replace("\n", "").split("<<@")
    theirs = golden.decode().replace("\n", "").split("<<@")

    def is_data(line: str) -> bool:
        line = line.lstrip(">")
        return line.startswith("$") and not line.startswith("$DATA")

    assert len(ours) == len(theirs)
    headings = [k for k, line in enumerate(theirs) if not is_data(line)]
    data = [k for k, line in enumerate(theirs) if is_data(line)]
    assert len(data) == 6 * 15
    assert all(ours[k] == theirs[k] for k in headings)  # headings agree ...
    assert sum(ours[k] != theirs[k] for k in data) > 0.9 * len(data)  # ... the numbers do not
