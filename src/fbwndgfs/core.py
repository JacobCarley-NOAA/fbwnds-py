"""Driver: read fields, interpolate to stations, encode, build bulletins.

This is the main program of ``fbwndgfs.F`` restructured into three steps
that can be used separately:

1. :func:`interpolate_tau` - fields of one forecast hour -> station values
2. :func:`build_tran` - station values -> transmission-file bytes
3. :func:`run` - both, from file names, writing the output file
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .bulletin import (
    TranStream,
    base_time_line,
    bulletin_id,
    catalog_header,
    header_times,
    level_heading,
    station_line,
    valid_time_line,
)
from .constants import (
    BULLETIN_LEVEL_RANGES,
    CRCRLF,
    KELVIN_OFFSET,
    LEVELS,
    MS_TO_KT,
    NLEVELS,
    PARAMETERS,
    TAUS,
    TMP,
)
from .encode import StationLevelData, apply_elevation_rules, encode_temp, encode_wind, to_hundredths
from .errors import InconsistentInputError, StationOffGridError, UnsupportedGridError
from .gribio import Field, FieldSource, Grib2Source
from .grid import LatLonGrid
from .stations import PathOrLines, Station, bulletin_groups, read_station_list
from .w3emc import w3ft01

log = logging.getLogger(__name__)


@dataclass
class TauResult:
    """Everything computed for one forecast hour."""

    tau: int
    reference_time: dt.datetime
    #: ``data[s][l]`` for station ``s`` (station-list order) and level ``l``.
    data: list[list[StationLevelData]] = field(default_factory=list)


def _interpolation_view(values: np.ndarray, legacy_grid_dims: tuple[int, int] | None) -> np.ndarray:
    """Return the 2-D array ``W3FT01`` should index.

    Normally this is the field itself.  With ``legacy_grid_dims = (II, JJ)``
    the field is laid out the way the Fortran saw it: as the start of a
    flat array that ``W3FT01`` indexes as ``FLD(II, JJ)`` regardless of the
    true grid size.  Points beyond the decoded field are NaN (the Fortran
    read stale memory there).
    """
    if legacy_grid_dims is None:
        return values
    ii, jj = legacy_grid_dims
    flat = np.full(ii * jj, np.nan, dtype=np.float64)
    if values.size > flat.size:
        raise UnsupportedGridError(
            f"field has {values.size} points, more than the legacy limit of {flat.size}"
        )
    flat[: values.size] = values.ravel()
    return flat.reshape(jj, ii)


def interpolate_tau(
    source: FieldSource,
    stations: Sequence[Station],
    tau: int,
    *,
    legacy_grid_dims: tuple[int, int] | None = None,
) -> TauResult:
    """Read the 45 fields of one forecast hour and reduce them to stations.

    For every station and level the u and v wind components (converted to
    knots) and the temperature (converted to Celsius) are interpolated with
    the biquadratic ``W3FT01`` scheme, stored as truncated integer
    hundredths as the Fortran did, and encoded.

    Parameters
    ----------
    source
        Supplier of the fields, normally a :class:`~fbwndgfs.gribio.Grib2Source`.
    stations
        Stations in station-list order.
    tau
        Forecast hour.
    legacy_grid_dims
        ``None`` (default) interpolates on the grid the data is actually on.
        ``(1760, 880)`` reproduces the Fortran executable, which indexes
        every field as if it were on the T574 Gaussian grid.  See
        ``docs/PORTING_NOTES.md``; intended for regression testing only.
    """
    nstn = len(stations)
    hundredths = np.zeros((len(PARAMETERS), nstn, NLEVELS), dtype=np.int64)
    reference_time: dt.datetime | None = None
    grid: LatLonGrid | None = None
    points: list[tuple[float, float]] = []

    for ityp, param in enumerate(PARAMETERS):
        for ilev, level in enumerate(LEVELS):
            fld: Field = source.get(param, level, tau)

            if reference_time is None:
                reference_time = fld.reference_time
            elif fld.reference_time != reference_time:
                raise InconsistentInputError(
                    f"{fld.description} is from the {fld.reference_time:%Y%m%d %HZ} cycle; "
                    f"other fields are from {reference_time:%Y%m%d %HZ}"
                )

            if fld.grid != grid:
                if grid is not None:
                    log.warning("%s is on a different grid from the preceding fields", fld.description)
                grid = fld.grid
                points = _station_points(grid, stations)

            # Convert to bulletin units before interpolating, as the Fortran does.
            if param is TMP:
                values = fld.values - KELVIN_OFFSET
            else:
                values = fld.values * MS_TO_KT
            view = _interpolation_view(values, legacy_grid_dims)

            for s, (x, y) in enumerate(points):
                value = w3ft01(x, y, view, ncyclk=0, lin=0)
                if not np.isfinite(value):
                    raise StationOffGridError(
                        f"station {stations[s].name!r}: no valid data for {fld.description}"
                    )
                hundredths[ityp, s, ilev] = to_hundredths(value)

    assert reference_time is not None
    result = TauResult(tau=tau, reference_time=reference_time)
    for s, stn in enumerate(stations):
        winds: list[str] = []
        temps: list[str] = []
        for ilev in range(NLEVELS):
            winds.append(encode_wind(int(hundredths[0, s, ilev]), int(hundredths[1, s, ilev])))
            temps.append(encode_temp(int(hundredths[2, s, ilev])))
        apply_elevation_rules(stn.elevation_ft, winds, temps)
        result.data.append(
            [
                StationLevelData(
                    u_kt=float(hundredths[0, s, ilev]) * 0.01,
                    v_kt=float(hundredths[1, s, ilev]) * 0.01,
                    temp_c=float(hundredths[2, s, ilev]) * 0.01,
                    wind=winds[ilev],
                    temp=temps[ilev],
                )
                for ilev in range(NLEVELS)
            ]
        )
    return result


def _station_points(grid: LatLonGrid, stations: Sequence[Station]) -> list[tuple[float, float]]:
    points = []
    for stn in stations:
        xy = grid.earth_to_grid(stn.lon, stn.lat)
        if xy is None:
            raise StationOffGridError(
                f"station {stn.name!r} ({stn.lat}, {stn.lon}) is outside the model grid"
            )
        points.append(xy)
    return points


def build_tran(
    stations: Sequence[Station],
    results: Sequence[TauResult],
    transmit_time: dt.datetime,
) -> bytes:
    """Lay out the bulletins of a run and return the tran-file bytes.

    Two bulletins are produced per forecast hour: levels 1000-24000 ft for
    the first ``B``..``E`` station group of the list and 30000-53000 ft for
    the second.

    Parameters
    ----------
    stations
        The full station list, in file order.
    results
        One :class:`TauResult` per forecast hour, in the order 6, 12, 24.
    transmit_time
        UTC time stamp for the WMO headings of all bulletins.
    """
    if len(results) != len(TAUS):
        raise ValueError(f"expected results for forecast hours {TAUS}")
    cycle = results[0].reference_time
    for res in results:
        if res.reference_time != cycle:
            raise InconsistentInputError(
                f"forecast hour {res.tau} is from the {res.reference_time:%Y%m%d %HZ} cycle, "
                f"forecast hour {results[0].tau} from {cycle:%Y%m%d %HZ}"
            )

    groups = bulletin_groups(stations, count=len(BULLETIN_LEVEL_RANGES))
    # Index of each group's first station in the full list.
    starts = [0]
    for grp in groups[:-1]:
        starts.append(starts[-1] + len(grp))

    stream = TranStream()
    for itau, res in enumerate(results):
        times = header_times(cycle, res.tau, transmit_time)
        for part, (first, last) in enumerate(BULLETIN_LEVEL_RANGES):
            ident = bulletin_id(itau, part)
            stream.begin_bulletin(
                [
                    catalog_header(ident, times),
                    base_time_line(times),
                    valid_time_line(times),
                    level_heading(first, last),
                    CRCRLF,
                ]
            )
            for offset, stn in enumerate(groups[part]):
                levels = res.data[starts[part] + offset]
                stream.add_station_line(
                    station_line(
                        stn.ident,
                        [d.wind for d in levels],
                        [d.temp for d in levels],
                        first,
                        last,
                    )
                )
            stream.end_bulletin()
            log.info("%s: %d stations, valid %sZ", ident.wmo_heading, len(groups[part]), times.valid)
    return stream.to_records()


def run(
    station_list: PathOrLines,
    grib_files: Mapping[int, Sequence[str | os.PathLike] | str | os.PathLike],
    output: str | os.PathLike | None = None,
    *,
    transmit_time: dt.datetime | None = None,
    legacy_grid_dims: tuple[int, int] | None = None,
) -> bytes:
    """Create the Pacific winds/temperatures aloft bulletins.

    Parameters
    ----------
    station_list
        Path to (or lines of) the station list, e.g. ``fbwnd_pacific.stnlist``.
    grib_files
        GRIB2 file(s) for each forecast hour, keyed by hour: ``{6: [...],
        12: [...], 24: [...]}``.  For the GFS give both the ``pres_a`` and
        ``pres_b`` 0.25 degree files of each hour.
    output
        Where to write the 1280-byte-record transmission file.  ``None``
        writes nothing.
    transmit_time
        UTC time for the WMO heading.  Defaults to the current time, as in
        the Fortran.
    legacy_grid_dims
        See :func:`interpolate_tau`.

    Returns
    -------
    bytes
        The transmission file contents.

    Raises
    ------
    fbwndgfs.errors.FbwndError
        Any of its subclasses; see :mod:`fbwndgfs.errors`.
    """
    missing = [tau for tau in TAUS if tau not in grib_files]
    if missing:
        raise ValueError(f"no GRIB2 files given for forecast hour(s) {missing}")
    if transmit_time is None:
        transmit_time = dt.datetime.now(dt.timezone.utc)

    stations = read_station_list(station_list)
    log.info("number of stations = %d", len(stations))
    bulletin_groups(stations, count=len(BULLETIN_LEVEL_RANGES))  # fail early

    results = []
    for tau in TAUS:
        log.info("forecast hour %d: %s", tau, grib_files[tau])
        with Grib2Source(grib_files[tau]) as source:
            results.append(
                interpolate_tau(source, stations, tau, legacy_grid_dims=legacy_grid_dims)
            )

    tran = build_tran(stations, results, transmit_time)
    if output is not None:
        with open(output, "wb") as fh:
            fh.write(tran)
        log.info("wrote %s (%d records)", output, len(tran) // 1281)
    return tran
