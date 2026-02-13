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
import subprocess
import tempfile

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


def make_test_tif(path, rows=10, cols=10):
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


def test_basic_crop():
    """Crop a synthetic DEM and check output is a valid GeoTIFF."""
    with tempfile.TemporaryDirectory() as tmp:
        tif = os.path.join(tmp, "test.tif")
        out = os.path.join(tmp, "test_crop.tif")
        make_test_tif(tif, rows=10, cols=10)

        result = subprocess.run(
            [
                "uv", "run", "demcrop.py",
                tif,
                "--bounds", "13.48", "42.54", "13.52", "42.56",
                "--output", out,
            ],
            capture_output=True, text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}\n{result.stdout}"
        assert os.path.isfile(out)

        with rasterio.open(out) as src:
            data = src.read(1)
            assert data.size > 0


def test_invalid_geotiff():
    """Passing a non-GeoTIFF file should fail with a clear error."""
    with tempfile.TemporaryDirectory() as tmp:
        fake = os.path.join(tmp, "fake.tif")
        with open(fake, "w") as f:
            f.write("not a geotiff")

        result = subprocess.run(
            [
                "uv", "run", "demcrop.py",
                fake,
                "--bounds", "13.48", "42.54", "13.52", "42.56",
            ],
            capture_output=True, text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 1
        assert "not a valid GeoTIFF" in result.stdout
