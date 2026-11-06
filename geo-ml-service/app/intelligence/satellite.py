"""Vegetation, forest and surface-water intelligence from Sentinel-2 L2A and ESA WorldCover.

Public Earth Search STAC + open COGs; no credentials. NDVI/NDWI are computed from real
reflectance with the scene-classification (SCL) mask; previews are decimated to <= 256 px.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from .common import cached, colorize, key_bbox, ok, overlay
from .raster_io import coverage, mosaic, read_band, stac_search

WC_CLASSES = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up", 60: "Bare / sparse", 70: "Snow / ice", 80: "Water", 90: "Wetland", 95: "Mangroves", 100: "Moss / lichen"}
VALID_SCL = (4, 5, 6, 7)


def indices(red: np.ndarray, nir: np.ndarray, green: np.ndarray, scl: np.ndarray) -> dict[str, np.ndarray]:
    """Pure function: reflectance (DN/10000) arrays -> masked NDVI, NDWI, water, valid masks."""
    valid = np.isin(scl, VALID_SCL) & np.isfinite(red) & np.isfinite(nir) & np.isfinite(green) & ((red + nir) > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(valid, (nir - red) / (nir + red), np.nan)
        ndwi = np.where(valid, (green - nir) / (green + nir), np.nan)
    water = valid & ((ndwi > 0.15) | (scl == 6))
    return {"ndvi": ndvi, "ndwi": ndwi, "water": water, "valid": valid}


def vegetation_stats(ndvi: np.ndarray) -> dict[str, Any]:
    v = ndvi[np.isfinite(ndvi)]
    if v.size < 25:
        raise ValueError("too few cloud-free pixels")
    cls = {"dense (>0.6)": (0.6, 9), "moderate (0.3-0.6)": (0.3, 0.6), "sparse (0.15-0.3)": (0.15, 0.3), "bare / water (<0.15)": (-9, 0.15)}
    return {"mean_ndvi": round(float(v.mean()), 3), "median_ndvi": round(float(np.median(v)), 3), "p10_p90": [round(float(np.percentile(v, 10)), 2), round(float(np.percentile(v, 90)), 2)],
            "density_pct": {k: round(100 * float(((v >= lo) & (v < hi)).mean()), 1) for k, (lo, hi) in cls.items()}}


def change_stats(ndvi_now: np.ndarray, ndvi_prev: np.ndarray, tree: np.ndarray | None) -> dict[str, Any] | None:
    both = np.isfinite(ndvi_now) & np.isfinite(ndvi_prev)
    if both.sum() < 25:
        return None
    d = ndvi_now - ndvi_prev
    out = {"mean_ndvi_change": round(float(d[both].mean()), 3), "pixels_compared": int(both.sum()),
           "declined_pct": round(100 * float((d[both] < -0.2).mean()), 1), "improved_pct": round(100 * float((d[both] > 0.2).mean()), 1)}
    if tree is not None and (both & tree).sum() >= 25:
        m = both & tree
        out["tree_pixels_with_decline_pct"] = round(100 * float((d[m] < -0.2).mean()), 1)
    return out


def _scene_arrays(item: dict[str, Any], bbox: list[float], shp: tuple[int, int] | None = None):
    a = item["assets"]
    red, shp, res = read_band(a["red"]["href"], bbox, shp)
    nir, _, _ = read_band(a["nir"]["href"], bbox, shp)
    green, _, _ = read_band(a["green"]["href"], bbox, shp)
    scl, _, _ = read_band(a["scl"]["href"], bbox, shp, resampling=__import__("rasterio").enums.Resampling.nearest)
    return indices(red / 10000.0, nir / 10000.0, green / 10000.0, np.nan_to_num(scl, nan=0).astype(int)), shp, res


def _pick_scene(bbox: list[float], dt: str, max_cloud: int = 35, need: int = 8) -> list[dict[str, Any]]:
    items = stac_search("sentinel-2-l2a", bbox, datetime=dt, limit=40, query={"eo:cloud_cover": {"lt": max_cloud}})
    items = [i for i in items if all(k in i.get("assets", {}) for k in ("red", "nir", "green", "scl")) and coverage(i, bbox) > 0.3]
    items.sort(key=lambda i: (-round(coverage(i, bbox), 1), i["properties"]["datetime"]), reverse=False)
    # prefer the most complete footprint coverage, then most recent
    items.sort(key=lambda i: (round(coverage(i, bbox), 1), i["properties"]["datetime"]), reverse=True)
    return items[:need]


def _worldcover(bbox: list[float]) -> np.ndarray | None:
    try:
        items = stac_search("esa-worldcover", bbox, datetime="2021-01-01/2021-12-31", limit=10, sort_desc=False)
        hrefs = [i["assets"]["map"]["href"] for i in items if "map" in i.get("assets", {})]
        return mosaic(hrefs, bbox) if hrefs else None
    except Exception:  # noqa: BLE001 - land cover is a complement, not required for NDVI
        return None


def _resize_nearest(a: np.ndarray, shp: tuple[int, int]) -> np.ndarray:
    ri = (np.arange(shp[0]) * a.shape[0] / shp[0]).astype(int); ci = (np.arange(shp[1]) * a.shape[1] / shp[1]).astype(int)
    return a[np.ix_(ri, ci)]


def landcover_stats(wc: np.ndarray) -> dict[str, Any]:
    v = wc[np.isfinite(wc)].astype(int)
    if v.size == 0:
        raise ValueError("no land-cover pixels")
    shares = {WC_CLASSES.get(c, str(c)): round(100 * float((v == c).mean()), 1) for c in np.unique(v)}
    return {"classes_pct": dict(sorted(shares.items(), key=lambda kv: -kv[1])), "forest_cover_pct": round(100 * float(np.isin(v, (10, 95)).mean()), 1),
            "cropland_pct": round(100 * float((v == 40).mean()), 1), "built_up_pct": round(100 * float((v == 50).mean()), 1)}


def vegetation(bbox: list[float]) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        today = date.today()
        scenes = _pick_scene(bbox, f"{(today - timedelta(days=120)).isoformat()}/{today.isoformat()}")
        if not scenes:
            scenes = _pick_scene(bbox, f"{(today - timedelta(days=365)).isoformat()}/{today.isoformat()}", 50)
        chosen = None
        for it in scenes:
            try:
                arrs, shp, res = _scene_arrays(it, bbox)
            except Exception:  # noqa: BLE001 - try the next scene
                continue
            if arrs["valid"].mean() >= 0.4:
                chosen = (it, arrs, shp, res); break
        if not chosen:
            raise RuntimeError("no usable cloud-free Sentinel-2 scene found")
        item, arrs, shp, res = chosen
        when = item["properties"]["datetime"][:10]
        out: dict[str, Any] = {"scene": {"id": item["id"], "date": when, "cloud_cover_pct": round(item["properties"].get("eo:cloud_cover", float("nan")), 1),
                                         "footprint_coverage_pct": round(100 * coverage(item, bbox), 0), "native_resolution_m": 10},
                               "valid_pixel_pct": round(100 * float(arrs["valid"].mean()), 0), "vegetation": vegetation_stats(arrs["ndvi"])}
        out["scene"]["preview_grid"] = f"{shp[0]}x{shp[1]} px (decimated from 10 m)"
        wv = arrs["water"].sum() / max(1, arrs["valid"].sum())
        out["surface_water"] = {"water_fraction_pct": round(100 * float(wv), 2), "method": "NDWI>0.15 or Sentinel-2 SCL water class, cloud-masked"}
        wc = _worldcover(bbox)
        tree = None
        if wc is not None:
            try:
                out["land_cover"] = {**landcover_stats(wc), "source": "ESA WorldCover 10 m, 2021"}
                tree = _resize_nearest(wc, shp) == 10
            except Exception:  # noqa: BLE001
                pass
        # Same-season comparison one year earlier from the same tile (identical grid).
        try:
            d0 = datetime.fromisoformat(when)
            prev_dt = f"{(d0 - timedelta(days=410)).date()}/{(d0 - timedelta(days=320)).date()}"
            tile = item["properties"].get("grid:code") or item["properties"].get("s2:mgrs_tile")
            cands = [p for p in _pick_scene(bbox, prev_dt, 40, 10) if (p["properties"].get("grid:code") or p["properties"].get("s2:mgrs_tile")) == tile]
            for p in cands:
                parr, _, _ = _scene_arrays(p, bbox, shp)
                if parr["valid"].mean() < 0.4:
                    continue
                ch = change_stats(arrs["ndvi"], parr["ndvi"], tree)
                if ch:
                    ch.update({"previous_scene_date": p["properties"]["datetime"][:10], "note": "Same season, one year earlier. Declines can reflect drought, harvest or fire as well as clearing; not confirmed deforestation."})
                    ch["water_fraction_change_pp"] = round(100 * float(wv) - 100 * float(parr["water"].sum() / max(1, parr["valid"].sum())), 2)
                    out["change"] = ch
                    break
        except Exception:  # noqa: BLE001 - historical comparison is optional
            pass
        stops = [(-0.1, (120, 90, 60)), (0.15, (214, 190, 110)), (0.35, (160, 200, 90)), (0.6, (60, 160, 70)), (0.9, (10, 90, 40))]
        out["_overlays"] = [overlay("ndvi", f"NDVI ({when})", colorize(arrs["ndvi"], stops, alpha=190), bbox,
                                    [{"color": "#785a3c", "label": "<0.1 bare"}, {"color": "#a0c85a", "label": "0.35"}, {"color": "#0a5a28", "label": ">0.8 dense"}], "Sentinel-2 L2A, cloud-masked")]
        wrgba = np.zeros(arrs["water"].shape + (4,), dtype=np.uint8); wrgba[arrs["water"]] = (40, 140, 255, 200)
        out["_overlays"].append(overlay("water", "Surface water", wrgba, bbox, [{"color": "#288cff", "label": "water"}], "Sentinel-2 NDWI / SCL"))
        if wc is not None:
            colors = {10: (0, 100, 0), 20: (255, 187, 34), 30: (255, 255, 76), 40: (240, 150, 255), 50: (250, 0, 0), 60: (180, 180, 180), 70: (240, 240, 240), 80: (0, 100, 200), 90: (0, 150, 160), 95: (0, 207, 117), 100: (250, 230, 160)}
            lc = np.zeros(wc.shape + (4,), dtype=np.uint8)
            for k, rgb in colors.items():
                lc[wc == k] = (*rgb, 190)
            out["_overlays"].append(overlay("landcover", "Land cover (2021)", lc, bbox, [{"color": "#006400", "label": "tree"}, {"color": "#f096ff", "label": "crop"}, {"color": "#fa0000", "label": "built"}, {"color": "#0064c8", "label": "water"}], "ESA WorldCover"))
        out["source"] = "Sentinel-2 L2A (Earth Search STAC), ESA WorldCover 2021"
        return out
    return cached(("veg", key_bbox(bbox)), 12 * 3600, run)
