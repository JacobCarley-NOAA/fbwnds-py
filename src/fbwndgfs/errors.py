"""Exceptions raised by :mod:`fbwndgfs`.

Each class records the fatal condition code of the Fortran program it
replaces (``legacy_code``) and the process exit status the command line
interface uses for it (``exit_code``).  The Fortran codes above 255 cannot
be returned by a POSIX process, which is why the two differ.
"""

from __future__ import annotations


class FbwndError(Exception):
    """Base class for all fbwndgfs errors."""

    legacy_code: int | None = None
    exit_code: int = 1


class StationListError(FbwndError):
    """The station list could not be read or is not usable (legacy 110)."""

    legacy_code = 110
    exit_code = 10


class GribReadError(FbwndError):
    """A GRIB2 file could not be opened or decoded (legacy 1050/1060/1090)."""

    legacy_code = 1060
    exit_code = 60


class UnsupportedGridError(FbwndError):
    """The field is on a grid the program cannot handle (legacy 1070)."""

    legacy_code = 1070
    exit_code = 70


class MissingFieldError(FbwndError):
    """A required field is not in the input files (legacy 1080)."""

    legacy_code = 1080
    exit_code = 80


class InconsistentInputError(FbwndError):
    """The fields do not form one consistent model run (not checked by the Fortran)."""

    exit_code = 81


class StationOffGridError(FbwndError):
    """A station lies outside the model grid or on missing data."""

    exit_code = 82


class BulletinFormatError(FbwndError):
    """A bulletin could not be laid out in 1280-character blocks."""

    exit_code = 83
