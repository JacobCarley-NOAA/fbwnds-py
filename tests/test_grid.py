"""Latitude/longitude grid geometry (replacement for GDSWZD)."""

import pytest

from fbwndgfs.errors import UnsupportedGridError
from fbwndgfs.grid import LatLonGrid

import synthetic


@pytest.fixture
def gfs():
    return synthetic.QUARTER_DEGREE.grid()


def test_from_template(gfs):
    assert (gfs.nx, gfs.ny) == (1440, 721)
    assert (gfs.lat1, gfs.lon1, gfs.lat2, gfs.lon2) == (90.0, 0.0, -90.0, 359.75)
    assert gfs.dlon == pytest.approx(0.25, rel=1e-14)
    assert gfs.dlat == pytest.approx(-0.25, rel=1e-14)
    assert gfs.is_global_in_longitude
    assert not synthetic.LEGACY_SIZED.grid().is_global_in_longitude


@pytest.mark.parametrize(
    "lon, lat, x, y",
    [
        (0.0, 90.0, 1.0, 1.0),
        (359.75, -90.0, 1440.0, 721.0),
        (180.0, 0.0, 721.0, 361.0),
        (-169.53, 16.72, 1 + 190.47 / 0.25, 1 + (90 - 16.72) / 0.25),  # Johnston Island
        (190.47, 16.72, 1 + 190.47 / 0.25, 1 + (90 - 16.72) / 0.25),  # same point, 0..360
        (144.78, 13.48, 580.12, 307.08),  # Guam
        (-0.1, -14.33, 1 + 359.9 / 0.25, 1 + 104.33 / 0.25),  # just west of Greenwich
    ],
)
def test_earth_to_grid(gfs, lon, lat, x, y):
    gx, gy = gfs.earth_to_grid(lon, lat)
    assert gx == pytest.approx(x, abs=1e-9)
    assert gy == pytest.approx(y, abs=1e-9)


def test_out_of_range_inputs_return_none(gfs):
    assert gfs.earth_to_grid(361.0, 0.0) is None
    assert gfs.earth_to_grid(0.0, 90.5) is None
    assert gfs.earth_to_grid(0.0, -91.0) is None


def test_point_outside_regional_grid_returns_none():
    grid = LatLonGrid(nx=41, ny=21, lat1=30.0, lon1=140.0, lat2=10.0, lon2=180.0)
    assert grid.earth_to_grid(160.0, 20.0) == pytest.approx((21.0, 11.0))
    assert grid.earth_to_grid(100.0, 20.0) is None  # west of the grid
    assert grid.earth_to_grid(160.0, 50.0) is None  # north of the grid
    # one grid interval outside is still accepted (library convention) ...
    assert grid.earth_to_grid(180.9, 20.0) is not None
    # ... two are not
    assert grid.earth_to_grid(182.5, 20.0) is None


def test_south_to_north_grid():
    grid = LatLonGrid(nx=360, ny=181, lat1=-90.0, lon1=0.0, lat2=90.0, lon2=359.0)
    assert grid.dlat == pytest.approx(1.0)
    assert grid.earth_to_grid(10.0, -80.0) == pytest.approx((11.0, 11.0))


def test_east_to_west_grid():
    template = [6, 0, 0, 0, 0, 0, 0, 360, 181, 0, 0, 90_000_000, 359_000_000, 48,
                -90_000_000, 0, 1_000_000, 1_000_000, 0x80]  # fmt: skip
    grid = LatLonGrid.from_grib2_template(0, template)
    assert grid.i_sign == -1.0
    assert grid.dlon == pytest.approx(-1.0)
    assert grid.earth_to_grid(359.0, 90.0) == pytest.approx((1.0, 1.0))
    assert grid.earth_to_grid(349.0, 80.0) == pytest.approx((11.0, 11.0))


def test_basic_angle_scaling():
    template = synthetic.ONE_DEGREE.template()
    template[9], template[10] = 1, 1000  # coordinates in millidegrees
    for k in (11, 12, 14, 15):
        template[k] //= 1000
    grid = LatLonGrid.from_grib2_template(0, template)
    assert (grid.lat1, grid.lon2) == (90.0, 359.0)


@pytest.mark.parametrize("gdtn", [40, 30, 20, 10, 1])
def test_other_grid_templates_are_rejected(gdtn):
    with pytest.raises(UnsupportedGridError):
        LatLonGrid.from_grib2_template(gdtn, synthetic.ONE_DEGREE.template())


@pytest.mark.parametrize("flag", [0x20, 0x10])
def test_unsupported_scan_modes_are_rejected(flag):
    template = synthetic.ONE_DEGREE.template()
    template[18] = flag
    with pytest.raises(UnsupportedGridError):
        LatLonGrid.from_grib2_template(0, template)


def test_short_template_is_rejected():
    with pytest.raises(UnsupportedGridError):
        LatLonGrid.from_grib2_template(0, [0] * 10)
