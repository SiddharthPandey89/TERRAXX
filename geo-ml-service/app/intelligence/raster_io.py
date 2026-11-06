"""STAC search (Earth Search, no credentials) and windowed COG reads for small previews."""
from __future__ import annotations

from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, shape

from .common import http

STAC = "https://earth-search.aws.element84.com/v1/search"
MAX_PX = 256
GDAL = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff", GDAL_HTTP_MAX_RETRY="2",
            GDAL_HTTP_RETRY_DELAY="1", GDAL_HTTP_TIMEOUT="20", GDAL_HTTP_CONNECTTIMEOUT="8", AWS_NO_SIGN_REQUEST="YES")


def stac_search(collection: str, bbox: list[float], datetime: str | None = None, limit: int = 12, query: dict | None = None, sort_desc: bool = True) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"collections": [collection], "bbox": bbox, "limit": limit}
    if datetime:
        body["datetime"] = datetime
    if query:
        body["query"] = query
    if sort_desc:
        body["sortby"] = [{"field": "properties.datetime", "direction": "desc"}]
    with http(25) as c:
        r = c.post(STAC, json=body)
        r.raise_for_status()
        return r.json().get("features", [])


def coverage(item: dict[str, Any], bbox: list[float]) -> float:
    b = box(*bbox)
    return float(shape(item["geometry"]).intersection(b).area / b.area) if b.area else 0.0


def out_shape_for(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, MAX_PX / max(width, height, 1))
    return max(1, int(round(height * scale))), max(1, int(round(width * scale)))


def read_band(href: str, bbox: list[float], shape_hw: tuple[int, int] | None = None, resampling: Resampling = Resampling.bilinear) -> tuple[np.ndarray, tuple[int, int], float]:
    """Read ``bbox`` (WGS84) from a COG. Returns (array, (h, w), native_pixel_m)."""
    with rasterio.Env(**GDAL), rasterio.open(href) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
        win = from_bounds(left, bottom, right, top, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
        shp = shape_hw or out_shape_for(int(win.width), int(win.height))
        arr = src.read(1, window=win, out_shape=shp, resampling=resampling, masked=True)
        res = abs(src.transform.a)
        if src.crs and src.crs.is_geographic:
            res *= 111320.0
        return np.ma.filled(arr.astype("float64"), np.nan), shp, float(res)


def mosaic(hrefs: list[str], bbox: list[float], resampling: Resampling = Resampling.nearest) -> np.ndarray:
    """Mosaic EPSG:4326 tiles (DEM, WorldCover) over bbox at <= MAX_PX."""
    w, s, e, n = bbox
    res = max(e - w, n - s) / MAX_PX
    with rasterio.Env(**GDAL):
        srcs = [rasterio.open(h) for h in hrefs]
        try:
            data, _ = merge(srcs, bounds=(w, s, e, n), res=res, resampling=resampling, nodata=srcs[0].nodata)
            arr = data[0].astype("float64")
            if srcs[0].nodata is not None:
                arr[arr == srcs[0].nodata] = np.nan
            return arr
        finally:
            for x in srcs:
                x.close()
