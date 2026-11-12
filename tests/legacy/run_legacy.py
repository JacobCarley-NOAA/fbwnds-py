"""Run the compiled Fortran reference on synthetic inputs.

Needs the directory produced by ``tests/legacy/build_legacy.sh`` (holding
``fbwndgfs.x``, ``mkgrib1`` and ``grbindex``), given as ``legacy_dir`` or in
the environment variable ``FBWNDGFS_LEGACY_DIR``.

Command line use regenerates the golden files in ``tests/data``::

    FBWNDGFS_LEGACY_DIR=/path/to/build python tests/legacy/run_legacy.py
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import synthetic  # noqa: E402


def legacy_dir() -> str | None:
    path = os.environ.get("FBWNDGFS_LEGACY_DIR")
    if path and all(os.path.exists(os.path.join(path, exe)) for exe in ("fbwndgfs.x", "mkgrib1", "grbindex")):
        return path
    return None


def run_legacy(
    workdir: str,
    station_list: str,
    seed: int,
    spec: synthetic.GridSpec,
    cycle: dt.datetime,
    exe_dir: str | None = None,
    tenths: bool = False,
) -> bytes:
    """Create GRIB1 inputs, run ``fbwndgfs.x`` and return its tran file."""
    exe_dir = exe_dir or legacy_dir()
    if exe_dir is None:
        raise RuntimeError("FBWNDGFS_LEGACY_DIR is not set or incomplete")
    inputs = synthetic.write_legacy_inputs(workdir, seed, spec, cycle, tenths)
    env = dict(os.environ)
    for unit, tau in ((11, 6), (12, 12), (13, 24)):
        ctl, raw = inputs[tau]
        grb = os.path.join(workdir, f"f{tau:03d}.grib1")
        idx = grb + ".idx"
        subprocess.run([os.path.join(exe_dir, "mkgrib1"), ctl, raw, grb], check=True, cwd=workdir)
        subprocess.run([os.path.join(exe_dir, "grbindex"), grb, idx], check=True, cwd=workdir, stdout=subprocess.DEVNULL)
        os.remove(raw)
        # The Fortran holds file names in CHARACTER*80 variables, so pass
        # names relative to the working directory rather than full paths.
        env[f"FORT{unit}"] = os.path.basename(grb)
        env[f"FORT{unit + 20}"] = os.path.basename(idx)
    out = os.path.join(workdir, "tran.legacy")
    env["FORT51"] = os.path.basename(out)
    with open(station_list, "rb") as stdin:
        proc = subprocess.run(
            [os.path.join(exe_dir, "fbwndgfs.x")], stdin=stdin, env=env, cwd=workdir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"fbwndgfs.x failed ({proc.returncode}):\n{proc.stdout.decode(errors='replace')[-2000:]}")
    with open(out, "rb") as fh:
        return fh.read()


def transmit_time_of(tran: bytes) -> dt.datetime:
    """Recover the wall-clock stamp the Fortran put in the first WMO heading.

    Only day, hour and minute appear in the bulletin; year and month of the
    returned value are placeholders.
    """
    stamp = tran[52:58].decode("ascii")  # DDHHMM after "FBOC31 KWNO "
    return dt.datetime(2000, 1, int(stamp[:2]), int(stamp[2:4]), int(stamp[4:6]))


#: The stored golden cases: name -> (seed, grid, cycle, station list, legacy_grid_dims)
DATA = os.path.join(os.path.dirname(HERE), "data")
GOLDEN = {
    # Operational configuration: 0.25 degree input, where the Fortran
    # mis-indexes the grid.  Checks the port's emulation of the executable.
    "golden_0p25_legacy_dims": (
        20261111, synthetic.QUARTER_DEGREE, dt.datetime(2026, 11, 11, 12),
        os.path.join(os.path.dirname(os.path.dirname(HERE)), "parm", "fbwnd_pacific.stnlist"),
        (1760, 880),
    ),
    # Grid with the dimensions the Fortran assumes: its indexing is right,
    # so the port's default mode must agree with it.  Month-end 18Z cycle,
    # high terrain, edge-of-grid stations, more than one ETB per bulletin.
    "golden_1760x880_default": (
        19860103, synthetic.LEGACY_SIZED, dt.datetime(2027, 2, 28, 18),
        os.path.join(DATA, "stress.stnlist"),
        None,
    ),
}


def main() -> None:
    for name, (seed, spec, cycle, stations, _dims) in GOLDEN.items():
        with tempfile.TemporaryDirectory() as tmp:
            tran = run_legacy(tmp, stations, seed, spec, cycle)
        path = os.path.join(DATA, name + ".tran")
        with open(path, "wb") as fh:
            fh.write(tran)
        print(f"wrote {path} ({len(tran)} bytes)")


if __name__ == "__main__":
    main()
