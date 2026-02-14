# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rasterio",
#     "numpy",
#     "pyproj",
# ]
# ///

import argparse
import math
import os
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds


def main():
    parser = argparse.ArgumentParser(
        description="Crop a GeoTIFF DEM to a lat/lon bounding box.",
        epilog="Example: uv run demcrop.py dem.tif --bounds 13.3 42.35 13.65 42.55",
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
        "--ref-lon",
        type=float,
        default=None,
        metavar="LON",
        help="Reference longitude for Y computation. "
        "Set to the same value for all tiles to ensure matching Y bounds. "
        "Default: center longitude of the GeoTIFF.",
    )
    parser.add_argument(
        "--ref-lat",
        type=float,
        default=None,
        metavar="LAT",
        help="Reference latitude for X computation. "
        "Set to the same value for all tiles to ensure matching X bounds. "
        "Default: center latitude of the GeoTIFF.",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output GeoTIFF file. Default: <input_name>_crop.tif",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input}")
        sys.exit(1)

    try:
        with rasterio.open(args.input) as src:
            src.read(1, window=rasterio.windows.Window(0, 0, 1, 1))
    except rasterio.errors.RasterioIOError:
        print(f"Error: not a valid GeoTIFF: {args.input}")
        sys.exit(1)

    output = args.output or os.path.splitext(args.input)[0] + "_crop.tif"
    sw_lon, sw_lat, ne_lon, ne_lat = args.bounds

    with rasterio.open(args.input) as src:
        file_crs = src.crs
        transformer = Transformer.from_crs("EPSG:4326", file_crs, always_xy=True)

        # Per-edge projection: X at ref_lat, Y at ref_lon.
        # Default to GeoTIFF center so all tiles from the same file align automatically.
        inv_transformer = Transformer.from_crs(file_crs, "EPSG:4326", always_xy=True)
        tif_center_x = src.transform.c + (src.width / 2) * src.transform.a
        tif_center_y = src.transform.f + (src.height / 2) * src.transform.e
        tif_center_lon, tif_center_lat = inv_transformer.transform(tif_center_x, tif_center_y)
        ref_lat = args.ref_lat if args.ref_lat is not None else tif_center_lat
        ref_lon = args.ref_lon if args.ref_lon is not None else tif_center_lon
        left, _ = transformer.transform(sw_lon, ref_lat)
        right, _ = transformer.transform(ne_lon, ref_lat)
        _, bottom = transformer.transform(ref_lon, sw_lat)
        _, top = transformer.transform(ref_lon, ne_lat)

        # Snap outward to pixel grid (tiles share 1 pixel at boundaries)
        window = from_bounds(left, bottom, right, top, src.transform)
        col_off = int(window.col_off)
        row_off = int(window.row_off)
        col_end = math.ceil(window.col_off + window.width)
        row_end = math.ceil(window.row_off + window.height)
        window = rasterio.windows.Window(col_off, row_off, col_end - col_off, row_end - row_off)

        data = src.read(1, window=window)
        transform = src.window_transform(window)
        nodata = src.nodata

        profile = src.profile.copy()
        profile.update(
            height=data.shape[0],
            width=data.shape[1],
            transform=transform,
        )

        with rasterio.open(output, "w", **profile) as dst:
            dst.write(data, 1)

    valid = data[data != nodata] if nodata is not None else data.ravel()
    print(f"Cropped: {data.shape[1]}x{data.shape[0]} pixels")
    print(f"Elevation range: {valid.min():.0f} - {valid.max():.0f} m")
    print(f"Saved to: {output}")


if __name__ == "__main__":
    main()
