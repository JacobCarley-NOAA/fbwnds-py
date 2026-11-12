"""Station list reader."""

import io

import pytest

from fbwndgfs.errors import StationListError
from fbwndgfs.stations import Station, bulletin_groups, parse_station_line, read_station_list


def test_operational_list(pacific_stnlist):
    stations = read_station_list(pacific_stnlist)
    assert len(stations) == 30
    jon = stations[0]
    assert jon == Station("B", " ", "JON ", 7, 16.72, -169.53)
    assert jon.name == "JON"
    assert stations[14].indicator == "E" and stations[14].name == "T11"
    assert stations[7] == Station(" ", " ", "GRO ", 607, 14.17, 145.23)
    low, high = bulletin_groups(stations)
    assert [s.name for s in low] == [s.name for s in high]
    assert len(low) == 15
    assert low[4].lat == -14.33  # Pago Pago is in the southern hemisphere


def test_fixed_columns_and_trailing_comment_ignored():
    stn = parse_station_line("EXABCD 12345 -12.34 -123.45 anything goes here 99.99")
    assert stn == Station("E", "X", "ABCD", 12345, -12.34, -123.45)


def test_fortran_edit_descriptor_rules():
    # no decimal point: F6.2 / F7.2 imply two decimal places
    assert parse_station_line("  AAA      7   1672  -16953").lat == 16.72
    assert parse_station_line("  AAA      7   1672  -16953").lon == -169.53
    # blank numeric fields read as zero
    stn = parse_station_line("B ZZZ")
    assert (stn.elevation_ft, stn.lat, stn.lon) == (0, 0.0, 0.0)
    # embedded blanks are ignored (BLANK='NULL')
    assert parse_station_line("  AAA   1 2  16.72 -169.53").elevation_ft == 12
    assert parse_station_line("  AAA     -5  16.72 -169.53").elevation_ft == -5
    # short line is padded
    assert parse_station_line("  AAA     10  16.7").lat == 16.7


@pytest.mark.parametrize(
    "line",
    [
        "  AAA    abc  16.72 -169.53",
        "  AAA      7  1x.72 -169.53",
        "  AAA      7  16.72 -1.9.53",
    ],
)
def test_malformed_numbers(line):
    with pytest.raises(StationListError, match="line 3"):
        read_station_list(["B X        0   0.00    0.00", "E Y        0   0.00    0.00", line])


def test_impossible_position():
    with pytest.raises(StationListError, match="impossible position"):
        read_station_list(["B AAA      7  96.72 -169.53"])


def test_sources_path_file_and_lines(tmp_path, pacific_stnlist):
    text = open(pacific_stnlist).read()
    from_path = read_station_list(pacific_stnlist)
    assert read_station_list(io.StringIO(text)) == from_path
    assert read_station_list(text.splitlines()) == from_path
    assert read_station_list(tmp_path.joinpath("x").parent / pacific_stnlist) == from_path


def test_blank_lines_skipped_and_empty_list_rejected(tmp_path):
    lines = ["", "B AAA      7  16.72 -169.53", "   ", "E BBB      7  16.72 -169.53", ""]
    assert len(read_station_list(lines)) == 2
    with pytest.raises(StationListError, match="empty"):
        read_station_list(["", "  "])
    with pytest.raises(StationListError, match="cannot read"):
        read_station_list(tmp_path / "does_not_exist")


def _stn(ind, name):
    return Station(ind, " ", name.ljust(4), 0, 0.0, 0.0)


def test_bulletin_groups():
    stations = [_stn("B", "A"), _stn(" ", "B"), _stn("E", "C"), _stn("B", "D"), _stn("E", "E"),
                _stn("B", "F"), _stn("E", "G")]  # fmt: skip
    groups = bulletin_groups(stations)
    assert [[s.name for s in g] for g in groups] == [["A", "B", "C"], ["D", "E"]]  # third group unused
    assert len(bulletin_groups(stations, count=3)) == 3


@pytest.mark.parametrize(
    "inds, message",
    [
        ("B E", "1 complete"),  # only one group
        ("B  ", "0 complete"),  # never closed
        (" E B E", "not marked 'B'"),
        ("B B E B E", "before the previous"),
        ("B E  E", "not marked 'B'"),
    ],
)
def test_bulletin_group_errors(inds, message):
    stations = [_stn(c, f"S{k}") for k, c in enumerate(inds)]
    with pytest.raises(StationListError, match=message):
        bulletin_groups(stations)
