"""Regular latitude/longitude grid geometry.

Replaces the ``GDSWZD_GRIB1`` call (NCEPLIBS-ip) that the Fortran used to
turn a station's longitude/latitude into fractional grid coordinates.  The
arithmetic follows ``ip_equid_cylind_grid_mod`` so the coordinates agree
with the library to rounding error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .errors import UnsupportedGridError

#: Offset in the ``DLON`` expression of NCEPLIBS-ip ``ip_equid_cylind_grid_mod``.
#:
#: Released NCEPLIBS-ip (through v5.4.1) uses 1; the unreleased develop
#: branch changed it to 1e-2 (``DLON_OFFSET``).  The two are equal in exact
#: arithmetic but round differently in the last bit, which can move an
#: interpolated value across a rounding boundary.  The released form is used
#: because that is what operational executables link.
_DLON_OFFSET = 1.0


def _fmod(a: float, b: float) -> float:
    """Fortran ``MOD`` for reals (result takes the sign of ``a``)."""
    return math.fmod(a, b)


@dataclass(frozen=True)
class LatLonGrid:
    """An equidistant cylindrical (regular lat/lon) grid.

    Grid coordinates are 1-based and follow the storage order of the field:
    ``x`` increases along a row in the direction the points are stored,
    ``y`` increases from the first stored row to the last.
    """

    nx: int
    ny: int
    lat1: float  #: latitude of the first grid point (degrees north)
    lon1: float  #: longitude of the first grid point (degrees east)
    lat2: float  #: latitude of the last grid point
    lon2: float  #: longitude of the last grid point
    i_sign: float = 1.0  #: +1 if points run west to east along a row, else -1

    # -- derived spacing (same expressions as NCEPLIBS-ip) ------------------

    @property
    def dlon(self) -> float:
        """Signed longitude increment between adjacent points in a row."""
        hi = self.i_sign
        span = _fmod(hi * (self.lon2 - self.lon1) - _DLON_OFFSET + 3600.0, 360.0) + _DLON_OFFSET
        return hi * span / (self.nx - 1)

    @property
    def dlat(self) -> float:
        """Signed latitude increment between adjacent rows."""
        return (self.lat2 - self.lat1) / (self.ny - 1)

    @property
    def is_global_in_longitude(self) -> bool:
        return self.nx == round(360.0 / abs(self.dlon))

    # -- constructors -------------------------------------------------------

    @classmethod
    def from_grib2_template(cls, gdtn: int, gdt: Sequence[int]) -> "LatLonGrid":
        """Build the grid from a GRIB2 grid definition template.

        Only template 3.0 (latitude/longitude) with rows stored consecutively
        is supported; that is what the GFS ``pres_a``/``pres_b`` 0.25 degree
        files use.
        """
        if int(gdtn) != 0:
            raise UnsupportedGridError(
                f"GRIB2 grid definition template 3.{int(gdtn)} is not supported; "
                "only 3.0 (regular latitude/longitude) is."
            )
        gdt = [int(v) for v in gdt]
        if len(gdt) < 19:
            raise UnsupportedGridError("grid definition template 3.0 needs 19 values")
        scan = gdt[18]
        if scan & 0x20:
            raise UnsupportedGridError("grids stored column by column (scan flag 32) are not supported")
        if scan & 0x10:
            raise UnsupportedGridError("boustrophedonic grids (scan flag 16) are not supported")
        scale = gdt[9] * gdt[10]
        if scale == 0:
            scale = 10**6
        return cls(
            nx=gdt[7],
            ny=gdt[8],
            lat1=float(gdt[11]) / float(scale),
            lon1=float(gdt[12]) / float(scale),
            lat2=float(gdt[14]) / float(scale),
            lon2=float(gdt[15]) / float(scale),
            i_sign=-1.0 if scan & 0x80 else 1.0,
        )

    # -- coordinate transform -------------------------------------------------

    def earth_to_grid(self, lon: float, lat: float) -> tuple[float, float] | None:
        """Return the fractional grid coordinates ``(x, y)`` of a point.

        Mirrors ``GDSWZD`` with ``IOPT = -1``.  Longitude may be given in
        either the -180..180 or the 0..360 convention.  ``None`` is returned
        when the point is not on the grid (the library returns its fill
        value there).
        """
        if not (abs(lon) <= 360.0 and abs(lat) <= 90.0):
            return None
        hi = self.i_sign
        x = 1.0 + hi * _fmod(hi * (lon - self.lon1) + 3600.0, 360.0) / self.dlon
        y = 1.0 + (lat - self.lat1) / self.dlat
        xmin, xmax = 0.0, float(self.nx + 1)
        if self.is_global_in_longitude:
            xmax = float(self.nx + 2)
        ymin, ymax = 0.0, float(self.ny + 1)
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return x, y
        return None
