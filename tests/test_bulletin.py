"""Bulletin headings, data lines, blocking and record framing."""

import datetime as dt

import pytest

from fbwndgfs.bulletin import (
    HeaderTimes,
    TranStream,
    base_time_line,
    bulletin_id,
    catalog_header,
    frame_records,
    header_times,
    level_heading,
    station_line,
    tran_to_text,
    valid_time_line,
)
from fbwndgfs.constants import BULLETIN_IDS
from fbwndgfs.errors import BulletinFormatError, InconsistentInputError

# ---- tables copied verbatim from the DATA statements of fbwndgfs.F ----------
NVALTM = ["0600", "1200", "0000", "1200", "1800", "0600",
          "1800", "0000", "1200", "0000", "0600", "1800"]  # fmt: skip
NUSETM = ["0200-0900", "0900-1800", "1800-0600",
          "0800-1500", "1500-0000", "0000-1200",
          "1400-2100", "2100-0600", "0600-1800",
          "2000-0300", "0300-1200", "1200-0000"]  # fmt: skip


def legacy_valid_day(cycle: dt.datetime, icyc: int, t: int) -> int:
    """The IVLDAY logic of the Fortran (primary run branch); icyc, t are 1-based."""
    ndate = cycle.replace(hour=0) + dt.timedelta(days=1)
    ivlday = cycle.day
    if t == 3:
        ivlday = ndate.day
    if icyc == 3 and t == 2:
        ivlday = ndate.day
    if icyc == 4:
        ivlday = ndate.day
    return ivlday


@pytest.mark.parametrize("day", [dt.date(2026, 11, 11), dt.date(2027, 2, 28), dt.date(2028, 2, 29),
                                 dt.date(2026, 12, 31), dt.date(2026, 4, 30)])  # fmt: skip
@pytest.mark.parametrize("icyc", [1, 2, 3, 4])
@pytest.mark.parametrize("t", [1, 2, 3])
def test_header_times_match_legacy_tables(day, icyc, t):
    cycle = dt.datetime(day.year, day.month, day.day, (icyc - 1) * 6)
    tau = (6, 12, 24)[t - 1]
    times = header_times(cycle, tau, dt.datetime(2030, 1, 5, 3, 7))
    iitau = (icyc - 1) * 3 + t
    assert times.valid == f"{legacy_valid_day(cycle, icyc, t):02d}{NVALTM[iitau - 1]}"
    assert times.use_period == NUSETM[iitau - 1]
    assert times.base == f"{cycle.day:02d}{cycle.hour:02d}00"
    assert times.transmit == "050307"


