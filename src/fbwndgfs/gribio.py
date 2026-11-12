"""GRIB2 input through `grib2io <https://github.com/NOAA-MDL/grib2io>`_.

grib2io decodes messages with the NCEPLIBS-g2c library, so this module is
the Python counterpart of the ``GETGB`` calls in the Fortran.  The Fortran
needed GRIB1 input, which the operational script produced from the GFS
GRIB2 files with ``wgrib2 | cnvgrib -g21 | grbindex``.  Reading GRIB2
directly makes those three steps unnecessary.

The module imports grib2io lazily so the rest of the package (station
parsing, interpolation, encoding, bulletin layout) can be used and tested
without it.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

import numpy as np

from .constants import Level, Parameter
from .errors import FbwndError, GribReadError, MissingFieldError
from .grid import LatLonGrid

log = logging.getLogger(__name__)

#: (category, number, surface type, surface value, forecast hour)
FieldKey = tuple[int, int, int, float, int]


@dataclass
class Field:
    """A decoded 2-D field and the metadata the program needs."""

    values: np.ndarray  #: float64, shape (ny, nx), in file storage order
    grid: LatLonGrid
    reference_time: dt.datetime
    description: str = ""


class FieldSource(Protocol):
    """Anything that can supply the fields of one forecast hour."""

    def get(self, param: Parameter, level: Level, tau: int) -> Field:
        """Return the field or raise :class:`MissingFieldError`."""
        ...


def _code(value: Any) -> int:
    """Integer value of a grib2io metadata attribute (plain int or table entry)."""
    return int(getattr(value, "value", value))


def field_key(param: Parameter, level: Level, tau: int) -> FieldKey:
    return (
        param.grib2_category,
        param.grib2_number,
        level.grib2_surface_type,
        level.grib2_surface_value,
        tau,
    )


def describe(param: Parameter, level: Level, tau: int) -> str:
    where = f"{level.value} m above mean sea level" if level.kind == "height" else f"{level.value} mb"
    return f"{param.name}:{where}:{tau} hour fcst"


class Grib2Source:
    """Fields from one or more GRIB2 files.

    Parameters
    ----------
    paths
        GRIB2 files to search, in priority order.  For the GFS both the
        ``pres_a`` and the ``pres_b`` file of a forecast hour are needed:
        ``pres_b`` holds the 305, 457, 610, 914 and 4572 m levels.

    Notes
    -----
    A message matches when it is a meteorological product (discipline 0) in
    product definition template 4.0 (analysis or forecast at a point in
    time) with the requested parameter, first fixed surface and forecast
    time.  The first match in file order is used, as ``GETGB`` did.
    Only the message headers are read up front; a field is decoded when it
    is requested.
    """

    def __init__(self, paths: Sequence[str | os.PathLike] | str | os.PathLike) -> None:
        try:
            import grib2io  # noqa: PLC0415 - optional at import time
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise GribReadError(
                "grib2io is required to read GRIB2 files "
                "(pip install grib2io; needs NCEPLIBS-g2c)"
            ) from exc

        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        self.paths = [os.fspath(p) for p in paths]
        if not self.paths:
            raise GribReadError("no GRIB2 files given")
        self._files = []
        self._index: dict[FieldKey, Any] = {}
        for path in self.paths:
            try:
                fh = grib2io.open(path, mode="r")
            except Exception as exc:  # grib2io raises several types
                self.close()
                raise GribReadError(f"cannot open GRIB2 file {path}: {exc}") from exc
            self._files.append(fh)
            nmsg = 0
            for msg in fh:
                nmsg += 1
                key = self._key_of(msg)
                if key is not None:
                    self._index.setdefault(key, msg)
            log.debug("%s: %d messages indexed", path, nmsg)
            if nmsg == 0:
                self.close()
                raise GribReadError(f"{path} contains no GRIB2 messages")

    @staticmethod
    def _key_of(msg: Any) -> FieldKey | None:
        try:
            if _code(msg.discipline) != 0 or _code(msg.pdtn) != 0:
                return None
            lead = msg.leadTime
            hours = lead.total_seconds() / 3600.0
            if hours != int(hours):
                return None
            return (
                _code(msg.parameterCategory),
                _code(msg.parameterNumber),
                _code(msg.typeOfFirstFixedSurface),
                float(msg.valueOfFirstFixedSurface),
                int(hours),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def get(self, param: Parameter, level: Level, tau: int) -> Field:
        msg = self._index.get(field_key(param, level, tau))
        if msg is None:
            raise MissingFieldError(
                f"record not found: {describe(param, level, tau)} in {', '.join(self.paths)}"
            )
        try:
            grid = LatLonGrid.from_grib2_template(_code(msg.gdtn), msg.gridDefinitionTemplate)
            data = np.ma.filled(np.ma.asarray(msg.data, dtype=np.float64), np.nan)
            ref = msg.refDate
        except FbwndError:
            raise
        except Exception as exc:  # grib2io / g2c decode failure
            raise GribReadError(f"cannot decode {describe(param, level, tau)}: {exc}") from exc
        finally:
            # Release the decoded array held by the message object.
            flush = getattr(msg, "flush_data", None)
            if callable(flush):
                flush()
        if data.shape != (grid.ny, grid.nx):
            raise GribReadError(
                f"{describe(param, level, tau)}: decoded shape {data.shape} does not match "
                f"grid {grid.ny} x {grid.nx}"
            )
        return Field(values=data, grid=grid, reference_time=ref, description=describe(param, level, tau))

    def close(self) -> None:
        for fh in self._files:
            try:
                fh.close()
            except Exception:  # pragma: no cover - best effort
                pass
        self._files = []
        self._index = {}

    def __enter__(self) -> "Grib2Source":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ArraySource:
    """Fields held in memory; used by tests and for driving the program
    from data that is not in GRIB2 files."""

    def __init__(self, grid: LatLonGrid, reference_time: dt.datetime) -> None:
        self.grid = grid
        self.reference_time = reference_time
        self._fields: dict[FieldKey, np.ndarray] = {}

    def add(self, param: Parameter, level: Level, tau: int, values: np.ndarray) -> None:
        values = np.asarray(values, dtype=np.float64)
        if values.shape != (self.grid.ny, self.grid.nx):
            raise ValueError(f"expected shape {(self.grid.ny, self.grid.nx)}, got {values.shape}")
        self._fields[field_key(param, level, tau)] = values

    def get(self, param: Parameter, level: Level, tau: int) -> Field:
        try:
            values = self._fields[field_key(param, level, tau)]
        except KeyError:
            raise MissingFieldError(f"record not found: {describe(param, level, tau)}") from None
        return Field(values, self.grid, self.reference_time, describe(param, level, tau))

    def close(self) -> None:  # symmetry with Grib2Source
        pass


def required_fields(taus: Iterable[int]) -> list[tuple[Parameter, Level, int]]:
    """All (parameter, level, forecast hour) combinations the program reads."""
    from .constants import LEVELS, PARAMETERS  # noqa: PLC0415

    return [(p, lvl, tau) for tau in taus for p in PARAMETERS for lvl in LEVELS]
