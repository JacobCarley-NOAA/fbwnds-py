"""Encoding of interpolated winds and temperatures into bulletin groups.

A winds-aloft group is ``DDff`` followed, on levels that carry a
temperature, by a signed two-digit temperature::

    DD  wind direction in tens of degrees true (01-36)
    ff  wind speed in knots
    TT  temperature in whole degrees Celsius

Special encodings (FAA winds and temperatures aloft convention):

* speed 100-199 kt: 50 is added to ``DD`` and 100 subtracted from ``ff``;
* speed above 199 kt: encoded as 199 kt (``DD + 50``, ``ff = 99``);
* speed below 5 kt: "light and variable", encoded ``9900``.

All arithmetic follows ``fbwndgfs.F`` statement by statement, including the
places where it truncates instead of rounding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import MINUS, PLUS
from .w3emc import fint, w3ai15, w3fc05

WIND_BLANK = " " * 4
TEMP_BLANK = " " * 3


def to_hundredths(x: float) -> int:
    """Store a value as integer hundredths, truncating (``KSTNU = X*100.0``)."""
    return fint(x * 100.0)


def encode_wind(u_hundredths: int, v_hundredths: int) -> str:
    """Encode wind components (hundredths of a knot) as the 4-character ``DDff``."""
    u = float(u_hundredths) * 0.01
    v = float(v_hundredths) * 0.01
    dd, ss = w3fc05(u, v)

    # Direction rounded to the nearest 10 degrees, forced into 1..36.
    nddd = fint((dd + 5.0) / 10.0)
    if nddd > 36 or nddd <= 0:
        nddd = int(math.fmod(nddd, 36))  # Fortran MOD keeps the sign of NDDD
        if nddd <= 0:
            nddd += 36

    # Speed rounded to the nearest knot.
    nsss = fint(ss + 0.5)
    if nsss > 199:
        nsss = 99
        nddd += 50
    elif nsss > 99:
        nsss -= 100
        nddd += 50
    elif nsss < 5:
        nsss = 0
        nddd = 99

    return w3ai15(nddd * 100 + nsss, 4)


def encode_temp(t_hundredths: int) -> str:
    """Encode a temperature (hundredths of a degree C) as sign plus two digits.

    The sign is ``-`` for temperatures of -0.5 C or lower and the
    transmission plus sign (``|``) otherwise.  Values round half away from
    zero.  Only the two low-order digits are kept.
    """
    tt = float(t_hundredths) * 0.01
    nttt = fint(tt)
    if tt <= -0.5:
        nttt = fint(tt - 0.5)
    if tt >= 0.5:
        nttt = fint(tt + 0.5)
    text = w3ai15(nttt, 3, MINUS)
    if tt > -0.5:
        text = PLUS + text[1:]
    return text


@dataclass
class StationLevelData:
    """Interpolated values and their encodings for one station and level."""

    u_kt: float  #: interpolated u component, knots (legacy factor)
    v_kt: float  #: interpolated v component, knots
    temp_c: float  #: interpolated temperature, degrees Celsius
    wind: str  #: 4 characters, blank if suppressed
    temp: str  #: 3 characters (sign + 2 digits), blank if suppressed


def apply_elevation_rules(elevation_ft: int, winds: list[str], temps: list[str]) -> None:
    """Blank the groups that are too close to the terrain (in place).

    ``winds`` and ``temps`` hold the 15 levels in order.

    * Temperatures are never issued for 1000-3000 ft, and are blanked at
      6000/9000/12000 ft when the level is less than 2500 ft above the
      station.
    * Winds are blanked at 3000/6000/9000/12000 ft when the level is less
      than 1500 ft above the station.
    """
    if elevation_ft > 9500:
        temps[6] = TEMP_BLANK
    if elevation_ft > 6500:
        temps[5] = TEMP_BLANK
    if elevation_ft > 3500:
        temps[4] = TEMP_BLANK
    for lvl in range(4):
        temps[lvl] = TEMP_BLANK

    if elevation_ft > 10500:
        winds[6] = WIND_BLANK
    if elevation_ft > 7500:
        winds[5] = WIND_BLANK
    if elevation_ft > 4500:
        winds[4] = WIND_BLANK
    if elevation_ft > 1500:
        winds[3] = WIND_BLANK
