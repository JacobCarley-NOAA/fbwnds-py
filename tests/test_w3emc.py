"""Ports of the w3emc routines: W3AI15, W3FC05, W3FT01."""

import math

import numpy as np
import pytest

from fbwndgfs.w3emc import fint, w3ai15, w3fc05, w3ft01


# ---------------------------------------------------------------- fint ----
@pytest.mark.parametrize("x, expected", [(2.9, 2), (-2.9, -2), (0.999, 0), (-0.999, 0), (5.0, 5)])
def test_fint_truncates_toward_zero(x, expected):
    assert fint(x) == expected


# -------------------------------------------------------------- W3AI15 ----
@pytest.mark.parametrize(
    "value, width, expected",
    [
        (0, 2, "00"),
        (0, 4, "0000"),
        (7, 2, "07"),
        (11, 2, "11"),
        (600, 4, "0600"),
        (9900, 4, "9900"),
        (8699, 4, "8699"),
        (5, 3, "005"),
        (-5, 3, "-05"),
        (-47, 3, "-47"),
        (123, 2, "23"),  # overflow: high digits are dropped
        (-123, 3, "-23"),
        (12345, 4, "2345"),
    ],
)
def test_w3ai15(value, width, expected):
    assert w3ai15(value, width) == expected


def test_w3ai15_custom_minus_and_bad_width():
    assert w3ai15(-3, 2, minus="M") == "M3"
    with pytest.raises(ValueError):
        w3ai15(1, 0)
    with pytest.raises(ValueError):
        w3ai15(1, 9)


# -------------------------------------------------------------- W3FC05 ----
@pytest.mark.parametrize(
    "u, v, direction",
    [
        (0.0, -10.0, 360.0),  # blowing toward the south = from the north
        (-10.0, 0.0, 90.0),  # from the east
        (0.0, 10.0, 180.0),  # from the south
        (10.0, 0.0, 270.0),  # from the west
        (-7.0, -7.0, 45.0),
        (7.0, 7.0, 225.0),
    ],
)
def test_w3fc05_directions(u, v, direction):
    dd, ss = w3fc05(u, v)
    # the library adds 0.001 degree; RTOD carries 9 significant digits
    assert dd == pytest.approx(direction + 1.0e-3, abs=1e-6)
    assert ss == pytest.approx(math.hypot(u, v))


def test_w3fc05_calm():
    assert w3fc05(0.0, 0.0) == (0.0, 0.0)
    dd, ss = w3fc05(1e-11, 0.0)
    assert dd == 0.0 and ss == 1e-11


def test_w3fc05_direction_range():
    rng = np.random.RandomState(0)
    for u, v in rng.uniform(-100, 100, size=(500, 2)):
        dd, _ = w3fc05(float(u), float(v))
        assert 0.0 < dd <= 360.001


# -------------------------------------------------------------- W3FT01 ----
def _grid(func, ii=12, jj=10):
    """fld[j-1, i-1] = func(i, j) with 1-based i, j."""
    j, i = np.mgrid[1 : jj + 1, 1 : ii + 1]
    return func(i.astype(float), j.astype(float))


def test_w3ft01_returns_node_values():
    fld = np.random.RandomState(1).uniform(-50, 50, size=(10, 12))
    for i in range(1, 13):
        for j in range(1, 11):
            assert w3ft01(float(i), float(j), fld) == fld[j - 1, i - 1]


@pytest.mark.parametrize("lin", [0, 1])
def test_w3ft01_exact_for_linear_fields_everywhere(lin):
    fld = _grid(lambda i, j: 3.0 * i - 2.0 * j + 5.0)
    rng = np.random.RandomState(2)
    for x, y in zip(rng.uniform(1, 12, 300), rng.uniform(1, 10, 300)):
        assert w3ft01(x, y, fld, lin=lin) == pytest.approx(3.0 * x - 2.0 * y + 5.0, abs=1e-10)


def test_w3ft01_biquadratic_exact_for_quadratics_in_interior():
    f = lambda i, j: 0.5 * i * i - 0.25 * j * j + 0.3 * i * j + i - j
    fld = _grid(f)
    rng = np.random.RandomState(3)
    # interior: 2 <= int(x) <= II-3 and 2 <= int(y) <= JJ-3
    for x, y in zip(rng.uniform(2, 9.99, 300), rng.uniform(2, 7.99, 300)):
        assert w3ft01(x, y, fld) == pytest.approx(f(x, y), abs=1e-9)


def test_w3ft01_bilinear_is_not_exact_for_quadratics():
    fld = _grid(lambda i, j: i * i)
    assert w3ft01(5.5, 5.0, fld, lin=1) == pytest.approx(30.5)  # chord, not 30.25
    assert w3ft01(5.5, 5.0, fld, lin=0) == pytest.approx(30.25)


def test_w3ft01_matches_bessel_formula_by_hand():
    fld = np.random.RandomState(4).uniform(0, 10, size=(8, 8))
    x, y = 4.3, 3.6
    i, j, dx, dy = 4, 3, 0.3, 0.6

    def row(jr):
        f = lambda ic: fld[jr - 1, ic - 1]
        return f(i) + dx * (f(i + 1) - f(i)) + dx * (dx - 1) / 4 * (f(i - 1) - f(i) - f(i + 1) + f(i + 2))

    r = [row(j - 1), row(j), row(j + 1), row(j + 2)]
    expected = r[1] + dy * (r[2] - r[1]) + dy * (dy - 1) / 4 * (r[0] - r[1] - r[2] + r[3])
    assert w3ft01(x, y, fld) == pytest.approx(expected, rel=1e-13)


