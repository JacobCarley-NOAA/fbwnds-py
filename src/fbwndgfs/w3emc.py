"""Python ports of the NCEPLIBS-w3emc routines that ``fbwndgfs.F`` calls.

Only three routines carry numerical or formatting behaviour that affects the
bulletins:

========  ==========================================================
W3FT01    interpolate a gridded field to a fractional (i, j) point
W3FC05    u, v wind components -> direction and speed
W3AI15    integer -> fixed-width ASCII digits
========  ==========================================================

The ports keep the operation order of the Fortran so that, in IEEE double
precision (the legacy executable is built with ``-r8``), results are
bit-identical.  Fortran ``REAL -> INTEGER`` assignment truncates toward
zero; :func:`fint` is used wherever the Fortran relied on that.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .constants import MINUS, RTOD


def fint(x: float) -> int:
    """Fortran ``INTEGER = REAL`` conversion: truncate toward zero."""
    return int(x)


# --------------------------------------------------------------------------
# W3FT01
# --------------------------------------------------------------------------


def w3ft01(
    sti: float,
    stj: float,
    fld: np.ndarray,
    ncyclk: int = 0,
    lin: int = 0,
) -> float:
    """Interpolate ``fld`` to the fractional grid point (``sti``, ``stj``).

    Port of ``W3FT01(STI,STJ,FLD,HI,II,JJ,NCYCLK,LIN)``.

    Parameters
    ----------
    sti, stj
        1-based fractional grid coordinates; ``sti`` runs along a row
        (the Fortran I index), ``stj`` across rows (J).
    fld
        2-D array of shape ``(JJ, II)``; ``fld[j - 1, i - 1]`` is the
        Fortran ``FLD(I, J)``.
    ncyclk
        0 = not cyclic, 1 = cyclic in I, 2 = cyclic in J, 3 = cyclic in both.
        The cyclic modes assume the wrap row/column is duplicated in the
        field.  ``fbwndgfs`` always passes 0.
    lin
        1 = bilinear; anything else = biquadratic (Bessel).  ``fbwndgfs``
        always passes 0.

    Returns
    -------
    float
        The interpolated value.

    Notes
    -----
    Away from the edges the result is Bessel's central-difference formula
    applied along I on four rows and then along J::

        f(i + d) = f(i) + d * (f(i+1) - f(i))
                   + d * (d - 1) / 4 * (f(i-1) - f(i) - f(i+1) + f(i+2))

    Within one point of an edge the quadratic term is dropped (linear
    interpolation) and stencil indices are clamped to the grid.
    """
    jj, ii = fld.shape

    i = fint(sti)
    j = fint(stj)
    xdeli = sti - float(i)
    xdelj = stj - float(j)
    ip2 = i + 2
    im1 = i - 1
    ip1 = i + 1
    jy = [j - 1, j, j + 1, j + 2]  # JY(1..4)

    xi2tm = 0.0
    xj2tm = 0.0
    if lin != 1:
        xi2tm = xdeli * (xdeli - 1.0) * 0.25
        xj2tm = xdelj * (xdelj - 1.0) * 0.25

    near_edge = i < 2 or j < 2 or i > ii - 3 or j > jj - 3
    if near_edge:
        icyclk = 0
        jcyclk = 0
        if ncyclk != 0:
            if ncyclk // 2 != 0:
                jcyclk = 1
            if ncyclk != 2:
                icyclk = 1
            if icyclk != 0:
                if i == 1:
                    ip2 = 3
                    im1 = ii - 1
                elif i == ii - 1:
                    ip2 = 2
                    im1 = ii - 2
                else:
                    ip2 = i + 2
                    im1 = i - 1
                ip1 = i + 1
            if jcyclk != 0:
                if j == 1:
                    jy[3] = 3
                    jy[0] = jj - 1
                elif j == jj - 1:
                    jy[3] = 2
                    jy[0] = jj - 2
                else:
                    jy[3] = j + 2
                    jy[0] = j - 1
                jy[2] = j + 1
                jy[1] = j
        if lin != 1:
            if icyclk == 0 and (i < 2 or i >= ii - 1):
                xi2tm = 0.0
            if jcyclk == 0 and (j < 2 or j >= jj - 1):
                xj2tm = 0.0
        # Do not allow a point off the grid, cyclic or not.
        i = min(max(i, 1), ii)
        ip1 = min(max(ip1, 1), ii)
        ip2 = min(max(ip2, 1), ii)
        im1 = min(max(im1, 1), ii)

    eras = [0.0, 0.0, 0.0, 0.0]
    for k in range(4):
        j1 = min(max(jy[k], 1), jj)
        row = fld[j1 - 1]
        f_i = float(row[i - 1])
        f_ip1 = float(row[ip1 - 1])
        f_im1 = float(row[im1 - 1])
        f_ip2 = float(row[ip2 - 1])
        eras[k] = (f_ip1 - f_i) * xdeli + f_i + (f_im1 - f_i - f_ip1 + f_ip2) * xi2tm

    return eras[1] + (eras[2] - eras[1]) * xdelj + (eras[0] - eras[1] - eras[2] + eras[3]) * xj2tm


# --------------------------------------------------------------------------
# W3FC05
# --------------------------------------------------------------------------


def w3fc05(u: float, v: float) -> tuple[float, float]:
    """Convert wind components to meteorological direction and speed.

    Port of ``W3FC05(U,V,DIR,SPD)``.

    Returns
    -------
    (direction, speed)
        Direction the wind blows *from*, in degrees, in the range
        (0.001, 360.001]; 0.0 when the speed is below 1e-10.  Speed is in
        the units of ``u`` and ``v``.

    Notes
    -----
    The 0.001 degree offset is part of the w3emc routine and is kept; it
    decides which way a direction lying exactly on a 5-degree boundary is
    rounded.
    """
    xspd = math.sqrt(u * u + v * v)
    if xspd < 1.0e-10:
        direction = 0.0
    else:
        direction = math.atan2(u, v) * RTOD + 180.0 + 1.0e-3
    return direction, xspd


# --------------------------------------------------------------------------
# W3AI15
# --------------------------------------------------------------------------


def w3ai15(value: int, width: int, minus: str = MINUS) -> str:
    """Format an integer as ``width`` ASCII characters with leading zeros.

    Port of ``W3AI15(NBUFA,NBUFB,1,N2,MINUS)`` for a single value.

    * Non-negative values give ``width`` digits, zero filled.
    * Negative values give ``minus`` followed by ``width - 1`` digits.
    * Digits that do not fit are dropped from the left (no overflow
      marker), exactly as the Fortran does: ``w3ai15(123, 2) == "23"``.
    """
    if not 1 <= width <= 8:
        raise ValueError(f"width must be 1..8, got {width}")
    if value == 0:
        return "0" * width
    magnitude = abs(value)
    if value > 0:
        positions: Sequence[int] = range(1, width + 1)
        prefix = ""
    else:
        positions = range(2, width + 1)
        prefix = minus
    digits = "".join(str((magnitude // 10 ** (width - p)) % 10) for p in positions)
    return prefix + digits
