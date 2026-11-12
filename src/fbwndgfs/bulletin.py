"""Bulletin text layout and the 1280-byte transmission ("tran") file.

The output is the NCEP transmission-file format consumed by
``make_ntc_bull.pl``.  Printable stand-ins are used for control characters:

=====  ==========================================
``<<@``  carriage return, carriage return, line feed
``^``    padding / shift character
``$``    start-of-line marker
``|``    plus sign
``>``    end of a 1280-character transmission block (ETB)
``%``    end of bulletin (ETX)
``'``    start of the bulletin catalog header
=====  ==========================================

Layout of one bulletin (``<<@`` shown as line breaks)::

    '101377PFB                              FBOC31 KWNO 120116<<@
    ^^^FD1OC1<<@
    $DATA BASED ON 111200Z    <<@
    VALID 111800Z   FOR USE 1400-2100Z. TEMPS NEG ABV 24000<<@
    @^FT  1000 1500 2000 3000    6000    9000   12000   15000   18000   24000<<@
    $JON 2254 2254 2254 2254 2254|08 2254|08 2254|08 2254|08 2254|08 2254|08<<@
    ...
    %
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from .constants import (
    BLOCK_FLUSH_THRESHOLD,
    BLOCK_SIZE,
    BULLETIN_IDS,
    CRCRLF,
    CYCLE_HOURS,
    ETB,
    ETX,
    LEVELS,
    ORIGINATOR,
    RUN_FLAG,
    TAUS,
    USE_PERIOD_OFFSETS,
    BulletinId,
)
from .errors import BulletinFormatError, InconsistentInputError
from .w3emc import w3ai15

# --------------------------------------------------------------------------
# Header times
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HeaderTimes:
    """Date/time groups that appear in a bulletin heading."""

    transmit: str  #: ``DDHHMM`` the bulletin was created (UTC wall clock)
    base: str  #: ``DDHHMM`` of the model cycle
    valid: str  #: ``DDHHMM`` the forecast is valid
    use_period: str  #: ``HHMM-HHMM`` period of use


def header_times(cycle: dt.datetime, tau: int, transmit: dt.datetime) -> HeaderTimes:
    """Work out the heading date/time groups.

    Parameters
    ----------
    cycle
        Model reference time; must be a 00, 06, 12 or 18 UTC cycle.
    tau
        Forecast hour: 6, 12 or 24.
    transmit
        Time stamp for the WMO heading (UTC).

    Notes
    -----
    The Fortran looked the valid time and period of use up in tables
    (``NVALTM``/``NUSETM``) indexed by cycle and forecast hour and derived
    the valid day with a set of special cases.  Those tables are plain
    offsets from the cycle time, which is what is computed here; the unit
    tests check the result against the original tables.
    """
    if cycle.hour not in CYCLE_HOURS or cycle.minute or cycle.second:
        raise InconsistentInputError(
            f"model cycle {cycle:%Y-%m-%d %H:%M} is not a 00/06/12/18 UTC cycle"
        )
    if tau not in USE_PERIOD_OFFSETS:
        raise ValueError(f"unsupported forecast hour {tau}; expected one of {TAUS}")
    valid = cycle + dt.timedelta(hours=tau)
    start, end = USE_PERIOD_OFFSETS[tau]
    use_start = cycle + dt.timedelta(hours=start)
    use_end = cycle + dt.timedelta(hours=end)
    return HeaderTimes(
        transmit=w3ai15(transmit.day, 2) + f"{transmit.hour:02d}{transmit.minute:02d}",
        base=w3ai15(cycle.day, 2) + w3ai15(cycle.hour * 100, 4),
        valid=w3ai15(valid.day, 2) + f"{valid.hour:02d}00",
        use_period=f"{use_start.hour:02d}00-{use_end.hour:02d}00",
    )


# --------------------------------------------------------------------------
# Lines
# --------------------------------------------------------------------------


def catalog_header(ident: BulletinId, times: HeaderTimes) -> str:
    """The 74-character catalog + WMO + AWIPS heading (``NBULHD``)."""
    line = (
        f"'10{ident.catalog_number}{RUN_FLAG}FB".ljust(40)
        + f"{ident.wmo_heading} {ORIGINATOR} {times.transmit}{CRCRLF}"
        + f"^^^{ident.awips_id}{CRCRLF}$"
    )
    assert len(line) == 74, len(line)
    return line


def base_time_line(times: HeaderTimes) -> str:
    """``DATA BASED ON ddhhmmZ`` (first 28 characters of ``NBASHD``)."""
    line = f"DATA BASED ON {times.base}Z    {CRCRLF}"
    assert len(line) == 28, len(line)
    return line


def valid_time_line(times: HeaderTimes) -> str:
    """``VALID ddhhmmZ FOR USE hhmm-hhmmZ ...`` (``NVALHD``, 60 characters)."""
    line = f"VALID {times.valid}Z   FOR USE {times.use_period}Z. TEMPS NEG ABV 24000{CRCRLF}@^"
    assert len(line) == 60, len(line)
    return line


def level_heading(first: int, last: int) -> str:
    """The ``FT`` column heading for levels ``first`` .. ``last - 1`` (0-based).

    The column arithmetic is the ``DO 4500`` loop of the Fortran; it lines
    the headings up with the data groups, which are 5 characters wide on
    levels without a temperature, 8 with a signed temperature and 7 with an
    unsigned one.
    """
    line = [" "] * 73
    line[0:2] = "FT"
    npos1 = 5
    npos2 = npos1
    for n in range(first + 1, last + 1):  # n is the 1-based Fortran level
        if n <= 3:
            pass
        elif n == 4:
            npos1 -= 1
        elif 5 <= n <= 6:
            npos1 += 2
        elif n in (7, 11):
            npos1 += 1
        elif n > 7:
            npos1 += 2
        npos2 = npos1 + 4
        line[npos1 - 1 : npos2] = LEVELS[n - 1].label
        npos1 += LEVELS[n - 1].heading_advance
    return "".join(line[:npos2])


def station_line(ident: str, winds: Sequence[str], temps: Sequence[str], first: int, last: int) -> str:
    """One data line: ``$`` + station id + the groups for the given levels.

    ``winds``/``temps`` hold all 15 levels.  Levels 5-10 carry a signed
    temperature, levels 11-15 an unsigned one (always negative up there),
    levels 1-4 none.
    """
    groups = []
    for m in range(first + 1, last + 1):  # 1-based level
        group = winds[m - 1][:4]
        if 4 < m <= 10:
            group += temps[m - 1][:3]
        if m > 10:
            group += temps[m - 1][1:3]
        groups.append(group)
    # The identifier occupies columns 2-5 and the first group starts in
    # column 6: there is no separator after a 4-character identifier.
    return "$" + ident[:4].ljust(4) + " ".join(groups)


# --------------------------------------------------------------------------
# Blocking and record framing
# --------------------------------------------------------------------------


class TranStream:
    """Accumulates bulletins as a stream of transmission blocks.

    Reproduces the ``WXAI19`` line blocker as the Fortran drives it: a block
    holds at most :data:`BLOCK_SIZE` characters; before a station line is
    added to a block that already holds :data:`BLOCK_FLUSH_THRESHOLD` or
    more, the block is closed with ETB and a new one is started.  A bulletin
    ends with ETX.
    """

    def __init__(self) -> None:
        self._stream: list[str] = []
        self._block: list[str] = []
        self._block_len = 0

    def _put(self, text: str) -> None:
        if self._block_len + len(text) > BLOCK_SIZE:
            # WXAI19 would return NEXT = -1 and the Fortran would silently
            # drop the rest of the bulletin.  With the fixed line lengths of
            # these bulletins this cannot happen.
            raise BulletinFormatError(
                f"line of {len(text)} characters does not fit in the "
                f"{BLOCK_SIZE}-character transmission block"
            )
        self._block.append(text)
        self._block_len += len(text)

    def _flush(self) -> None:
        self._stream.extend(self._block)
        self._block = []
        self._block_len = 0

    def begin_bulletin(self, header_lines: Sequence[str]) -> None:
        self._block = []
        self._block_len = 0
        for line in header_lines:
            self._put(line)

    def add_station_line(self, line: str) -> None:
        if self._block_len >= BLOCK_FLUSH_THRESHOLD:
            self._put(ETB)
            self._flush()
        self._put(line)
        self._put(CRCRLF)

    def end_bulletin(self) -> None:
        self._put(ETX)
        self._flush()

    @property
    def text(self) -> str:
        """The unframed character stream written so far."""
        return "".join(self._stream)

    def to_records(self) -> bytes:
        """Frame the stream as fixed-length records for the tran file."""
        return frame_records(self.text)


def frame_records(stream: str) -> bytes:
    """Cut a character stream into 1280-byte records, each followed by LF.

    The last record is padded with blanks.  As in the Fortran, a final
    record is always written, so a stream whose length is an exact multiple
    of 1280 is followed by one all-blank record.
    """
    data = stream.encode("ascii")
    nrec = len(data) // BLOCK_SIZE + 1
    out = bytearray()
    for k in range(nrec):
        out += data[k * BLOCK_SIZE : (k + 1) * BLOCK_SIZE].ljust(BLOCK_SIZE, b" ")
        out += b"\n"
    return bytes(out)


def bulletin_id(tau_index: int, part: int) -> BulletinId:
    """Identifiers of bulletin ``part`` (0 = low levels, 1 = high) of a forecast hour."""
    return BULLETIN_IDS[2 * tau_index + part]


def tran_to_text(tran: bytes | str) -> str:
    """Render a tran file as plain text for people to read.

    Record framing and control stand-ins are removed, ``|`` becomes ``+`` and
    each bulletin starts at its WMO heading.  This is a reading aid; the
    operational conversion is done by ``make_ntc_bull.pl``.
    """
    if isinstance(tran, bytes):
        tran = tran.decode("ascii", errors="replace")
    text = tran.replace("\n", "")
    bulletins = []
    for chunk in text.split(ETX):
        start = chunk.find("'1")
        if start < 0:
            continue
        body = chunk[start + 40 :]
        body = body.replace("<<@@", "\n").replace(CRCRLF, "\n")
        for ch in (ETB, "^", "$"):
            body = body.replace(ch, "")
        lines = [line.rstrip() for line in body.replace("|", "+").split("\n")]
        bulletins.append("\n".join(lines).rstrip() + "\n")
    return "\n".join(bulletins)
