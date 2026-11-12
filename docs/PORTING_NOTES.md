# Porting notes: `fbwndgfs.F` → Python

Source: `src/fbwndgfs.fd/fbwndgfs.F` in NOAA-EMC/gfs-utils at commit
`8282140861731e07ffd30fe51a5de958e5e0b863` (970 lines: the main program and
the line blocker `WXAI19`). Driver: `dev/scripts/exgfs_atmos_fbwind.sh` and
`parm/product/fbwnd_pacific.stnlist` in NOAA-EMC/global-workflow (`0e01b99`).

Contents

1. [What the program does](#1-what-the-program-does)
2. [Statement-level correspondence](#2-statement-level-correspondence)
3. [Defects found in the Fortran](#3-defects-found-in-the-fortran)
4. [Behaviour kept on purpose](#4-behaviour-kept-on-purpose)
5. [Behaviour changed on purpose](#5-behaviour-changed-on-purpose)
6. [How equivalence was established](#6-how-equivalence-was-established)
7. [Limits](#7-limits)

---

## 1. What the program does

For forecast hours 6, 12 and 24 of one GFS cycle:

1. Read u, v and temperature on 15 levels (45 fields per hour):
   305, 457, 610, 914, 1829, 2743, 3658, 4572 m above mean sea level
   (labelled 1000 … 15000 ft) and 500, 400, 300, 250, 200, 150, 100 mb
   (labelled 18000 … 53000 ft).
2. Convert winds to knots (× 1.94254) and temperature to °C (− 273.15) on the
   whole grid.
3. For every station, interpolate each field to the station
   (`W3FT01`, biquadratic) and store `INT(value * 100)`.
4. Per station and level: direction and speed from u, v (`W3FC05`);
   direction to the nearest 10° (01–36), speed to the nearest knot; apply the
   100-kt and calm encodings; temperature to the nearest degree with a sign
   character.
5. Blank groups that are too close to the ground for the station's
   elevation.
6. Write two bulletins: levels 1–10 for the first `B…E` group of the station
   list and levels 11–15 for the second.

Six bulletins result, written as one character stream cut into 1280-byte
records.

## 2. Statement-level correspondence

| Fortran | Python | Notes |
|---|---|---|
| `READ(5,10)` loop, `FORMAT(A1,A1,A4,1X,I5,1X,F6.2,1X,F7.2)` | `stations.parse_station_line` | Fortran edit-descriptor rules kept: blanks ignored in numeric fields, blank field = 0, `Fw.2` without a decimal point implies two decimals. Verified against the Fortran with such records in `tests/data/stress.stnlist`. |
| `KTAU`, `IDWD1H/P`, `IDWD2H/P`, `IDWD2`, `NHGT6`, `NHGTP`, `NFDHDG`, `NCATNR`, `AWIPSID` | `constants.py` | Transcribed. |
| `GETGB` with `MPDS(5,6,7,14)` | `gribio.Grib2Source.get` | GRIB1 table 2 numbers 33/34/11 → GRIB2 (0,2,2)/(0,2,3)/(0,0,0); level type 103 → surface type 102, 100 → 100 (Pa); `P1` → forecast time. First match wins, as with `JREW=0`. |
| `GDSWZD_GRIB1(KGDS,-1,…)` | `grid.LatLonGrid.earth_to_grid` | Same expressions as `ip_equid_cylind_grid_mod` (`init_grib2`, `IOPT=-1`), including the `DLON_OFFSET` handling and the acceptance window `0 ≤ x ≤ IM+1(+1 if global)`. |
| `RFLD(I)*1.94254`, `RFLD(I)-273.15` | `core.interpolate_tau` | Applied before interpolation, as in the Fortran. |
| `W3FT01(ISTN,JSTN,RINTRP,X,IMAX,JMAX,0,0)` | `w3emc.w3ft01` | Full port including the cyclic branches the program never uses. |
| `KSTNU(S,L)=X*100.0` | `encode.to_hundredths` | Truncation toward zero. |
| `W3FC05` | `w3emc.w3fc05` | `ATAN2(U,V)*57.2957795 + 180 + 1.E-3`. |
| `NDDD`, `NSSS`, `NDDSS`, `NTTT` logic | `encode.encode_wind`, `encode.encode_temp` | Same branch order. |
| `W3AI15` | `w3emc.w3ai15` | Zero-filled digits; high digits dropped on overflow. |
| `IELEV` tests | `encode.apply_elevation_rules` | |
| `NBULHD`, `NBASHD`, `NVALHD`, `LINE73` assembly | `bulletin.catalog_header`, `base_time_line`, `valid_time_line`, `level_heading`, `station_line` | Column arithmetic of `DO 4500` / `DO 5300` reproduced. |
| `NVALTM`, `NUSETM`, `IVLDAY` rules | `bulletin.header_times` | Computed as offsets from the cycle time; `tests/test_bulletin.py` checks all 12 cycle/hour combinations against the original tables, across month and year ends and 29 February. |
| `WXAI19`, `NEXT.GE.1207` test, ETB/ETX | `bulletin.TranStream` | |
| `SPACE`/`INDEX` copy loop, `WRITE(51,REC=IREC)` | `bulletin.frame_records` | Including the final record that is always written. |
| `ERREXIT(110/1050/…)` | `errors.py` | Exceptions; CLI exit codes 10/60/70/80. |
| `TMODE='T'` (backup run) branches | — | Dead code: `TMODE` is hard-wired to `'M'`. Not ported. |
| `MUSES`, `KBMS`, `JTIME` date check | — | Read or computed, never used. |

Arithmetic is done in IEEE double precision in the same operation order as
the Fortran, which is built with `-r8` (`-fdefault-real-8`), so real
literals such as `1.94254` and `57.2957795` are doubles there too.

## 3. Defects found in the Fortran

All three were reproduced with an executable built from the unmodified
source (gfortran 13.3, NCEPLIBS-w3emc `02cf4c8`, NCEPLIBS-ip `06ccb44`,
NCEPLIBS-bacio `c4adc7e`). None was inferred from reading alone.

### 3.1 Interpolation uses fixed grid dimensions (affects the numbers)

```fortran
      PARAMETER  (NPTS=1548800)
      PARAMETER  (IMAX=1760,JMAX=880)
      REAL       RFLD(NPTS),RINTRP(IMAX,JMAX)
      EQUIVALENCE  (RFLD(1),RINTRP(1,1))
      ...
      CALL GDSWZD_GRIB1(KGDS,-1,1,FILL,XPTS(J),YPTS(J),ALON(J),ALAT(J),IRET)
      ...
      CALL W3FT01(ISTN(S),JSTN(S),RINTRP,X,IMAX,JMAX,NCYCLK,LIN)
```

`GETGB` fills `RFLD` contiguously with however many points the record has,
and `GDSWZD` computes the station's (x, y) from the record's own grid
description. `W3FT01` then addresses the field as `FLD(1760,880)`, i.e. it
reads element `x + (y-1)*1760`. That is the right element only if the grid
is 1760 points wide.

The 1760 × 880 dimensions are the T574 Gaussian grid (history entry of
2010-05-26). The script has fed the 0.25° grid, 1440 × 721, since
"Sep 2016 … Modified to use GFS 0p25 deg GRIB2" (script header). On that
grid row `y` of the true field starts at element `(y-1)*1440 + 1`, so the
Fortran samples a point `(y-1)*320` elements further along: a different
latitude row and a different longitude, and the four rows of the stencil
are 1760 elements apart rather than one grid row apart.

Demonstration (0.25° grid, every level: T = 273.15 + latitude/2 K,
u = longitude/10 m/s, v = 20 m/s):

| Station | Position | Correct group | Fortran executable |
|---|---|---|---|
| JON | 16.72 N 169.53 W | `2254+08` | `2362+00` |
| KWA | 8.72 N 167.73 E | `2251+04` | `2365-05` |
| MAJ | 7.05 N 171.27 E | `2251+04` | `2041-06` |
| MDY | 28.20 N 177.37 W | `2253+14` | `2250+07` |
| PPG | 14.33 S 170.71 W | `2253-07` | `2042-19` |

For Johnston Island the stencil rows land near the equator (0.25–0.5°N)
on meridians 80° apart (about 130°W and 50°W), and are blended.

The "Fortran executable" column is output of the compiled program; the
port's `legacy_grid_dims=(1760, 880)` mode reproduces it byte for byte
(§6). The "correct" column is the port's default and agrees with the
analytic fields.

What this means for you: if the operational `fbwndgfs.x` is built from this
source and fed by this script, FBOC31–39 have not described the winds over
their stations since the input changed. I have only the source, not
operational output, so that conclusion needs one check on your side:
compare a current FBOC31 with the GFS at one station.

Consequence for the port: the default is the correct interpolation, so its
output will differ from the current executable's in nearly every group.
`--legacy-grid-dims 1760x880` is there if you need identical output during
a transition.

### 3.2 `WXAI19` overruns the block it blanks (can corrupt the output)

```fortran
         CALL W3FI01(LW)            ! LW = 4 (bytes in a default INTEGER)
         IWORDS = N / LW            ! 1280 / 4 = 320
         CALL XSTORE(NBLK,WBLANK,IWORDS)
```

`XSTORE` in `libw3emc_d.a` stores `MWORDS` default-`REAL` words, which are 8
bytes in the `_d` library, so 2560 bytes are written into the 1280-byte
`BULTN`. With gfortran the next 1280 bytes are the `SPACE` record buffer:
each time a new transmission block is started, bulletin text waiting in
`SPACE` is overwritten (with `20 00 00 00 00 00 00 00` patterns), and the
output file loses most of its content. Whether the Intel build is affected
depends on how that compiler lays out the two arrays; the overrun itself is
there regardless.

The reference executable used for the tests is therefore linked with a
4-byte-word `XSTORE` (`tests/legacy/xstore_shim.f90`). `fbwndgfs.F` itself
is compiled unmodified. The port has no equivalent of this routine.

### 3.3 Knots conversion factor

`1.94254` is used for m/s → knots; the correct value is `1.943844`. Speeds
are 0.07 % low (0.1 kt at 150 kt), which changes a rounded speed only
rarely. **Kept** (`constants.MS_TO_KT`) so that this port changes one thing
at a time; changing it is a one-line edit.

### 3.4 Smaller things

- File names are held in `CHARACTER*80`; longer paths are truncated and the
  run stops with code 1050.
- A station list of 800 or more records is reported as a read error.
- `FILL` passed to `GDSWZD` is uninitialised, and its return code is not
  checked: a station off the grid gets arbitrary coordinates.
- If the cycle hour is not 00/06/12/18, `ICYC` is undefined.
- Header date/times are taken from whichever record was read last; fields
  from different cycles are not detected.
- A station list without an `E` marker runs off the end of the arrays.
- `SPACE` is not initialised before first use (harmless once the first
  record fills).

## 4. Behaviour kept on purpose

- The `1.94254` factor (§3.3).
- `W3FC05`'s `+1.E-3` degree, which settles ties at 5° boundaries.
- Truncation to hundredths after interpolation, then rounding: a speed of
  24.4999 kt is stored as 24.49 and reported as 24.
- Temperatures between −0.5 and 0 are reported `+00`.
- Only two temperature digits; no elevation blanking of the 1000–2000 ft
  winds or of the 15000 ft level.
- No separator between a four-character station identifier and the first
  group (the operational identifiers have three characters).
- Non-cyclic interpolation: within the last grid interval before the
  wrap-around longitude the value is taken from the last column. No
  Pacific station is near 0°E.
- The WMO heading carries the wall-clock UTC time of the run, taken once
  for all six bulletins.
- A final output record is always written, so a stream that fills its last
  record exactly is followed by one blank record.

## 5. Behaviour changed on purpose

| Change | Reason |
|---|---|
| Interpolates on the actual grid dimensions | §3.1 |
| Input is GRIB2 via grib2io/g2c | Removes `wgrib2`/`cnvgrib`/`grbindex` and the GRIB1 dependency |
| Product template must be 4.0 | A GRIB1 `P1` match could not tell an instantaneous field from an accumulation; GRIB2 can |
| Mixed cycles, off-cycle hours, off-grid stations, missing data at a station, malformed station groups are errors | Were undefined behaviour |
| A line that would not fit a transmission block is an error | The Fortran would silently drop the rest of the bulletin; cannot occur with these line lengths |
| Blank lines in the station list are skipped | The Fortran would read them as stations at 0°N 0°E (never reached in practice) |
| Messages go to `logging`; no `W3TAGB`/`W3TAGE` banner | |

## 6. How equivalence was established

The port was compared with the compiled Fortran, not only with my reading
of it.

**Reference build** (`tests/legacy/build_legacy.sh`): `fbwndgfs.F`
unmodified, the flags from gfs-utils' `CMakeLists.txt`, the `XSTORE` shim of
§3.2.

**Same data to both programs** (`tests/synthetic.py`): random fields are
written as GRIB2 with grib2io for the port and, from the same arrays, as
GRIB1 with w3emc `PUTGB` (`tests/legacy/mkgrib1.f90`) plus `grbindex` for
the Fortran. The fields span every encoding branch: speeds from calm to
over 199 kt, both temperature signs on all levels.

**Two configurations**

| | Grid | Port mode | Purpose |
|---|---|---|---|
| A | 1760 × 880, 0.2° | default | The Fortran's indexing is right on a grid of exactly its hard-wired size, so here the Fortran is a valid reference for the port's default behaviour. |
| B | 1440 × 721, 0.25° | `legacy_grid_dims=(1760,880)` | The operational configuration. Shows the port reproduces the executable, defect included, so every other step is proven on the real grid and station list. |

**Station lists**: the operational list, and `tests/data/stress.stnlist`
(94 records): stations in the first and last grid intervals in both
directions, exactly on a grid node, in a calm band, west longitudes, at
each elevation threshold and one foot above it, a negative elevation,
coordinates written without a decimal point, and enough stations for two
ETB block breaks in each bulletin.

**Results**: output files identical byte for byte in

- 2 stored golden cases (run in the default test suite),
- 9 live cases (all four cycles; month end, year end, 29 February),
- 8 further ad hoc runs with 0.1-precision fields packed with decimal scale
  1, as real GFS output is (two such cases are also in the live tier).

The remaining tests (228) check each routine independently of the Fortran:
`W3FT01` against the Bessel formula and against exact results for linear
and quadratic fields; grid coordinates against hand calculation; every
encoding boundary; heading times against the original tables; record
framing; error paths.

## 7. Limits

- **Not run on real GFS files.** The environment the port was made in
  could not reach NOMADS. Synthetic files have the operational grid,
  parameters, levels and `pres_a`/`pres_b` split, but simple packing; real
  files use complex packing with spatial differencing, which g2c decodes
  but which was not exercised here.
- Only regular lat/lon grids (GRIB2 template 3.0), stored row by row.
  Gaussian grids, which the program read before 2016, are rejected with a
  clear error rather than supported.
- GRIB2 values are decoded in single precision, GRIB1 values were decoded
  in double. A difference in the eighth significant digit can in principle
  move a value across a truncation boundary; it did not in any test.
- The reference executable was built with gfortran, not the Intel compiler
  used operationally.
- `make_ntc_bull.pl` was read, not run: the output format is identical to
  the Fortran's, so it should need no change.
