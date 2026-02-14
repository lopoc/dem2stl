# Changelog

## v0.2.0

### Tile alignment fix

Adjacent tiles generated from the same GeoTIFF now align automatically — no manual coordination needed.

**Problem:** WGS84→UTM conversion is non-linear. The same meridian maps to different UTM X values at different latitudes, causing gaps (up to 125m) or offsets (up to 110m) between adjacent tiles.

**Fix:** Bounds are now computed per-edge using a shared reference point (the GeoTIFF center by default). X bounds are projected at the reference latitude, Y bounds at the reference longitude. This guarantees that tiles sharing the same lat or lon boundary produce identical UTM coordinates at that edge.

### Changes

- **Per-edge projection** in both `dem2stl.py` and `demcrop.py`: X computed at ref latitude, Y at ref longitude
- **Pixel grid snapping**: crop windows snap outward to the raster grid (floor start, ceil end), so tiles share at most 1 pixel at boundaries
- **`--ref-lon` / `--ref-lat`** parameters: override the reference point for cross-file tiling. Default: GeoTIFF center (automatic alignment for tiles from the same file)
- **`--base-thickness`** parameter in `dem2stl.py`: fixed base thickness in mm (default: 2mm), replacing the previous percentage-based calculation that caused steps between tiles
- **Tests**: added `test_adjacent_tiles_auto_align` verifying horizontal and vertical tile pairs align automatically

## v0.1.0

Initial release.

- GeoTIFF DEM to watertight binary STL conversion
- Lat/lon bounding box crop with `--bounds`
- Configurable scale (`--scale`), base height (`--base-height`)
- `demcrop.py` utility for cropping GeoTIFFs
