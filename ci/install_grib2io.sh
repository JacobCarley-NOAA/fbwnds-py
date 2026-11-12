#!/usr/bin/env bash
# Build NCEPLIBS-g2c and install grib2io against it.
#
#   ci/install_grib2io.sh <prefix>
#
# grib2io publishes no Linux wheels, so it is built from source against a
# g2c shared library installed under <prefix>.  NCEPLIBS-ip is optional for
# grib2io and not needed by fbwndgfs, so it is not built.
#
# Needs: git, cmake >= 3.18, a C compiler, libaec, libpng and openjpeg
# development headers (Ubuntu: libaec-dev libpng-dev libopenjp2-7-dev).
# Afterwards, put <prefix>/lib on LD_LIBRARY_PATH.
set -euo pipefail

PREFIX=${1:?usage: install_grib2io.sh <prefix>}
G2C_REF=${G2C_REF:-v2.3.0}
GRIB2IO_VERSION=${GRIB2IO_VERSION:-2.8.2}

mkdir -p "$PREFIX"
PREFIX=$(cd "$PREFIX" && pwd)
SRC=$(mktemp -d)
trap 'rm -rf "$SRC"' EXIT

git clone -q --depth 1 --branch "$G2C_REF" https://github.com/NOAA-EMC/NCEPLIBS-g2c.git "$SRC/g2c"
cmake -S "$SRC/g2c" -B "$SRC/build" \
      -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
      -DBUILD_SHARED_LIBS=ON -DBUILD_STATIC_LIBS=OFF \
      -DUSE_Jasper=OFF -DUSE_OpenJPEG=ON -DUSE_AEC=ON -DUSE_PNG=ON > "$SRC/cmake.log"
cmake --build "$SRC/build" --target install -j 4 > "$SRC/build.log"

G2C_DIR=$PREFIX python -m pip install --no-binary grib2io "grib2io==$GRIB2IO_VERSION"
echo "g2c $G2C_REF and grib2io $GRIB2IO_VERSION installed; add $PREFIX/lib to LD_LIBRARY_PATH"
