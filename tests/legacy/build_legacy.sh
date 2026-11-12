#!/usr/bin/env bash
# Build the Fortran reference used by the "legacy" test tier.
#
#   tests/legacy/build_legacy.sh <work-dir>
#
# Produces <work-dir>/bin with
#   fbwndgfs.x  the legacy program, compiled from the unmodified fbwndgfs.F
#               of NOAA-EMC/gfs-utils at the commit the port was made from,
#               linked with xstore_shim.f90 (see that file for why)
#   mkgrib1     writes GRIB1 test input with w3emc PUTGB
#   grbindex    NCEPLIBS-grib_util GRIB1 indexer
#
# Then run the comparison tests with
#   FBWNDGFS_LEGACY_DIR=<work-dir>/bin python -m pytest tests/test_legacy_live.py
#
# Requirements: git, cmake, make, gfortran (10 or newer), BLAS and LAPACK
# (for NCEPLIBS-ip).  Set FC to use another gfortran.
set -euo pipefail

WORK=${1:?usage: build_legacy.sh <work-dir>}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FC=${FC:-gfortran}
GFS_UTILS_COMMIT=8282140861731e07ffd30fe51a5de958e5e0b863
# Library releases the golden files were checked against; override to test others.
BACIO_REF=${BACIO_REF:-v2.6.0}
W3EMC_REF=${W3EMC_REF:-v2.13.0}
IP_REF=${IP_REF:-v5.4.1}
GRIB_UTIL_REF=${GRIB_UTIL_REF:-v1.5.0}

mkdir -p "$WORK"/{src,build,bin}
WORK=$(cd "$WORK" && pwd)
PREFIX=$WORK/nceplibs

clone() {  # clone <org/repo> [commit]
  local dir=$WORK/src/${1#*/}
  [[ -d $dir/.git ]] || git clone -q "https://github.com/$1.git" "$dir"
  [[ -z ${2:-} ]] || git -C "$dir" checkout -q "$2"
}

clone NOAA-EMC/gfs-utils "$GFS_UTILS_COMMIT"
clone NOAA-EMC/NCEPLIBS-bacio "$BACIO_REF"
clone NOAA-EMC/NCEPLIBS-w3emc "$W3EMC_REF"
clone NOAA-EMC/NCEPLIBS-ip "$IP_REF"
clone NOAA-EMC/NCEPLIBS-grib_util "$GRIB_UTIL_REF"

build() {  # build <repo> [cmake options...]
  local name=$1; shift
  cmake -S "$WORK/src/$name" -B "$WORK/build/$name" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_PREFIX_PATH="$PREFIX" \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DCMAKE_Fortran_COMPILER="$FC" "$@" > "$WORK/build/$name.cmake.log"
  cmake --build "$WORK/build/$name" --target install -j 4 > "$WORK/build/$name.make.log"
}

build NCEPLIBS-bacio
build NCEPLIBS-w3emc -DBUILD_4=ON -DBUILD_D=ON -DBUILD_WITH_BUFR=OFF
build NCEPLIBS-ip -DOPENMP=OFF

LIB=$PREFIX/lib
[[ -d $LIB ]] || LIB=$PREFIX/lib64

# The legacy program: same flags as gfs-utils' CMakeLists.txt for GNU
# (-fdefault-real-8 -fconvert=big-endian; -fdefault-integer-4 is not a
# gfortran option and 4-byte integers are the default anyway), plus the
# options current gfortran needs to accept the 1986-style argument passing.
$FC -O2 -std=legacy -fallow-argument-mismatch -fdefault-real-8 -fconvert=big-endian \
    -DW3EMC_V2_10 -I"$PREFIX/include_d" -I"$PREFIX/include" \
    "$WORK/src/gfs-utils/src/fbwndgfs.fd/fbwndgfs.F" "$HERE/xstore_shim.f90" \
    -o "$WORK/bin/fbwndgfs.x" \
    "$LIB/libip_d.a" "$LIB/libw3emc_d.a" "$LIB/libbacio.a" -llapack -lblas

$FC -O2 -fallow-argument-mismatch -I"$PREFIX/include_4" "$HERE/mkgrib1.f90" \
    -o "$WORK/bin/mkgrib1" "$LIB/libw3emc_4.a" "$LIB/libbacio.a"

$FC -cpp -O2 -std=legacy -fallow-argument-mismatch -I"$PREFIX/include_4" \
    "$WORK/src/NCEPLIBS-grib_util/src/grbindex/grbindex.f" \
    -o "$WORK/bin/grbindex" "$LIB/libw3emc_4.a" "$LIB/libbacio.a"

echo "built: $(ls "$WORK/bin" | tr '\n' ' ')"
echo "export FBWNDGFS_LEGACY_DIR=$WORK/bin"
