"""Driver logic on in-memory fields (no GRIB library needed)."""

import datetime as dt

import numpy as np
import pytest

import synthetic
from fbwndgfs import ArraySource, build_tran, interpolate_tau, read_station_list, tran_to_text
from fbwndgfs.constants import LEVELS, MS_TO_KT, PARAMETERS, TAUS, TMP, UGRD, VGRD
from fbwndgfs.core import _interpolation_view
from fbwndgfs.errors import (
    InconsistentInputError,
    MissingFieldError,
    StationListError,
    StationOffGridError,
    UnsupportedGridError,
)
from fbwndgfs.stations import Station

CYCLE = dt.datetime(2026, 11, 11, 12)
SPEC = synthetic.ONE_DEGREE


def analytic_source(spec=SPEC, cycle=CYCLE, taus=TAUS, skip=None):
    """u = 10 m/s + lon/36, v = -5 m/s, T = 300 K - |lat| - 3 K per level."""
    grid = spec.grid()
    lat = grid.lat1 + grid.dlat * np.arange(grid.ny)
    lon = grid.lon1 + grid.dlon * np.arange(grid.nx)
    lon2d, lat2d = np.meshgrid(lon, lat)
    src = ArraySource(grid, cycle)
    for tau in taus:
        for ilev, level in enumerate(LEVELS):
            for param in PARAMETERS:
                if skip == (param, ilev, tau):
                    continue
                if param is UGRD:
                    values = 10.0 + lon2d / 36.0
                elif param is VGRD:
                    values = np.full_like(lon2d, -5.0)
                else:
                    values = 300.0 - np.abs(lat2d) - 3.0 * ilev
                src.add(param, level, tau, values)
    return src


STATIONS = [
    Station("B", " ", "AAA ", 0, 20.5, 144.0),
    Station("E", " ", "BBB ", 5000, -10.25, -170.5),
    Station("B", " ", "AAA ", 0, 20.5, 144.0),
    Station("E", " ", "BBB ", 5000, -10.25, -170.5),
]


def test_interpolated_values_for_linear_fields():
    res = interpolate_tau(analytic_source(), STATIONS, 6)
    assert res.tau == 6 and res.reference_time == CYCLE
    a = res.data[0]
    # u = (10 + 144/36) m/s = 14 m/s, v = -5 m/s, stored as truncated hundredths of a knot
    assert a[0].u_kt == int(14.0 * MS_TO_KT * 100) / 100
    assert a[0].v_kt == int(-5.0 * MS_TO_KT * 100) / 100
    # T = 300 - 20.5 - 3*ilev K
    for ilev in range(15):
        assert a[ilev].temp_c == pytest.approx(300 - 20.5 - 3 * ilev - 273.15, abs=0.011)
    # wind from 290 degrees at 29 kt: atan2(27.19, -9.71) + 180 = 289.6
    assert a[7].wind == "2929"
    # station B: lon -170.5 -> 189.5 E; u = 15.264 m/s = 29.65 kt
    b = res.data[1]
    assert b[0].u_kt == pytest.approx((10 + 189.5 / 36) * MS_TO_KT, abs=0.011)
    assert b[9].temp == "-10"  # 300 - 10.25 - 27 - 273.15 = -10.4


def test_temperature_groups_and_terrain_blanking():
    res = interpolate_tau(analytic_source(), STATIONS, 12)
    a, b = res.data[0], res.data[1]
    # sea-level station: temps only from 6000 ft (level index 4) upward
    assert [d.temp for d in a[:4]] == ["   "] * 4
    assert a[4].temp == "-06"  # 300 - 20.5 - 12 - 273.15 = -5.65
    assert a[14].temp == "-36"  # -35.65
    assert all(d.wind.strip() for d in a)
    # 5000 ft station: 3000 and 6000 ft winds and the 6000 ft temperature are blanked
    assert b[3].wind == "    " and b[4].wind == "    " and b[5].wind != "    "
    assert b[4].temp == "   " and b[5].temp != "   "


def test_same_station_listed_twice_gets_same_values():
    res = interpolate_tau(analytic_source(), STATIONS, 24)
    assert res.data[0] == res.data[2]
    assert res.data[1] == res.data[3]


def test_missing_field_is_reported():
    src = analytic_source(skip=(VGRD, 9, 12))
    interpolate_tau(src, STATIONS, 6)
    with pytest.raises(MissingFieldError, match="VGRD:400 mb:12 hour fcst"):
        interpolate_tau(src, STATIONS, 12)
    src = analytic_source(skip=(TMP, 0, 6))
    with pytest.raises(MissingFieldError, match="TMP:305 m above mean sea level:6 hour fcst"):
        interpolate_tau(src, STATIONS, 6)


def test_station_off_grid():
    spec = synthetic.GridSpec(41, 21, 30_000, 140_000, 1000)  # 10..30 N, 140..180 E
    src = analytic_source(spec)
    inside = [Station("B", " ", "IN  ", 0, 20.0, 160.0), Station("E", " ", "IN2 ", 0, 12.0, 150.0)]
    interpolate_tau(src, inside, 6)
    outside = inside + [Station(" ", " ", "OUT ", 0, 50.0, 160.0)]
    with pytest.raises(StationOffGridError, match="'OUT'.*outside the model grid"):
        interpolate_tau(src, outside, 6)


def test_missing_data_at_station():
    src = analytic_source()
    key = next(iter(src._fields))
    src._fields[key] = src._fields[key].copy()
    src._fields[key][68:72, 142:147] = np.nan  # around 20.5 N, 144 E
    with pytest.raises(StationOffGridError, match="'AAA': no valid data"):
        interpolate_tau(src, STATIONS, 6)