@pytest.mark.parametrize(
    "x, y",
    [(1.4, 5.5), (11.6, 5.5), (5.5, 1.4), (5.5, 9.7), (1.2, 1.3), (11.9, 9.9)],
)
def test_w3ft01_is_linear_in_the_outermost_cells(x, y):
    """In the first/last grid interval the quadratic term is switched off."""
    fld = _grid(lambda i, j: i * i + j * j)
    i, j = int(x), int(y)
    dx, dy = x - i, y - j
    quad_i = not (i < 2 or i >= 11)
    quad_j = not (j < 2 or j >= 9)
    fi = (i + dx) ** 2 if quad_i else i * i + dx * ((i + 1) ** 2 - i * i)
    fj = (j + dy) ** 2 if quad_j else j * j + dy * ((j + 1) ** 2 - j * j)
    assert w3ft01(x, y, fld) == pytest.approx(fi + fj, abs=1e-9)


def test_w3ft01_clamps_points_off_the_grid():
    fld = _grid(lambda i, j: 10.0 * i + j)
    # x beyond the last column: both stencil columns clamp to II
    assert w3ft01(12.5, 5.0, fld) == pytest.approx(10.0 * 12 + 5)
    # y beyond the last row
    assert w3ft01(6.0, 10.5, fld) == pytest.approx(10.0 * 6 + 10)
    # x below the first column: I = 0 and I+1 = 1 both clamp to column 1
    assert w3ft01(0.5, 5.0, fld) == pytest.approx(10.0 * 1 + 5)


def test_w3ft01_second_to_last_cell_keeps_quadratic_term():
    """I = II-2 takes the edge branch but must still interpolate quadratically."""
    fld = _grid(lambda i, j: i * i)
    assert w3ft01(10.5, 5.0, fld) == pytest.approx(10.5**2)
    assert w3ft01(11.5, 5.0, fld) == pytest.approx((121 + 144) / 2)  # last cell: linear


@pytest.mark.parametrize("ncyclk", [1, 3])
def test_w3ft01_cyclic_in_i(ncyclk):
    """Cyclic mode: column II duplicates column 1, stencil wraps around."""
    ii, jj = 13, 9  # 12 distinct columns + 1 duplicate
    f = lambda i, j: np.sin(2 * np.pi * (i - 1) / (ii - 1)) + 0.0 * j
    fld = _grid(f, ii, jj)
    # first cell: IM1 wraps to II-1
    x = 1.5
    f1, f2, f3, f0 = (float(f(c, 1)) for c in (1, 2, 3, ii - 1))
    expected = f1 + 0.5 * (f2 - f1) + 0.5 * -0.5 / 4 * (f0 - f1 - f2 + f3)
    assert w3ft01(x, 4.0, fld, ncyclk=ncyclk) == pytest.approx(expected, rel=1e-12)
    # last cell: IP2 wraps to column 2
    x = ii - 0.5
    a, b, c, d = (float(f(col, 1)) for col in (ii - 2, ii - 1, ii, 2))
    expected = b + 0.5 * (c - b) + 0.5 * -0.5 / 4 * (a - b - c + d)
    assert w3ft01(x, 4.0, fld, ncyclk=ncyclk) == pytest.approx(expected, rel=1e-12)
    # non-cyclic gives plain linear there
    assert w3ft01(x, 4.0, fld, ncyclk=0) == pytest.approx((b + c) / 2, rel=1e-12)


@pytest.mark.parametrize("ncyclk", [2, 3])
def test_w3ft01_cyclic_in_j(ncyclk):
    ii, jj = 9, 13
    f = lambda i, j: np.cos(2 * np.pi * (j - 1) / (jj - 1)) + 0.0 * i
    fld = _grid(f, ii, jj)
    f1, f2, f3, f0 = (float(f(1, r)) for r in (1, 2, 3, jj - 1))
    expected = f1 + 0.5 * (f2 - f1) + 0.5 * -0.5 / 4 * (f0 - f1 - f2 + f3)
    assert w3ft01(4.0, 1.5, fld, ncyclk=ncyclk) == pytest.approx(expected, rel=1e-12)
    a, b, c, d = (float(f(1, r)) for r in (jj - 2, jj - 1, jj, 2))
    expected = b + 0.5 * (c - b) + 0.5 * -0.5 / 4 * (a - b - c + d)
    assert w3ft01(4.0, jj - 0.5, fld, ncyclk=ncyclk) == pytest.approx(expected, rel=1e-12)


def test_w3ft01_cyclic_interior_edge_cells():
    """Cyclic I, a near-edge cell that is neither the first nor the last."""
    fld = _grid(lambda i, j: i * i, 13, 9)
    assert w3ft01(11.5, 1.0, fld, ncyclk=1) == pytest.approx(11.5**2)
    assert w3ft01(5.0, 8.5, fld.T.copy(), ncyclk=2) == pytest.approx(8.5**2)


def test_w3ft01_propagates_nan():
    fld = np.zeros((8, 8))
    fld[3, 3] = np.nan
    assert math.isnan(w3ft01(4.5, 4.5, fld))
    assert w3ft01(7.0, 7.0, fld) == 0.0
