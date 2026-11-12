"""Tables and constants carried over from ``fbwndgfs.F``.

Everything here is a direct transcription of a ``DATA`` statement or a
literal in the Fortran source.  The Fortran name is given next to each item
so the two can be compared line by line.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Forecast hours (KTAU) and unit conversions
# --------------------------------------------------------------------------

#: Forecast projections processed, in hours (``KTAU``).
TAUS: tuple[int, ...] = (6, 12, 24)

#: m/s -> knots factor used by the legacy code.
#:
#: The exact factor is 1.943844.  The Fortran has used 1.94254 since 1986 and
#: the value is kept so the bulletins do not change; it under-reports speed
#: by 0.07 % (0.1 kt at 150 kt).
MS_TO_KT: float = 1.94254

#: Kelvin -> Celsius offset.
KELVIN_OFFSET: float = 273.15

#: Radians -> degrees constant from ``W3FC05`` (``RTOD``).
RTOD: float = 57.2957795

# --------------------------------------------------------------------------
# Levels (IDWD2, NHGT6, NHGTP)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    """One of the 15 bulletin levels."""

    #: Column heading in feet, exactly 5 characters (``NHGT6(N)(1:5)``).
    label: str
    #: ``"height"`` (metres above mean sea level) or ``"pressure"`` (hPa).
    kind: str
    #: Level value: metres for heights, hPa for pressure levels (``IDWD2``).
    value: int
    #: Column advance after the heading is written (``NHGTP``).
    heading_advance: int

    @property
    def grib2_surface_type(self) -> int:
        """GRIB2 code table 4.5 value: 102 = altitude above MSL, 100 = isobaric."""
        return 102 if self.kind == "height" else 100

    @property
    def grib2_surface_value(self) -> float:
        """Level value in GRIB2 units (m, or Pa for isobaric surfaces)."""
        return float(self.value) if self.kind == "height" else float(self.value) * 100.0


LEVELS: tuple[Level, ...] = (
    Level("1000 ", "height", 305, 5),
    Level("1500 ", "height", 457, 5),
    Level("2000 ", "height", 610, 6),
    Level("3000 ", "height", 914, 6),
    Level("6000 ", "height", 1829, 6),
    Level("9000 ", "height", 2743, 6),
    Level("12000", "height", 3658, 6),
    Level("15000", "height", 4572, 6),
    Level("18000", "pressure", 500, 6),
    Level("24000", "pressure", 400, 6),
    Level("30000", "pressure", 300, 5),
    Level("34000", "pressure", 250, 5),
    Level("39000", "pressure", 200, 5),
    Level("45000", "pressure", 150, 5),
    Level("53000", "pressure", 100, 5),
)

NLEVELS: int = len(LEVELS)

#: 0-based, half-open level ranges of the two bulletins issued per forecast
#: hour (``LMTLWR``/``LMTUPR``): levels 1-10 and levels 11-15.
BULLETIN_LEVEL_RANGES: tuple[tuple[int, int], ...] = ((0, 10), (10, 15))

# --------------------------------------------------------------------------
# GRIB parameters (IDWD1H / IDWD1P -> GRIB2 discipline 0)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Parameter:
    """A GRIB parameter read by the program."""

    name: str
    #: GRIB1 parameter number in table 2 (what the Fortran asked ``GETGB`` for).
    grib1_number: int
    #: GRIB2 parameter category / number (discipline 0).
    grib2_category: int
    grib2_number: int


UGRD = Parameter("UGRD", 33, 2, 2)
VGRD = Parameter("VGRD", 34, 2, 3)
TMP = Parameter("TMP", 11, 0, 0)

#: Order matters: it is the ``ITYP`` loop order of the Fortran.
PARAMETERS: tuple[Parameter, ...] = (UGRD, VGRD, TMP)

# --------------------------------------------------------------------------
# Bulletin identification (NFDHDG, NCATNR, AWIPSID)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BulletinId:
    """Identifiers of one of the six bulletins of a run."""

    #: WMO heading TTAAii, e.g. ``FBOC31`` (``'FB' // NFDHDG``).
    wmo_heading: str
    #: Catalog number (``NCATNR``).
    catalog_number: str
    #: AWIPS identifier (``AWIPSID``).
    awips_id: str


#: In run order: (6 h low, 6 h high, 12 h low, 12 h high, 24 h low, 24 h high).
BULLETIN_IDS: tuple[BulletinId, ...] = (
    BulletinId("FBOC31", "1377", "FD1OC1"),
    BulletinId("FBOC37", "5980", "FD8OC7"),
    BulletinId("FBOC33", "1378", "FD3OC3"),
    BulletinId("FBOC38", "5981", "FD9OC8"),
    BulletinId("FBOC35", "1379", "FD5OC5"),
    BulletinId("FBOC39", "5982", "FD0OC9"),
)

#: Originating centre in the WMO heading.
ORIGINATOR: str = "KWNO"

#: Run flag in the catalog field: ``P`` = primary run (``TFLAG``).
RUN_FLAG: str = "P"

#: Model cycles the program accepts (``ICYC`` 1-4).
CYCLE_HOURS: tuple[int, ...] = (0, 6, 12, 18)

#: "FOR USE" period as (start, end) offsets in hours from the cycle time,
#: keyed by forecast hour.  Reproduces the ``NUSETM`` table.
USE_PERIOD_OFFSETS: dict[int, tuple[int, int]] = {6: (2, 9), 12: (9, 18), 24: (18, 30)}

# --------------------------------------------------------------------------
# Transmission control characters
# --------------------------------------------------------------------------
# The "tran" file uses printable stand-ins that the downstream formatter
# (make_ntc_bull.pl) translates or strips.

CRCRLF: str = "<<@"  #: carriage return, carriage return, line feed
ETB: str = ">"  #: end of transmission block
ETX: str = "%"  #: end of bulletin
PLUS: str = "|"  #: plus sign of a temperature (``NNPOS = CHAR(124)``)
MINUS: str = "-"

#: Size of a transmission block and of an output record (``BULTN``/``SPACE``).
BLOCK_SIZE: int = 1280

#: A block is closed with ETB once it holds this many characters.
BLOCK_FLUSH_THRESHOLD: int = 1207

#: Grid dimensions hard-wired in the Fortran (``IMAX``, ``JMAX``): the T574
#: Gaussian grid.  See ``docs/PORTING_NOTES.md`` before using these.
LEGACY_GRID_DIMS: tuple[int, int] = (1760, 880)
