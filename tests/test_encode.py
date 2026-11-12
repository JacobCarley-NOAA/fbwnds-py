"""Wind and temperature group encoding and the terrain rules."""

import math

import pytest

from fbwndgfs.constants import MS_TO_KT
from fbwndgfs.encode import (
    TEMP_BLANK,
    WIND_BLANK,
    apply_elevation_rules,
    encode_temp,
    encode_wind,
    to_hundredths,
)


def wind(direction_deg: float, speed_kt: float) -> str:
    """Encode a wind given as meteorological direction and speed."""
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return encode_wind(round(u * 100), round(v * 100))


@pytest.mark.parametrize(
    "direction, speed, group",
    [
        (90, 10, "0910"),
        (270, 25, "2725"),
        (180, 7, "1807"),
        (360, 50, "3650"),
        (0.5, 50, "3650"),  # north is 36, never 00
        (4.9, 50, "3650"),
        (5.1, 50, "0150"),
        (354.9, 50, "3550"),
        (355.1, 50, "3650"),
        (14.9, 12, "0112"),
        (15.1, 12, "0212"),
        (230, 99, "2399"),
        (230, 100, "7300"),  # 100-199 kt: DD + 50, ff - 100
        (230, 145, "7345"),
        (230, 199, "7399"),
        (230, 200, "7399"),  # above 199 kt: reported as 199
        (230, 260, "7399"),
        (360, 150, "8650"),
        (10, 105, "5105"),
    ],
)
def test_encode_wind(direction, speed, group):
    assert wind(direction, speed) == group


@pytest.mark.parametrize("speed, group", [(0.0, "9900"), (3.0, "9900"), (4.49, "9900"), (4.51, "2705"), (5.0, "2705")])
def test_light_and_variable_below_five_knots(speed, group):
    assert wind(270, speed) == group


def test_speed_rounds_half_up():
    assert wind(270, 24.49) == "2724"
    assert wind(270, 24.50) == "2725"
    assert wind(270, 99.49) == "2799"
    assert wind(270, 99.50) == "7700"


def test_to_hundredths_truncates():
    assert to_hundredths(12.349) == 1234
    assert to_hundredths(-12.349) == -1234
    assert to_hundredths(0.009) == 0
    assert to_hundredths(-0.009) == 0


def test_legacy_knots_factor():
    # 51.48 m/s is 100.07 kt; the legacy factor gives 100.00
    assert to_hundredths(51.48 * MS_TO_KT) == 10000
    assert MS_TO_KT == 1.94254


@pytest.mark.parametrize(
    "celsius, group",
    [
        (0.0, "|00"),
        (0.49, "|00"),
        (0.5, "|01"),
        (-0.49, "|00"),  # rounds to zero: shown as plus
        (-0.5, "-01"),
        (-1.49, "-01"),
        (-1.5, "-02"),
        (12.5, "|13"),
        (-12.5, "-13"),
        (-56.0, "-56"),
        (37.2, "|37"),
        (99.4, "|99"),
        (-99.4, "-99"),
        (103.0, "|03"),  # only two digits are kept
        (-103.0, "-03"),
    ],
)
def test_encode_temp(celsius, group):
    assert encode_temp(round(celsius * 100)) == group


def _all_levels():
    return [f"W{k:03d}" for k in range(15)], [f"T{k:02d}" for k in range(15)]


@pytest.mark.parametrize(
    "elev, blank_winds, blank_temps",
    [
        (0, [], [0, 1, 2, 3]),
        (1500, [], [0, 1, 2, 3]),
        (1501, [3], [0, 1, 2, 3]),
        (3500, [3], [0, 1, 2, 3]),
        (3501, [3], [0, 1, 2, 3, 4]),
        (4500, [3], [0, 1, 2, 3, 4]),
        (4501, [3, 4], [0, 1, 2, 3, 4]),
        (6500, [3, 4], [0, 1, 2, 3, 4]),
        (6501, [3, 4], [0, 1, 2, 3, 4, 5]),
        (7500, [3, 4], [0, 1, 2, 3, 4, 5]),
        (7501, [3, 4, 5], [0, 1, 2, 3, 4, 5]),
        (9500, [3, 4, 5], [0, 1, 2, 3, 4, 5]),
        (9501, [3, 4, 5], [0, 1, 2, 3, 4, 5, 6]),
        (10500, [3, 4, 5], [0, 1, 2, 3, 4, 5, 6]),
        (10501, [3, 4, 5, 6], [0, 1, 2, 3, 4, 5, 6]),
        (20000, [3, 4, 5, 6], [0, 1, 2, 3, 4, 5, 6]),
        (-5, [], [0, 1, 2, 3]),
    ],
)
def test_elevation_rules(elev, blank_winds, blank_temps):
    winds, temps = _all_levels()
    apply_elevation_rules(elev, winds, temps)
    assert [k for k, w in enumerate(winds) if w == WIND_BLANK] == blank_winds
    assert [k for k, t in enumerate(temps) if t == TEMP_BLANK] == blank_temps
    # untouched entries keep their value
    assert all(w == f"W{k:03d}" for k, w in enumerate(winds) if k not in blank_winds)
