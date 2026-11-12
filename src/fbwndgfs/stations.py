"""Station list (``fbwnd_pacific.stnlist``) reader.

The list is a fixed-column text file.  The Fortran read it from standard
input with ``FORMAT(A1,A1,A4,1X,I5,1X,F6.2,1X,F7.2)``::

    column  1      bulletin marker: 'B' first station of a bulletin,
                   'E' last station, blank otherwise
    column  2      multiple-use flag (read, never used)
    columns 3-6    station identifier
    columns 8-12   station elevation in feet
    columns 14-19  latitude,  degrees north
    columns 21-27  longitude, degrees east (negative = west)
    columns 28-    ignored (free-form comment)

Stations are listed once per bulletin they appear in.  The first ``B``..``E``
group supplies the low-level bulletins (1000 ft to 24000 ft) and the second
group the high-level bulletins (30000 ft to 53000 ft).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import IO, Iterable, Sequence, Union

from .errors import StationListError

PathOrLines = Union[str, os.PathLike, IO[str], Iterable[str]]

_RECORD_WIDTH = 27


@dataclass(frozen=True)
class Station:
    """One record of the station list."""

    indicator: str  #: 'B', 'E' or ' '
    multi_use: str  #: column 2; kept for completeness, not used
    ident: str  #: 4-character identifier, blank padded as in the file
    elevation_ft: int
    lat: float
    lon: float

    @property
    def name(self) -> str:
        """Identifier without padding."""
        return self.ident.strip()


def _read_int(field: str, what: str, lineno: int) -> int:
    """Fortran ``Iw`` edit descriptor: blanks are ignored, all blank is 0."""
    text = field.replace(" ", "")
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        raise StationListError(f"line {lineno}: bad {what} {field!r}") from None


def _read_real(field: str, decimals: int, what: str, lineno: int) -> float:
    """Fortran ``Fw.d`` edit descriptor.

    A field without a decimal point has ``d`` implied decimal places.
    """
    text = field.replace(" ", "")
    if not text:
        return 0.0
    try:
        if any(c in text for c in ".eEdD"):
            return float(text.replace("d", "e").replace("D", "e"))
        return int(text) / (10.0**decimals)
    except ValueError:
        raise StationListError(f"line {lineno}: bad {what} {field!r}") from None


def parse_station_line(line: str, lineno: int = 0) -> Station:
    """Parse one fixed-column station record."""
    rec = line.rstrip("\r\n").expandtabs().ljust(_RECORD_WIDTH)
    return Station(
        indicator=rec[0],
        multi_use=rec[1],
        ident=rec[2:6],
        elevation_ft=_read_int(rec[7:12], "elevation", lineno),
        lat=_read_real(rec[13:19], 2, "latitude", lineno),
        lon=_read_real(rec[20:27], 2, "longitude", lineno),
    )


def read_station_list(source: PathOrLines) -> list[Station]:
    """Read a station list.

    Parameters
    ----------
    source
        A path, an open text file, or any iterable of lines.

    Returns
    -------
    list of Station
        In file order.  Blank lines are skipped.

    Raises
    ------
    StationListError
        If the file cannot be read, a numeric field is malformed, a
        coordinate is out of range, or the list is empty.
    """
    if isinstance(source, (str, os.PathLike)):
        try:
            with open(source, "r", encoding="ascii", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            raise StationListError(f"cannot read station list {source}: {exc}") from exc
    elif isinstance(source, io.IOBase) or hasattr(source, "read"):
        lines = source.read().splitlines()  # type: ignore[union-attr]
    else:
        lines = list(source)

    stations: list[Station] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        stn = parse_station_line(line, lineno)
        if not -90.0 <= stn.lat <= 90.0 or not -360.0 <= stn.lon <= 360.0:
            raise StationListError(
                f"line {lineno}: station {stn.name!r} has an impossible position "
                f"({stn.lat}, {stn.lon})"
            )
        stations.append(stn)
    if not stations:
        raise StationListError("station list is empty")
    return stations


def bulletin_groups(stations: Sequence[Station], count: int = 2) -> list[list[Station]]:
    """Split the list into the station groups of the bulletins.

    A group runs from a station marked ``B`` to the next station marked
    ``E``.  The Fortran walked the list the same way, restarting from the top
    for every forecast hour, so only the first ``count`` groups are ever
    used.

    Raises
    ------
    StationListError
        If fewer than ``count`` complete groups exist or a group does not
        start with ``B``.  (The Fortran ran off the end of its arrays in
        these cases.)
    """
    groups: list[list[Station]] = []
    current: list[Station] = []
    for stn in stations:
        if not current and stn.indicator != "B":
            raise StationListError(
                f"station {stn.name!r} starts bulletin group {len(groups) + 1} "
                "but is not marked 'B' in column 1"
            )
        if current and stn.indicator == "B":
            raise StationListError(
                f"station {stn.name!r} is marked 'B' before the previous bulletin "
                "group was closed with 'E'"
            )
        current.append(stn)
        if stn.indicator == "E":
            groups.append(current)
            current = []
            if len(groups) == count:
                break
    if len(groups) < count:
        raise StationListError(
            f"station list defines {len(groups)} complete bulletin group(s) "
            f"(B ... E); {count} are required"
        )
    return groups
