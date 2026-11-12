"""Command line interface: ``fbwndgfs`` / ``python -m fbwndgfs``."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Sequence

from . import __version__
from .bulletin import tran_to_text
from .core import run
from .errors import FbwndError

_EPILOG = """\
exit status:
  0   success
  2   bad command line
  10  station list unreadable or malformed            (Fortran: 110)
  60  GRIB2 file unreadable or undecodable            (Fortran: 1050/1060/1090)
  70  unsupported grid                                (Fortran: 1070)
  80  required field not found                        (Fortran: 1080)
  81  fields are not from one model cycle
  82  station outside the grid or on missing data
  83  bulletin does not fit the transmission blocks

example:
  fbwndgfs --stations fbwnd_pacific.stnlist \\
      --f006 gfs.t12z.pres_a.0p25.f006.grib2 gfs.t12z.pres_b.0p25.f006.grib2 \\
      --f012 gfs.t12z.pres_a.0p25.f012.grib2 gfs.t12z.pres_b.0p25.f012.grib2 \\
      --f024 gfs.t12z.pres_a.0p25.f024.grib2 gfs.t12z.pres_b.0p25.f024.grib2 \\
      --output tran.fbwnd_pacific
"""


def _parse_time(text: str) -> dt.datetime:
    for fmt in ("%Y%m%d%H%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%MZ"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"cannot parse {text!r}; use YYYYMMDDHHMM (UTC)")


def _parse_dims(text: str) -> tuple[int, int]:
    try:
        ii, jj = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"cannot parse {text!r}; use IIxJJ, e.g. 1760x880") from None
    if ii < 4 or jj < 4:
        raise argparse.ArgumentTypeError("dimensions must be at least 4x4")
    return ii, jj


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbwndgfs",
        description=(
            "Create the Pacific winds and temperatures aloft bulletins "
            "(FBOC31/33/35/37/38/39) from GFS GRIB2 forecasts."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--stations",
        default="-",
        metavar="FILE",
        help="station list; '-' (default) reads standard input, as the Fortran did",
    )
    for tau in (6, 12, 24):
        p.add_argument(
            f"--f{tau:03d}",
            dest=f"f{tau:03d}",
            nargs="+",
            required=True,
            metavar="GRIB2",
            help=f"GRIB2 file(s) holding the {tau}-hour forecast",
        )
    p.add_argument("-o", "--output", required=True, metavar="FILE", help="transmission file to write")
    p.add_argument(
        "--text",
        metavar="FILE",
        help="also write a plain-text rendering of the bulletins ('-' for standard output)",
    )
    p.add_argument(
        "--transmit-time",
        type=_parse_time,
        metavar="YYYYMMDDHHMM",
        help="UTC time stamp for the WMO headings (default: now)",
    )
    p.add_argument(
        "--legacy-grid-dims",
        type=_parse_dims,
        metavar="IIxJJ",
        help=(
            "reproduce the Fortran executable's fixed interpolation dimensions "
            "(1760x880); for regression testing only, see docs/PORTING_NOTES.md"
        ),
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)],
        format="%(levelname)s %(name)s: %(message)s",
    )
    stations = sys.stdin if args.stations == "-" else args.stations
    try:
        tran = run(
            stations,
            {6: args.f006, 12: args.f012, 24: args.f024},
            output=args.output,
            transmit_time=args.transmit_time,
            legacy_grid_dims=args.legacy_grid_dims,
        )
    except FbwndError as exc:
        print(f"fbwndgfs: error: {exc}", file=sys.stderr)
        return exc.exit_code
    if args.text:
        text = tran_to_text(tran)
        if args.text == "-":
            sys.stdout.write(text)
        else:
            with open(args.text, "w", encoding="ascii") as fh:
                fh.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
