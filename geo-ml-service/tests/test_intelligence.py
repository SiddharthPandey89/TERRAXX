"""Processing tests on synthetic arrays/series (no network). Provider connectivity is checked separately at runtime."""
from datetime import date, timedelta

import numpy as np

from app.api.routes.report import ReportRequest, build_pdf
from app.intelligence import suitability as suit
from app.intelligence.climate import summarize
from app.intelligence.satellite import change_stats, indices, landcover_stats, vegetation_stats
from app.intelligence.soil import fertility
from app.intelligence.terrain import analyze_dem
from app.prospectivity.auto import run_auto


def _climate():
    ts = [date(2015, 1, 1) + timedelta(days=i) for i in range(3652)]
    doy = np.array([t.timetuple().tm_yday for t in ts])
    return summarize({"time": [t.isoformat() for t in ts], "temperature_2m_mean": (25 + 8 * np.sin((doy - 100) / 365 * 6.283)).tolist(),
                      "precipitation_sum": np.where((doy > 170) & (doy < 270), 9.0, 0.3).tolist(), "et0_fao_evapotranspiration": [4.5] * 3652,
                      "wind_speed_10m_max": [15.0] * 3652, "wind_direction_10m_dominant": [225.0] * 3652, "relative_humidity_2m_mean": [60.0] * 3652})


def _terrain():
    y, x = np.mgrid[0:80, 0:80]
    return analyze_dem((100 + 3.0 * x + 20 * np.sin(y / 9)).astype(float), [77, 23, 77.03, 23.03])


def _veg():
    red = np.full((60, 60), 0.08); nir = np.full((60, 60), 0.4); green = np.full((60, 60), 0.1); scl = np.full((60, 60), 4)
    arrs = indices(red, nir, green, scl)
    return arrs, vegetation_stats(arrs["ndvi"])


def test_aspect_direction():
    y, x = np.mgrid[0:60, 0:60]
    assert analyze_dem((100 + 3.0 * x).astype(float), [77, 23, 77.02, 23.02])["aspect_share_pct"]["W"] == 100.0


def test_cloud_mask_and_ndvi():
    red = np.full((20, 20), 0.1); nir = np.full((20, 20), 0.4); scl = np.full((20, 20), 4); scl[:5] = 9
    r = indices(red, nir, np.full((20, 20), 0.1), scl)
    assert abs(np.nanmean(r["ndvi"]) - 0.6) < 1e-9 and r["valid"].mean() == 0.75


def test_change_and_landcover():
    a = np.full((10, 10), 0.7); b = a.copy(); b[:5] = 0.2
    assert change_stats(b, a, np.ones((10, 10), bool))["tree_pixels_with_decline_pct"] == 50.0
    assert landcover_stats(np.array([[10, 40], [80, 10]], float))["forest_cover_pct"] == 50.0


def test_suitability_withholds_without_data():
    assert suit.habitability(None, None, None, None, None)["status"] == "withheld"
    assert suit.agriculture(None, None) is None


def test_prospectivity_withholds_without_evidence():
    r = run_auto([77, 23, 78, 24], None, ["coal"], lambda b, g=None: {"units_per_point": [None] * 16, "points": 16, "answered": 0, "with_units": 0, "coverage": 0, "notes": []},
                 lambda b: {"records": [], "available": False, "notes": [], "search_bbox": b})
    assert all(x["potential_score"] is None for x in r["results"])


def test_pdf_contains_analysis(tmp_path):
    arrs, vg = _veg(); t = _terrain(); ov = t.pop("_dem_overlay"); t.pop("_slope_overlay"); c = _climate()
    fert = fertility({"ph": 6.6, "soc": 14, "nitrogen": 1.4, "cec": 18})
    soil = {"properties": {"clay_pct": 30, "sand_pct": 30, "silt_pct": 40, "ph": 6.6, "organic_carbon_g_per_kg": 14, "nitrogen_g_per_kg": 1.4, "cec_cmol_per_kg": 18}, "depth": "0-30 cm", "texture_class": "clay loam", "fertility": fert, "source": "SoilGrids"}
    veg = {"scene": {"id": "S2X", "date": "2026-10-20", "cloud_cover_pct": 5, "footprint_coverage_pct": 100}, "vegetation": vg, "source": "Sentinel-2"}
    mods = {"climate": c, "terrain": t, "soil": soil, "vegetation": veg, "suitability": {"habitability": suit.habitability(c, {"mapped_features": {"river_segments": 2, "lakes_and_water_bodies": 1}}, veg, soil, t), "agriculture": suit.agriculture(c, soil)}}
    pdf = build_pdf(ReportRequest(region={"name": "Test", "bbox": [77, 23, 77.03, 23.03]}, modules=mods, overlays=[ov]))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 8000
    (tmp_path / "r.pdf").write_bytes(pdf)
    open("/tmp/report_test.pdf", "wb").write(pdf)
