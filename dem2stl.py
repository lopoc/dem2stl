# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rasterio",
#     "numpy",
#     "pyproj",
# ]
# ///

import argparse
import os
import struct
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert GeoTIFF DEM to watertight STL for 3D printing.",
        epilog="Example: uv run dem2stl.py dem.tif --bounds 13.53 42.44 13.60 42.50",
    )
    parser.add_argument("input", help="Input GeoTIFF file (.tif)")
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        required=True,
        metavar=("SW_LON", "SW_LAT", "NE_LON", "NE_LAT"),
        help="Crop rectangle as SW longitude, SW latitude, NE longitude, NE latitude (EPSG:4326)",
    )
    parser.add_argument(
        "--base-height",
        type=float,
        default=None,
        metavar="METERS",
        help="Absolute elevation (m) for the model base. "
        "Terrain below this is clipped flat. "
        "Default: minimum elevation in the crop.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=10000,
        metavar="N",
        help="Map scale 1:N. Default: 10000 (1km = 100mm).",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output STL file. Default: <input_name>.stl",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input}")
        sys.exit(1)

    try:
        with rasterio.open(args.input) as src:
            src.read(1, window=rasterio.windows.Window(0, 0, 1, 1))
    except rasterio.errors.RasterioIOError:
        print(f"Error: not a valid GeoTIFF: {args.input}")
        sys.exit(1)

    output = args.output or os.path.splitext(args.input)[0] + ".stl"
    sw_lon, sw_lat, ne_lon, ne_lat = args.bounds
    mm_per_m = 1000.0 / args.scale

    # --- CROP ---
    with rasterio.open(args.input) as src:
        file_crs = src.crs
        transformer = Transformer.from_crs("EPSG:4326", file_crs, always_xy=True)
        left, bottom = transformer.transform(sw_lon, sw_lat)
        right, top = transformer.transform(ne_lon, ne_lat)
        print(f"CRS: {file_crs}")
        print(f"Projected bounds: {left:.0f}, {bottom:.0f} -> {right:.0f}, {top:.0f}")

        window = from_bounds(left, bottom, right, top, src.transform)
        dem = src.read(1, window=window).astype(np.float32)
        nodata = src.nodata
        pixel_size = src.transform[0]  # meters per pixel

    print(f"DEM cropped: {dem.shape[1]}x{dem.shape[0]} pixels")
    print(f"Pixel size: {pixel_size:.1f} m")
    print(f"Scale: 1:{args.scale}")

    # Replace nodata
    mask = dem == nodata if nodata is not None else np.zeros_like(dem, dtype=bool)
    valid = dem[~mask]
    if valid.size == 0:
        print("Error: crop contains no valid elevation data.")
        sys.exit(1)

    min_elev = float(valid.min())
    max_elev = float(valid.max())
    dem[mask] = min_elev
    print(f"Elevation: {min_elev:.0f} - {max_elev:.0f} m")

    # Base height
    base_height = args.base_height if args.base_height is not None else min_elev

    below_count = int(np.sum(dem < base_height))
    if below_count > 0:
        below_min = float(dem[dem < base_height].min())
        total = dem.size
        print(
            f"\nWarning: {below_count}/{total} pixels ({below_count/total*100:.1f}%) "
            f"are below base height {base_height:.0f} m (lowest: {below_min:.0f} m)."
        )
        answer = input("Clip these to base height and continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)
        dem = np.maximum(dem, base_height)

    # Scale to mm: XY = pixel_index * pixel_size * mm_per_m, Z = (elev - base) * mm_per_m
    xy_step = pixel_size * mm_per_m  # mm between pixels
    dem = (dem - base_height) * mm_per_m
    base_z = -0.05 * dem.max()  # 5% base thickness

    rows, cols = dem.shape
    x_size = (cols - 1) * xy_step
    y_size = (rows - 1) * xy_step
    z_size = float(dem.max())
    print(f"Print size: {x_size:.1f} x {y_size:.1f} x {z_size:.1f} mm")

    # --- STL ---
    triangles = []

    print(f"\n[1/3] Top surface ({(rows-1)*(cols-1)*2} triangles)...")
    for i in range(rows - 1):
        if i % 50 == 0:
            print(f"\r  {i/(rows-1)*100:.0f}%", end="", flush=True)
        for j in range(cols - 1):
            x0, x1 = j * xy_step, (j + 1) * xy_step
            y0, y1 = (rows - 1 - i) * xy_step, (rows - 1 - (i + 1)) * xy_step
            z00, z10, z01, z11 = dem[i, j], dem[i, j + 1], dem[i + 1, j], dem[i + 1, j + 1]
            triangles.append(((x0, y0, z00), (x0, y1, z01), (x1, y0, z10)))
            triangles.append(((x1, y0, z10), (x0, y1, z01), (x1, y1, z11)))
    print("\r  100%")

    print("[2/3] Bottom surface (2 triangles)...")
    xmax = (cols - 1) * xy_step
    ymax = (rows - 1) * xy_step
    triangles.append(((0.0, 0.0, base_z), (0.0, ymax, base_z), (xmax, 0.0, base_z)))
    triangles.append(((xmax, ymax, base_z), (xmax, 0.0, base_z), (0.0, ymax, base_z)))
    print("  Done")

    print("[3/3] Side walls...")
    for j in range(cols - 1):
        x0, x1 = j * xy_step, (j + 1) * xy_step
        y = (rows - 1) * xy_step
        triangles.append(((x0, y, dem[0, j]), (x1, y, dem[0, j + 1]), (x0, y, base_z)))
        triangles.append(((x1, y, dem[0, j + 1]), (x1, y, base_z), (x0, y, base_z)))
    for j in range(cols - 1):
        x0, x1 = j * xy_step, (j + 1) * xy_step
        triangles.append(((x0, 0.0, dem[-1, j]), (x0, 0.0, base_z), (x1, 0.0, dem[-1, j + 1])))
        triangles.append(((x1, 0.0, dem[-1, j + 1]), (x0, 0.0, base_z), (x1, 0.0, base_z)))
    for i in range(rows - 1):
        y0, y1 = (rows - 1 - i) * xy_step, (rows - 1 - (i + 1)) * xy_step
        triangles.append(((0.0, y0, dem[i, 0]), (0.0, y0, base_z), (0.0, y1, dem[i + 1, 0])))
        triangles.append(((0.0, y1, dem[i + 1, 0]), (0.0, y0, base_z), (0.0, y1, base_z)))
    for i in range(rows - 1):
        y0, y1 = (rows - 1 - i) * xy_step, (rows - 1 - (i + 1)) * xy_step
        x = (cols - 1) * xy_step
        triangles.append(((x, y0, dem[i, -1]), (x, y1, dem[i + 1, -1]), (x, y0, base_z)))
        triangles.append(((x, y1, dem[i + 1, -1]), (x, y1, base_z), (x, y0, base_z)))
    print("  Done")

    print(f"\nWriting STL ({len(triangles)} triangles)...")
    with open(output, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(triangles)))
        for idx, tri in enumerate(triangles):
            if idx % 200000 == 0:
                print(f"\r  {idx/len(triangles)*100:.0f}%", end="", flush=True)
            v0, v1, v2 = np.array(tri[0]), np.array(tri[1]), np.array(tri[2])
            n = np.cross(v1 - v0, v2 - v0)
            norm = np.linalg.norm(n)
            if norm > 0:
                n /= norm
            f.write(struct.pack("<fff", *n))
            for v in tri:
                f.write(struct.pack("<fff", *v))
            f.write(struct.pack("<H", 0))

    print("\r  100%")
    size_mb = os.path.getsize(output) / 1024 / 1024
    print(f"\n{output} ({size_mb:.1f} MB, {len(triangles)} triangles)")


if __name__ == "__main__":
    main()
