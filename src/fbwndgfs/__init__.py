"""fbwndgfs - GFS winds and temperatures aloft bulletins for the Pacific.

Python replacement for the NCEP Fortran program ``FBWNDGFS`` (Cavanaugh,
1986; Vuong, 2004-2016).  It reads GFS wind and temperature forecasts from
GRIB2 files, interpolates them to a list of stations and writes the FBOC31,
FBOC33, FBOC35, FBOC37, FBOC38 and FBOC39 bulletins as a 1280-byte-record
transmission file.

Typical use::

    import fbwndgfs

    fbwndgfs.run(
        "fbwnd_pacific.stnlist",
        {6: ["pres_a.f006.grib2", "pres_b.f006.grib2"],
         12: ["pres_a.f012.grib2", "pres_b.f012.grib2"],
         24: ["pres_a.f024.grib2", "pres_b.f024.grib2"]},
        output="tran.fbwnd_pacific",
    )
"""

from .bulletin import frame_records, header_times, tran_to_text
from .constants import LEGACY_GRID_DIMS, LEVELS, TAUS
from .core import TauResult, build_tran, interpolate_tau, run
from .errors import (
    BulletinFormatError,
    FbwndError,
    GribReadError,
    InconsistentInputError,
    MissingFieldError,
    StationListError,
    StationOffGridError,
    UnsupportedGridError,
)
from .gribio import ArraySource, Field, Grib2Source
from .grid import LatLonGrid
from .stations import Station, bulletin_groups, read_station_list

__version__ = "1.0.0"

__all__ = [
    "ArraySource",
    "BulletinFormatError",
    "FbwndError",
    "Field",
    "Grib2Source",
    "GribReadError",
    "InconsistentInputError",
    "LEGACY_GRID_DIMS",
    "LEVELS",
    "LatLonGrid",
    "MissingFieldError",
    "Station",
    "StationListError",
    "StationOffGridError",
    "TAUS",
    "TauResult",
    "UnsupportedGridError",
    "build_tran",
    "bulletin_groups",
    "frame_records",
    "header_times",
    "interpolate_tau",
    "read_station_list",
    "run",
    "tran_to_text",
    "__version__",
]
