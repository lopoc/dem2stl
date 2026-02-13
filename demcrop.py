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
        left, bottom = transformer.transform(sw_lon, sw_lat)
        right, top = transformer.transform(ne_lon, ne_lat)

        window = from_bounds(left, bottom, right, top, src.transform)
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