def test_header_times_rejects_off_cycle_and_bad_tau():
    with pytest.raises(InconsistentInputError):
        header_times(dt.datetime(2026, 1, 1, 3), 6, dt.datetime(2026, 1, 1))
    with pytest.raises(InconsistentInputError):
        header_times(dt.datetime(2026, 1, 1, 6, 30), 6, dt.datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        header_times(dt.datetime(2026, 1, 1, 6), 18, dt.datetime(2026, 1, 1))


TIMES = HeaderTimes(transmit="120116", base="111200", valid="111800", use_period="1400-2100")


def test_heading_lines():
    assert catalog_header(BULLETIN_IDS[0], TIMES) == (
        "'101377PFB" + " " * 30 + "FBOC31 KWNO 120116<<@^^^FD1OC1<<@$"
    )
    assert catalog_header(BULLETIN_IDS[5], TIMES).startswith("'105982PFB ")
    assert "FBOC39 KWNO 120116<<@^^^FD0OC9<<@$" in catalog_header(BULLETIN_IDS[5], TIMES)
    assert base_time_line(TIMES) == "DATA BASED ON 111200Z    <<@"
    assert valid_time_line(TIMES) == "VALID 111800Z   FOR USE 1400-2100Z. TEMPS NEG ABV 24000<<@@^"


def test_bulletin_order():
    assert [b.wmo_heading for b in BULLETIN_IDS] == ["FBOC31", "FBOC37", "FBOC33", "FBOC38", "FBOC35", "FBOC39"]
    assert bulletin_id(0, 0).wmo_heading == "FBOC31"
    assert bulletin_id(0, 1).wmo_heading == "FBOC37"
    assert bulletin_id(2, 0).awips_id == "FD5OC5"
    assert bulletin_id(2, 1).catalog_number == "5982"


def test_level_headings():
    assert level_heading(0, 10) == (
        "FT  1000 1500 2000 3000    6000    9000   12000   15000   18000   24000"
    )
    assert level_heading(10, 15) == "FT   30000  34000  39000  45000  53000"


def test_station_lines():
    winds = [f"{k:02d}{k:02d}" for k in range(1, 16)]
    temps = [f"-{k:02d}" for k in range(1, 16)]
    low = station_line("ABC ", winds, temps, 0, 10)
    high = station_line("ABC ", winds, temps, 10, 15)
    assert low == "$ABC 0101 0202 0303 0404 0505-05 0606-06 0707-07 0808-08 0909-09 1010-10"
    assert high == "$ABC 111111 121212 131313 141414 151515"


def test_station_line_details():
    winds = ["9900"] * 15
    temps = ["|05"] * 15
    assert station_line("T11 ", winds, temps, 0, 10).startswith("$T11 9900 9900")
    # 4-character identifier: no separator before the first group (as in the Fortran)
    assert station_line("WXYZ", winds, temps, 10, 15).startswith("$WXYZ990005 990005")
    assert station_line("AB", winds, temps, 10, 15).startswith("$AB  990005")
    # blanked groups keep the columns
    winds[3] = "    "
    temps[4] = "   "
    line = station_line("ABC ", winds, temps, 0, 10)
    assert line[:36] == "$ABC 9900 9900 9900      9900    990"
    assert len(line) == 72
    assert len(station_line("ABC ", winds, temps, 10, 15)) == 39


# ---- blocking -----------------------------------------------------------------
def test_stream_single_block_bulletin():
    s = TranStream()
    s.begin_bulletin(["HEAD<<@"])
    s.add_station_line("$AAA 1")
    s.add_station_line("$BBB 2")
    s.end_bulletin()
    assert s.text == "HEAD<<@$AAA 1<<@$BBB 2<<@%"


def test_stream_inserts_etb_once_block_reaches_threshold():
    s = TranStream()
    s.begin_bulletin(["H" * 236])
    line = "L" * 73
    for _ in range(15):
        s.add_station_line(line)
    s.end_bulletin()
    text = s.text
    # 236 + 13 * 76 = 1224 >= 1207 -> ETB goes in before the 14th line
    assert text.count(">") == 1
    assert text.index(">") == 236 + 13 * 76
    assert text.endswith("<<@%")
    assert len(text) == 236 + 15 * 76 + 2


def test_stream_threshold_is_inclusive():
    s = TranStream()
    s.begin_bulletin(["H" * 1206])
    s.add_station_line("A" * 10)  # 1206 < 1207: no ETB
    s.add_station_line("B" * 10)  # block now 1219 -> ETB first
    s.end_bulletin()
    assert s.text == "H" * 1206 + "A" * 10 + "<<@>" + "B" * 10 + "<<@%"
    s = TranStream()
    s.begin_bulletin(["H" * 1207])
    s.add_station_line("A")
    s.end_bulletin()
    assert s.text == "H" * 1207 + ">A<<@%"


def test_stream_overflow_is_an_error():
    s = TranStream()
    s.begin_bulletin(["H" * 1200])
    with pytest.raises(BulletinFormatError):
        s.add_station_line("L" * 90)


def test_frame_records():
    out = frame_records("A" * 1500)
    assert len(out) == 2 * 1281
    assert out[:1280] == b"A" * 1280 and out[1280:1281] == b"\n"
    assert out[1281:] == b"A" * 220 + b" " * 1060 + b"\n"
    # exact multiple of 1280: the Fortran still writes a final (blank) record
    out = frame_records("B" * 2560)
    assert len(out) == 3 * 1281
    assert out[2 * 1281 :] == b" " * 1280 + b"\n"
    assert frame_records("") == b" " * 1280 + b"\n"


def test_tran_to_text():
    s = TranStream()
    for ident in BULLETIN_IDS[:2]:
        s.begin_bulletin([catalog_header(ident, TIMES), base_time_line(TIMES), valid_time_line(TIMES),
                          level_heading(10, 15), "<<@"])  # fmt: skip
        s.add_station_line("$JON 236200 9900|5")
        s.end_bulletin()
    text = tran_to_text(s.to_records())
    assert text.splitlines()[:5] == [
        "FBOC31 KWNO 120116",
        "FD1OC1",
        "DATA BASED ON 111200Z",
        "VALID 111800Z   FOR USE 1400-2100Z. TEMPS NEG ABV 24000",
        "FT   30000  34000  39000  45000  53000",
    ]
    assert "JON 236200 9900+5" in text
    assert text.count("FBOC37 KWNO") == 1
    assert tran_to_text(s.text) == text
