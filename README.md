# fbwndgfs (Python)

Python replacement for the NCEP Fortran program **FBWNDGFS** (`fbwndgfs.F`,
Cavanaugh 1986; Vuong 2004–2016), ported from
[NOAA-EMC/gfs-utils @ 8282140](https://github.com/NOAA-EMC/gfs-utils/tree/8282140861731e07ffd30fe51a5de958e5e0b863/src/fbwndgfs.fd).

It produces the Pacific **winds and temperatures aloft** bulletins from GFS
forecasts:

| Forecast | 1000–24000 ft | 30000–53000 ft |
|----------|---------------|----------------|
| 6 h      | FBOC31        | FBOC37         |
| 12 h     | FBOC33        | FBOC38         |
| 24 h     | FBOC35        | FBOC39         |

> **Read first:** the port does not reproduce the Fortran executable on the
> operational 0.25° input by default, because the Fortran interpolates from
> the wrong grid points there. See [Differences from the Fortran](#differences-from-the-fortran).

## What changed for the workflow

The Fortran needed GRIB1 input, so `exgfs_atmos_fbwind.sh` converted the GFS
GRIB2 files with `wgrib2`, `cnvgrib -g21` and `grbindex` first. The port reads
GRIB2 directly with [grib2io](https://github.com/NOAA-MDL/grib2io)
(NCEPLIBS-g2c), so those steps go away:

```bash
# before
for fhr3 in 006 012 024; do
    cat pres_a.f${fhr3} pres_b.f${fhr3} > tmp
    wgrib2 tmp | grep -F -f gfs_fbwnd_parmlist_g2 | wgrib2 -i -grib tmp2 tmp
    cnvgrib -g21 tmp2 gfs.t${cyc}z.grbf${fhr3}_grb1
    grbindex gfs.t${cyc}z.grbf${fhr3}_grb1 gfs.t${cyc}z.grbf${fhr3}_grb1.idx
done
export FORT11=... FORT12=... FORT13=... FORT31=... FORT32=... FORT33=... FORT51=tran.fbwnd_pacific
fbwndgfs.x < fbwnd_pacific.stnlist

# after
fbwndgfs --stations fbwnd_pacific.stnlist \
    --f006 gfs.t${cyc}z.pres_a.0p25.f006.grib2 gfs.t${cyc}z.pres_b.0p25.f006.grib2 \
    --f012 gfs.t${cyc}z.pres_a.0p25.f012.grib2 gfs.t${cyc}z.pres_b.0p25.f012.grib2 \
    --f024 gfs.t${cyc}z.pres_a.0p25.f024.grib2 gfs.t${cyc}z.pres_b.0p25.f024.grib2 \
    --output tran.fbwnd_pacific
```

The output file has the same format as before (1280-byte records, one LF
after each), so `make_ntc_bull.pl` is used unchanged.

## Install

```bash
pip install .            # needs numpy and grib2io
pip install .[test]      # plus pytest
```

grib2io needs the NCEPLIBS-g2c shared library. If no wheel is available for
your platform, build g2c and point pip at it:

```bash
G2C_DIR=/path/to/g2c pip install grib2io
```

NCEPLIBS-ip is **not** needed: the one routine the Fortran used from it
(`GDSWZD`, station lat/lon → grid coordinates) is a few lines for a regular
lat/lon grid and is implemented in `fbwndgfs/grid.py`.

Python 3.10 or newer.

## Use

### Command line

```
fbwndgfs --stations FILE --f006 GRIB2 [GRIB2 ...] --f012 GRIB2 [...] --f024 GRIB2 [...]
         --output FILE [--text FILE] [--transmit-time YYYYMMDDHHMM]
         [--legacy-grid-dims IIxJJ] [-v] [--version]
```

| Option | Meaning |
|---|---|
| `--stations` | Station list. `-` (the default) reads standard input, as the Fortran did. |
| `--f006/--f012/--f024` | GRIB2 file(s) for each forecast hour. For the GFS give both `pres_a` and `pres_b`; `pres_b` holds the 305, 457, 610, 914 and 4572 m levels. |
| `--output` | Transmission file to write (the Fortran's `FORT51`). |
| `--text` | Also write a plain-text rendering for people (`-` = stdout). Not for dissemination. |
| `--transmit-time` | UTC stamp for the WMO headings. Default: the current time, as in the Fortran. Set it to make runs reproducible. |
| `--legacy-grid-dims` | Regression testing only; see below. |

Exit status: `0` success, `2` bad command line, `10` station list, `60` GRIB
file unreadable, `70` unsupported grid, `80` field not found, `81` mixed
model cycles, `82` station off the grid, `83` bulletin layout. The Fortran
codes these replace are listed in `fbwndgfs --help`.

### Python

```python
import datetime as dt
import fbwndgfs

tran = fbwndgfs.run(
    "parm/fbwnd_pacific.stnlist",
    {6:  ["pres_a.f006.grib2", "pres_b.f006.grib2"],
     12: ["pres_a.f012.grib2", "pres_b.f012.grib2"],
     24: ["pres_a.f024.grib2", "pres_b.f024.grib2"]},
    output="tran.fbwnd_pacific",
)
print(fbwndgfs.tran_to_text(tran))
```

The steps are also available separately, e.g. to get at the interpolated
values:

```python
stations = fbwndgfs.read_station_list("parm/fbwnd_pacific.stnlist")
with fbwndgfs.Grib2Source(["pres_a.f006.grib2", "pres_b.f006.grib2"]) as src:
    result = fbwndgfs.interpolate_tau(src, stations, 6)
d = result.data[0][8]            # first station, 18000 ft (500 mb)
print(d.u_kt, d.v_kt, d.temp_c, d.wind, d.temp)
```

`fbwndgfs.ArraySource` feeds NumPy arrays instead of GRIB2 files.

## Inputs

**Station list** – fixed columns (`FORMAT(A1,A1,A4,1X,I5,1X,F6.2,1X,F7.2)`);
anything after column 27 is a comment:

```
B JON      7  16.72 -169.53 # FBOC31, 33, 35  Johnston Island
  KWA      9   8.72  167.73
...
E T11     91   9.48  138.07
B JON      7  16.72 -169.53   FBOC37, 38, 39  Johnston Island
...
E T11     91   9.48  138.07
```

Column 1 is `B` on the first and `E` on the last station of a bulletin;
columns 3–6 the identifier; then elevation (ft), latitude and longitude
(degrees, west negative). The first `B…E` group is used for the low-level
bulletins and the second for the high-level ones. `parm/fbwnd_pacific.stnlist`
is the operational list from global-workflow.

**GRIB2 fields** – for each forecast hour, `UGRD`, `VGRD` and `TMP`
(discipline 0, product template 4.0) on

- 305, 457, 610, 914, 1829, 2743, 3658 and 4572 m above mean sea level, and
- 500, 400, 300, 250, 200, 150 and 100 mb,

on a regular latitude/longitude grid (grid template 3.0). All fields must
come from one 00, 06, 12 or 18 UTC cycle.

## Output

One file of 1280-character records, each followed by a line feed, holding
the six bulletins as a continuous stream. Control characters are written as
printable stand-ins that `make_ntc_bull.pl` translates: `<<@` = CR CR LF,
`|` = `+`, `>` = end of block, `%` = end of bulletin, `^` and `$` = fill.

`--text` shows what a bulletin says:

```
FBOC31 KWNO 111605
FD1OC1
DATA BASED ON 111200Z
VALID 111800Z   FOR USE 1400-2100Z. TEMPS NEG ABV 24000
FT  1000 1500 2000 3000    6000    9000   12000   15000   18000   24000
JON 2254 2254 2254 2254 2254+08 2254+08 2254+08 2254+08 2254+08 2254+08
```

Each group is `DDff` (direction in tens of degrees, speed in knots) followed
by the temperature in °C. `9900` = light and variable (under 5 kt);
direction 51–86 = speed of 100 kt or more (subtract 50 from the direction,
add 100 to the speed; 199 kt is the maximum reported). Groups too close to
the terrain are left blank.

## How it works

1. Read the station list.
2. For each forecast hour read the 45 fields; convert winds to knots and
   temperatures to °C.
3. Convert each station's position to fractional grid coordinates and
   interpolate with the 16-point biquadratic (Bessel) scheme of w3emc
   `W3FT01`; keep the result as truncated integer hundredths.
4. Turn u/v into direction and speed (`W3FC05`), round, and encode; apply the
   station-elevation rules.
5. Lay out two bulletins per forecast hour in 1280-character transmission
   blocks and write the record file.

| Module | Contents | Fortran counterpart |
|---|---|---|
| `constants.py` | levels, bulletin IDs, conversion factors | `DATA` statements |
| `stations.py` | station list reader | `READ(5,10)` loop |
| `gribio.py` | GRIB2 field lookup and decoding (grib2io) | `GETGB` |
| `grid.py` | lat/lon → grid coordinates | `GDSWZD_GRIB1` (NCEPLIBS-ip) |
| `w3emc.py` | `w3ft01`, `w3fc05`, `w3ai15` | NCEPLIBS-w3emc |
| `encode.py` | `DDff`/`TT` encoding, elevation rules | `DO 3900` loop |
| `bulletin.py` | headings, lines, blocking, records | `DO 6900` loop, `WXAI19` |
| `core.py` | driver | main program |
| `cli.py` | command line | — |

`docs/PORTING_NOTES.md` has the statement-level detail.

## Differences from the Fortran

Full detail and evidence are in [`docs/PORTING_NOTES.md`](docs/PORTING_NOTES.md).

1. **Interpolation uses the grid the data is on.** `fbwndgfs.F` passes fixed
   dimensions `IMAX=1760, JMAX=880` (the T574 Gaussian grid of 2010) to the
   interpolation routine, while the script has supplied the 1440 × 721
   0.25° grid since 2016. Compiled from the unmodified source, the Fortran
   then takes each station's values from unrelated grid points: with
   T(°C) = latitude / 2 everywhere, Johnston Island (16.72°N) should read
   `+08` and the Fortran executable reports `+00`. The port interpolates
   correctly by default. `--legacy-grid-dims 1760x880` reproduces the
   Fortran executable exactly and exists for regression testing.
2. **Reads GRIB2**, so values are decoded by g2c in single precision rather
   than by w3emc in double from a GRIB1 copy. In testing this never changed
   a bulletin character.
3. **Checks the Fortran did not make** (each is an error instead of
   undefined behaviour): all fields from one cycle; cycle is 00/06/12/18 UTC;
   every station on the grid and on valid data; station list has two
   complete `B…E` groups.
4. No 80-character limit on file names and no 799-station limit.

Kept on purpose: the legacy m/s → knots factor `1.94254` (exact is 1.94384;
0.07 % low), the 0.001° offset in the wind direction, truncation (not
rounding) to hundredths after interpolation, and the wall-clock time stamp
in the WMO heading.

## Tests

```bash
python -m pytest                      # 244 tests, ~15 s
```

| Tier | Needs | What it checks |
|---|---|---|
| unit (228 tests) | NumPy | every routine against hand-computed values, analytic fields, the original lookup tables, error paths |
| `grib` (16 tests) | grib2io | GRIB2 selection rules, command line, and **byte-for-byte agreement with two outputs of the compiled Fortran** stored in `tests/data/*.tran` |
| `legacy` (9 tests) | compiled Fortran | generates fresh random inputs, runs the Fortran and the port, requires identical files |

To run the `legacy` tier:

```bash
tests/legacy/build_legacy.sh /tmp/legacy          # ~1 min; needs gfortran, cmake, BLAS/LAPACK
FBWNDGFS_LEGACY_DIR=/tmp/legacy/bin python -m pytest
```

Line coverage of the package is 98 %; the uncovered lines are defensive
branches in `gribio.py`.

**Not tested:** real GFS files (the build machine had no access to NOMADS).
The synthetic GRIB2 files use the same grid, parameters, levels and
`pres_a`/`pres_b` split, with simple packing; g2c handles the complex
packing of real files. Run one real cycle before relying on it.