def test_mixed_cycles_within_a_forecast_hour():
    src = analytic_source()
    real_get = src.get

    def get(param, level, tau):
        fld = real_get(param, level, tau)
        if param is TMP:
            fld.reference_time = CYCLE - dt.timedelta(hours=6)
        return fld

    src.get = get
    with pytest.raises(InconsistentInputError, match="20261111 06Z"):
        interpolate_tau(src, STATIONS, 6)


def _results(cycle=CYCLE):
    src = analytic_source(cycle=cycle)
    return [interpolate_tau(src, STATIONS, tau) for tau in TAUS]


def test_build_tran_structure():
    tran = build_tran(STATIONS, _results(), dt.datetime(2026, 11, 11, 16, 5))
    assert len(tran) % 1281 == 0
    stream = tran.decode("ascii").replace("\n", "")
    assert stream.count("%") == 6 and stream.count("'10") == 6
    order = [stream.index(h) for h in ("FBOC31", "FBOC37", "FBOC33", "FBOC38", "FBOC35", "FBOC39")]
    assert order == sorted(order)
    assert stream.count("KWNO 111605<<@") == 6
    assert stream.count("DATA BASED ON 111200Z") == 6
    for valid, use in (("111800", "1400-2100"), ("120000", "2100-0600"), ("121200", "0600-1800")):
        assert stream.count(f"VALID {valid}Z   FOR USE {use}Z.") == 2
    text = tran_to_text(tran)
    assert text.count("AAA ") == 6 and text.count("BBB ") == 6
    assert "|" not in text and "$" not in text and "^" not in text


def test_build_tran_rejects_mixed_cycles_and_bad_lists():
    results = _results()
    results[2].reference_time = CYCLE + dt.timedelta(hours=6)
    with pytest.raises(InconsistentInputError, match="forecast hour 24"):
        build_tran(STATIONS, results, CYCLE)
    with pytest.raises(ValueError):
        build_tran(STATIONS, _results()[:2], CYCLE)
    with pytest.raises(StationListError):
        build_tran(STATIONS[:2], _results(), CYCLE)
    with pytest.raises(InconsistentInputError, match="not a 00/06/12/18"):
        build_tran(STATIONS, _results(dt.datetime(2026, 11, 11, 9)), CYCLE)


def test_groups_may_hold_different_stations(pacific_stnlist):
    stations = read_station_list(pacific_stnlist)
    subset = stations[:15] + [Station("B", " ", "GUM ", 298, 13.48, 144.78),
                              Station("E", " ", "ROR ", 176, 7.37, 134.53)]  # fmt: skip
    src = analytic_source()
    text = tran_to_text(build_tran(subset, [interpolate_tau(src, subset, t) for t in TAUS], CYCLE))
    low, high = text.split("\n\n")[:2]
    assert len(low.splitlines()) == 5 + 15 and len(high.splitlines()) == 5 + 2
    assert [line[:3] for line in high.splitlines()[5:]] == ["GUM", "ROR"]


# ---- legacy grid dimension emulation ---------------------------------------
def test_interpolation_view_default_is_the_field_itself():
    values = np.arange(12.0).reshape(3, 4)
    assert _interpolation_view(values, None) is values


def test_interpolation_view_legacy_layout():
    """FLD(II,JJ) laid over the decoded points: element (i,j) = flat[(j-1)*II + i-1]."""
    values = np.arange(12.0).reshape(3, 4)  # a 4 x 3 grid
    view = _interpolation_view(values, (6, 5))
    assert view.shape == (5, 6)
    assert list(view[0]) == [0, 1, 2, 3, 4, 5]  # runs past the end of the true first row
    assert list(view[1]) == [6, 7, 8, 9, 10, 11]
    assert np.isnan(view[2:]).all()
    with pytest.raises(UnsupportedGridError):
        _interpolation_view(values, (2, 2))


def test_legacy_dims_equal_default_when_grid_matches():
    spec = synthetic.GridSpec(60, 31, 90_000, 0, 6000)
    src = analytic_source(spec)
    stations = [Station("B", " ", "AAA ", 0, 20.5, 144.0), Station("E", " ", "BBB ", 0, -40.0, 200.0)] * 2
    assert interpolate_tau(src, stations, 6, legacy_grid_dims=(60, 31)).data == interpolate_tau(src, stations, 6).data


def test_legacy_dims_misplace_stations_on_the_quarter_degree_grid():
    """The defect this port fixes: with IMAX=1760 on a 1440-wide grid the
    Fortran reads the wrong grid points (docs/PORTING_NOTES.md)."""
    spec = synthetic.QUARTER_DEGREE
    grid = spec.grid()
    lat = grid.lat1 + grid.dlat * np.arange(grid.ny)
    temp = np.repeat((273.15 + lat / 2.0)[:, None], grid.nx, axis=1)  # T(C) = lat / 2
    zero = np.zeros_like(temp)
    src = ArraySource(grid, CYCLE)
    for level in LEVELS:
        src.add(UGRD, level, 6, zero)
        src.add(VGRD, level, 6, zero)
        src.add(TMP, level, 6, temp)
    jon = [Station("B", " ", "JON ", 7, 16.72, -169.53), Station("E", " ", "PPG ", 30, -14.33, -170.71)] * 2
    right = interpolate_tau(src, jon, 6)
    wrong = interpolate_tau(src, jon, 6, legacy_grid_dims=(1760, 880))
    assert right.data[0][5].temp == "|08" and right.data[1][5].temp == "-07"  # lat / 2
    assert wrong.data[0][5].temp == "|00" and wrong.data[1][5].temp == "-19"
    # Johnston Island (16.72 N) is given values from rows near the equator:
    # the flat index x + (y-1)*1760 lands about 65 grid rows too far south.
    assert wrong.data[0][5].temp_c * 2 == pytest.approx(0.3, abs=0.3)
