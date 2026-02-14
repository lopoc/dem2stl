# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rasterio",
#     "numpy",
#     "pyproj",
#     "pytest",
# ]
# ///

import math
import os
import shutil
import struct
import subprocess
import tempfile

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds


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


def snap_bounds_like_script(tif_path, sw_lon, sw_lat, ne_lon, ne_lat,
                           ref_lon=None, ref_lat=None):
    """Replicate the per-edge + snap logic from dem2stl.py / demcrop.py."""
    with rasterio.open(tif_path) as src:
        file_crs = src.crs
        transformer = Transformer.from_crs("EPSG:4326", file_crs, always_xy=True)

        # Default to GeoTIFF center (same as scripts)
        inv_transformer = Transformer.from_crs(file_crs, "EPSG:4326", always_xy=True)
        tif_cx = src.transform.c + (src.width / 2) * src.transform.a
        tif_cy = src.transform.f + (src.height / 2) * src.transform.e
        tif_clon, tif_clat = inv_transformer.transform(tif_cx, tif_cy)

        rlat = ref_lat if ref_lat is not None else tif_clat
        rlon = ref_lon if ref_lon is not None else tif_clon
        left, _ = transformer.transform(sw_lon, rlat)
        right, _ = transformer.transform(ne_lon, rlat)
        _, bottom = transformer.transform(rlon, sw_lat)
        _, top = transformer.transform(rlon, ne_lat)

        window = window_from_bounds(left, bottom, right, top, src.transform)
        col_off = int(window.col_off)
        row_off = int(window.row_off)
        col_end = math.ceil(window.col_off + window.width)
        row_end = math.ceil(window.row_off + window.height)
        window = rasterio.windows.Window(col_off, row_off, col_end - col_off, row_end - row_off)

        return rasterio.windows.bounds(window, src.transform)


def make_large_test_tif(path, rows=500, cols=500):
    """Create a larger DEM in UTM 32N covering ~5km, 10m pixel size."""
    cx, cy = 870000, 4715000
    pixel_size = 10
    west = cx - cols * pixel_size // 2
    east = cx + cols * pixel_size // 2
    south = cy - rows * pixel_size // 2
    north = cy + rows * pixel_size // 2
    transform = from_bounds(west, south, east, north, cols, rows)
    data = np.linspace(500, 1500, rows * cols, dtype=np.float32).reshape(rows, cols)
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


def test_adjacent_tiles_auto_align():
    """Tiles from the same GeoTIFF align automatically (default ref = TIF center)."""
    with tempfile.TemporaryDirectory() as tmp:
        tif = os.path.join(tmp, "large.tif")
        make_large_test_tif(tif)
        pixel_size = 10

        # Horizontal pair — no ref_lon/ref_lat, uses GeoTIFF center automatically
        mid_lon = 13.53
        west = snap_bounds_like_script(tif, 13.50, 42.46, mid_lon, 42.48)
        east = snap_bounds_like_script(tif, mid_lon, 42.46, 13.56, 42.48)

        x_overlap = west[2] - east[0]
        assert 0 <= x_overlap <= pixel_size, (
            f"X boundary issue: west right={west[2]}, east left={east[0]}"
        )
        # Same Y range (same GeoTIFF center ref_lon + same lat range)
        assert west[1] == east[1], f"Y bottom mismatch: {west[1]} vs {east[1]}"
        assert west[3] == east[3], f"Y top mismatch: {west[3]} vs {east[3]}"

        # Vertical pair
        mid_lat = 42.47
        south = snap_bounds_like_script(tif, 13.50, 42.46, 13.56, mid_lat)
        north = snap_bounds_like_script(tif, 13.50, mid_lat, 13.56, 42.48)

        y_overlap = south[3] - north[1]
        assert 0 <= y_overlap <= pixel_size, (
            f"Y boundary issue: south top={south[3]}, north bottom={north[1]}"
        )
        # Same X range (same GeoTIFF center ref_lat + same lon range)
        assert south[0] == north[0], f"X left mismatch: {south[0]} vs {north[0]}"
        assert south[2] == north[2], f"X right mismatch: {south[2]} vs {north[2]}"
