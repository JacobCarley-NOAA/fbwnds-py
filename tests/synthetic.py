"""Deterministic synthetic GFS-like inputs for the tests.

The same integer-valued fields are written two ways:

* as GRIB2 with grib2io (input of the Python port), and
* as a raw float32 stream plus a control file from which the Fortran helper
  ``tests/legacy/mkgrib1.f90`` writes GRIB1 (input of the legacy program).

Whole numbers (decimal scale 0) decode to exactly the same values from
both formats, so the port and the Fortran can be compared byte for byte.
``numpy.random.RandomState`` is used because its streams are frozen across
NumPy versions, which keeps the stored golden files valid.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

import numpy as np

from fbwndgfs.constants import LEVELS, PARAMETERS, TAUS, TMP
from fbwndgfs.grid import LatLonGrid


@dataclass(frozen=True)
class GridSpec:
    """A latitude/longitude grid stored north to south, west to east.

    Corner coordinates and spacing are whole millidegrees so that GRIB1
    (millidegrees) and GRIB2 (microdegrees) describe exactly the same grid.
    """

    nx: int
    ny: int
    lat1_mdeg: int
    lon1_mdeg: int
    d_mdeg: int  #: spacing in both directions

    @property
    def lat2_mdeg(self) -> int:
        return self.lat1_mdeg - (self.ny - 1) * self.d_mdeg

    @property
    def lon2_mdeg(self) -> int:
        return self.lon1_mdeg + (self.nx - 1) * self.d_mdeg

    def template(self) -> list[int]:
        """GRIB2 grid definition template 3.0 (microdegrees)."""
        return [
            6, 0, 0, 0, 0, 0, 0, self.nx, self.ny, 0, 0,
            self.lat1_mdeg * 1000, self.lon1_mdeg * 1000, 48,
            self.lat2_mdeg * 1000, self.lon2_mdeg * 1000,
            self.d_mdeg * 1000, self.d_mdeg * 1000, 0,
        ]  # fmt: skip

    def grid(self) -> LatLonGrid:
        return LatLonGrid.from_grib2_template(0, self.template())


#: The operational GFS 0.25 degree global grid (1440 x 721).
QUARTER_DEGREE = GridSpec(1440, 721, 90_000, 0, 250)

#: A 0.2 degree grid with exactly the dimensions hard-wired in the Fortran
#: (IMAX = 1760, JMAX = 880).  On this grid the Fortran indexes fields
#: correctly, so it is a valid reference for the port's default mode.
LEGACY_SIZED = GridSpec(1760, 880, 87_900, 0, 200)

#: Small grids for fast tests.
ONE_DEGREE = GridSpec(360, 181, 90_000, 0, 1000)


def make_field(rng: np.random.RandomState, spec: GridSpec, param, ilev: int) -> np.ndarray:
    """Whole-number field with enough range to exercise every encoding branch."""
    shape = (spec.ny, spec.nx)
    if param is TMP:
        # 195..305 K: both signs of Celsius temperature at every level.
        return rng.randint(195, 306, size=shape).astype(np.float32)
    # Winds in m/s.  Upper levels reach +-125 m/s (> 199 kt); a calm band
    # near the equator produces "9900" groups.
    amp = 20 + 7 * ilev
    fld = rng.randint(-amp, amp + 1, size=shape).astype(np.float32)
    j0 = spec.ny // 2
    fld[j0 - 8 : j0 + 8, :] = rng.randint(-1, 2, size=(16, spec.nx))  # calm band
    return fld


def all_fields(seed: int, spec: GridSpec, tenths: bool = False):
    """Yield (tau, param, ilev, level, values) in the order the program reads them.

    With ``tenths=True`` a random number of tenths is added to every point,
    giving fields with the 0.1 precision of real GFS winds and temperatures.
    """
    rng = np.random.RandomState(seed)
    for tau in TAUS:
        for param in PARAMETERS:
            for ilev, level in enumerate(LEVELS):
                values = make_field(rng, spec, param, ilev)
                if tenths:
                    frac = rng.randint(0, 10, size=values.shape)
                    values = ((values.astype(np.int64) * 10 + frac) / 10.0).astype(np.float32)
                yield tau, param, ilev, level, values


def write_grib2(
    directory: str, seed: int, spec: GridSpec, cycle: dt.datetime, split: bool = True, tenths: bool = False
) -> dict[int, list[str]]:
    """Write the synthetic run as GRIB2; return ``{tau: [files]}``.

    With ``split=True`` each forecast hour is written as two files, mimicking
    the GFS ``pres_a``/``pres_b`` pair: the 305, 457, 610, 914 and 4572 m
    levels go to the "b" file.
    """
    import grib2io

    b_levels = {305, 457, 610, 914, 4572}
    paths: dict[int, list[str]] = {}
    handles: dict[str, object] = {}
    try:
        for tau, param, _ilev, level, values in all_fields(seed, spec, tenths):
            which = "b" if (split and level.kind == "height" and level.value in b_levels) else "a"
            path = os.path.join(directory, f"gfs.t{cycle:%H}z.pres_{which}.f{tau:03d}.grib2")
            if path not in handles:
                handles[path] = grib2io.open(path, mode="w")
                paths.setdefault(tau, []).append(path)
            handles[path].write(grib2_message(spec, cycle, tau, param, level, values, dec_scale=int(tenths)))
    finally:
        for fh in handles.values():
            fh.close()
    for files in paths.values():
        files.sort()
    return paths


def grib2_message(
    spec: GridSpec, cycle: dt.datetime, tau: int, param, level, values: np.ndarray, pdtn: int = 0, dec_scale: int = 0
):
    """One simple-packed GRIB2 message with the given decimal scale factor."""
    import grib2io

    section3 = np.array([0, spec.nx * spec.ny, 0, 0, 0] + spec.template())
    msg = grib2io.Grib2Message(section3=section3, pdtn=pdtn, drtn=0)
    msg.discipline = 0
    msg.originatingCenter = 7
    msg.originatingSubCenter = 0
    msg.masterTableInfo = 2
    msg.localTableInfo = 1
    msg.significanceOfReferenceTime = 1
    msg.refDate = cycle
    msg.productionStatus = 0
    msg.typeOfData = 1
    msg.parameterCategory = param.grib2_category
    msg.parameterNumber = param.grib2_number
    msg.typeOfGeneratingProcess = 2
    msg.generatingProcess = 96
    msg.unitOfForecastTime = 1
    msg.valueOfForecastTime = tau
    msg.typeOfFirstFixedSurface = level.grib2_surface_type
    msg.scaleFactorOfFirstFixedSurface = 0
    msg.scaledValueOfFirstFixedSurface = int(level.grib2_surface_value)
    msg.typeOfSecondFixedSurface = 255
    msg.decScaleFactor = dec_scale
    msg.binScaleFactor = 0
    msg.nBitsPacking = 0
    msg.data = np.asarray(values, dtype=np.float32)
    msg.pack()
    return msg


def write_legacy_inputs(
    directory: str, seed: int, spec: GridSpec, cycle: dt.datetime, tenths: bool = False
) -> dict[int, tuple[str, str]]:
    """Write control + raw files for ``mkgrib1``; return ``{tau: (ctl, raw)}``."""
    out: dict[int, tuple[str, str]] = {}
    handles = {}
    lines: dict[int, list[str]] = {}
    try:
        for tau, param, _ilev, level, values in all_fields(seed, spec, tenths):
            if tau not in handles:
                raw = os.path.join(directory, f"f{tau:03d}.raw")
                handles[tau] = open(raw, "wb")
                lines[tau] = []
                out[tau] = (os.path.join(directory, f"f{tau:03d}.ctl"), raw)
            ltype = 103 if level.kind == "height" else 100
            lines[tau].append(
                f"{param.grib1_number} {ltype} {level.value} {cycle.year % 100} "
                f"{cycle.month} {cycle.day} {cycle.hour} {tau} {int(tenths)}"
            )
            values.astype("<f4").tofile(handles[tau])
    finally:
        for fh in handles.values():
            fh.close()
    for tau, (ctl, _raw) in out.items():
        with open(ctl, "w") as fh:
            fh.write(
                f"{spec.nx} {spec.ny} {spec.lat1_mdeg} {spec.lon1_mdeg} {spec.lat2_mdeg} "
                f"{spec.lon2_mdeg} {spec.d_mdeg} {spec.d_mdeg}\n"
            )
            fh.write(f"{len(lines[tau])}\n")
            fh.write("\n".join(lines[tau]) + "\n")
    return out
