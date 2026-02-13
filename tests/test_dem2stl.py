# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rasterio",
#     "numpy",
#     "pyproj",
#     "pytest",
# ]
# ///

import os
import shutil
import struct
import subprocess
import tempfile

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds


def make_test_tif(path, rows=10, cols=10):
    """Create a tiny GeoTIFF with a synthetic elevation ramp (100-200m).

    Centered around lon=13.5, lat=42.55 in UTM 32N, 1km pixel size.
    """
    cx, cy = 869500, 4720500
    pixel_size = 1000
    west = cx - cols * pixel_size // 2
    east = cx + cols * pixel_size // 2
    south = cy - rows * pixel_size // 2
    north = cy + rows * pixel_size // 2
    transform = from_bounds(west, south, east, north, cols, rows)
    data = np.linspace(100, 200, rows * cols, dtype=np.float32).reshape(rows, cols)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(32632),
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(data, 1)
    return data


def read_stl_triangle_count(path):
    with open(path, "rb") as f:
        f.read(80)  # header
        return struct.unpack("<I", f.read(4))[0]


def test_basic_run():
    """Generate STL from synthetic DEM and check output is valid binary STL."""
    with tempfile.TemporaryDirectory() as tmp:
        tif = os.path.join(tmp, "test.tif")
        stl = os.path.join(tmp, "test.stl")
        rows, cols = 5, 5

        make_test_tif(tif, rows=rows, cols=cols)

        # Bounds that cover the entire test tile (UTM 32N -> lat/lon)
        result = subprocess.run(
            [
                "uv", "run", "dem2stl.py",
                tif,
                "--bounds", "13.48", "42.54", "13.52", "42.56",
                "--output", stl,
            ],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}\n{result.stdout}"
        assert os.path.isfile(stl)

        # Binary STL: 80 header + 4 count + 50 bytes per triangle
        n_tri = read_stl_triangle_count(stl)
        expected_size = 80 + 4 + n_tri * 50
        assert os.path.getsize(stl) == expected_size
        assert n_tri > 0


def test_base_height_no_clip():
    """With --base-height below all terrain, no clipping prompt should appear."""
    with tempfile.TemporaryDirectory() as tmp:
        tif = os.path.join(tmp, "test.tif")
        stl = os.path.join(tmp, "test.stl")
        make_test_tif(tif, rows=4, cols=4)

        result = subprocess.run(
            [
                "uv", "run", "dem2stl.py",
                tif,
                "--bounds", "13.48", "42.54", "13.52", "42.56",
                "--base-height", "50",
                "--output", stl,
            ],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}\n{result.stdout}"
        assert os.path.isfile(stl)
        assert read_stl_triangle_count(stl) > 0


def test_invalid_geotiff():
    """Passing a non-GeoTIFF file should fail with a clear error."""
    with tempfile.TemporaryDirectory() as tmp:
        fake = os.path.join(tmp, "fake.tif")
        with open(fake, "w") as f:
            f.write("not a geotiff")

        result = subprocess.run(
            [
                "uv", "run", "dem2stl.py",
                fake,
                "--bounds", "13.48", "42.54", "13.52", "42.56",
            ],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 1
        assert "not a valid GeoTIFF" in result.stdout
