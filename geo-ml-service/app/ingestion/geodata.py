"""Public geology data clients used for automatic, evidence-only prospectivity.

Macrostrat supplies sampled mapped-unit context. USGS MRDS supplies historical,
reported occurrence points. Neither source is treated as a calibrated prediction.
"""
from __future__ import annotations

import math
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .registry import request_json

MACROSTRAT_URL = "https://macrostrat.org/api/v2/geologic_units/map"
MRDS_WFS_URL = "https://mrdata.usgs.gov/services/wfs/mrds"
MRDS_WFS_VERSION = "1.1.0"
MAX_MRDS_FEATURES = 1000
MAX_MRDS_RESPONSE_BYTES = 12 * 1024 * 1024
Fetcher = Callable[..., tuple[Any, str]]

# Exact official MRDS commodity-code groups. AL is deliberately not mapped to
# bauxite: USGS defines AL as aluminum and it is not specific to bauxite ore.
MRDS_COMMODITY_CODES: dict[str, frozenset[str]] = {
    "iron ore": frozenset({"FE"}),
    "copper": frozenset({"CU", "CU_O", "CU_S"}),
    "gold": frozenset({"AU", "AU_R"}),
    "bauxite": frozenset(),
    "coal": frozenset({"COA", "COA_A", "COA_B", "COA_L", "COA_S"}),
    "limestone": frozenset({"LST", "LST_C", "LST_D", "LST_P"}),
    "manganese": frozenset({"MN", "MN_F"}),
}


def grid_points(bbox: list[float], n: int = 4, geometry: dict | None = None) -> list[tuple[float, float]]:
    """Return (longitude, latitude) cell-centre samples, constrained to geometry."""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 16:
        raise ValueError("Sampling grid size must be an integer from 1 to 16.")
    west, south, east, north = bbox
    points = [
        (west + (i + 0.5) * (east - west) / n,
         south + (j + 0.5) * (north - south) / n)
        for j in range(n) for i in range(n)
    ]
    if geometry is None:
        return points

    from shapely.geometry import Point, shape

    polygon = shape(geometry)
    if polygon.is_empty or not polygon.is_valid:
        return []
    inside = [point for point in points if polygon.covers(Point(point))]
    if inside:
        return inside
    representative = polygon.representative_point()
    return [(representative.x, representative.y)] if not representative.is_empty else []


def _macrostrat_sample(point: tuple[float, float], units: list[dict[str, Any]] | None) -> dict[str, Any]:
    selected = []
    for unit in (units or [])[:8]:
        selected.append({
            key: unit[key]
            for key in (
                "map_id", "source_id", "name", "strat_name", "lith", "descrip",
                "best_int_name", "t_int_name", "b_int_name", "scale", "license",
            )
            if unit.get(key) is not None
        })
    return {
        "longitude": round(point[0], 6),
        "latitude": round(point[1], 6),
        "unit_count": len(units or []),
        "units": selected,
    }


def fetch_units(
    bbox: list[float],
    geometry: dict | None = None,
    n: int = 4,
    fetcher: Fetcher = request_json,
) -> dict[str, Any]:
    """Sample Macrostrat map units; coverage is query-point response, not area coverage."""
    base = os.getenv("MACROSTRAT_API_URL", MACROSTRAT_URL).strip() or MACROSTRAT_URL
    points = grid_points(bbox, n, geometry)

    def one(point: tuple[float, float]) -> list[dict[str, Any]] | None:
        try:
            payload, _ = fetcher(
                base,
                provider="macrostrat",
                timeout=20.0,
                retries=1,
                params={
                    "lat": round(point[1], 5),
                    "lng": round(point[0], 5),
                    "scale": "medium",
                    "response": "long",
                    "format": "json",
                },
            )
        except Exception:  # noqa: BLE001 - one failed cell must not fail the region
            return None
        data = ((payload or {}).get("success") or {}).get("data") if isinstance(payload, dict) else None
        return [unit for unit in data if isinstance(unit, dict)] if isinstance(data, list) else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, points))

    answered = [result for result in results if result is not None]
    with_units = [result for result in answered if result]
    notes: list[str] = []
    if not answered:
        notes.append("Macrostrat geologic-unit service was unreachable; no lithology evidence is available.")
    elif not with_units:
        notes.append("Macrostrat returned no mapped geologic units for the sampled points.")

    samples = [_macrostrat_sample(point, result) for point, result in zip(points, results)]
    return {
        "units_per_point": results,
        "sample_locations": samples,
        "points": len(points),
        "answered": len(answered),
        "with_units": len(with_units),
        "coverage": len(with_units) / len(points) if points else 0.0,
        "coverage_definition": "fraction of sampled query points with at least one returned map unit; not area-weighted",
        "source": "Macrostrat geologic_units/map",
        "source_url": base,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }


def request_mrds_gml(
    url: str,
    *,
    provider: str,
    params: dict[str, Any],
    timeout: float = 20.0,
    retries: int = 1,
) -> tuple[str, str]:
    """Fetch bounded WFS GML with short timeouts and limited transient retries."""
    if timeout <= 0 or retries < 0:
        raise ValueError("MRDS timeout must be positive and retries non-negative.")
    query = urlencode({key: value for key, value in params.items() if value is not None})
    request_url = f"{url}?{query}" if query else url
    headers = {
        "Accept": "text/xml; subtype=gml/3.1.1, application/xml",
        "User-Agent": "Earth-GeoIntelligence/0.1 public-data client",
    }
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        request = Request(request_url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_MRDS_RESPONSE_BYTES + 1)
            if len(raw) > MAX_MRDS_RESPONSE_BYTES:
                raise ValueError("USGS MRDS response exceeded the configured size limit.")
            return raw.decode("utf-8", errors="strict"), request_url
        except HTTPError as exc:
            body = exc.read(512).decode("utf-8", errors="replace").strip()
            if (exc.code == 429 or exc.code >= 500) and attempt < retries:
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    delay = min(max(float(retry_after), 0.0), 2.0)
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        delay = min(max((retry_at - datetime.now(retry_at.tzinfo)).total_seconds(), 0.0), 2.0)
                    except (TypeError, ValueError, OverflowError):
                        delay = 0.5
                time.sleep(delay or 0.5)
                continue
            raise RuntimeError(f"{provider} returned HTTP {exc.code}: {body[:160] or 'request failed'}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5)
                continue
            raise RuntimeError(f"{provider} request failed after bounded retries.") from exc

    raise RuntimeError(f"{provider} request failed.") from last_error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _parse_point(feature: ET.Element) -> list[float] | None:
    point = next((element for element in feature.iter() if _local_name(element.tag) == "Point"), None)
    if point is None:
        return None
    pos = next((element for element in point.iter() if _local_name(element.tag) in {"pos", "coordinates"}), None)
    if pos is None or not pos.text:
        return None
    raw = pos.text.strip().replace(",", " ").split()
    try:
        first, second = float(raw[0]), float(raw[1])
    except (ValueError, IndexError):
        return None

    srs_name = (pos.get("srsName") or point.get("srsName") or "EPSG:4326").upper()
    if "CRS84" in srs_name or _local_name(pos.tag) == "coordinates":
        longitude, latitude = first, second
    else:
        # USGS WFS 1.1 EPSG:4326 GML positions use authority axis order: lat, lon.
        latitude, longitude = first, second
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return [longitude, latitude]


def _parse_mrds_gml(payload: Any) -> list[dict[str, Any]]:
    """Convert the published MRDS WFS GML feature collection to small GeoJSON records."""
    if isinstance(payload, dict):
        # Retain compatibility with fixture/injected JSON responses used by callers.
        features = payload.get("features")
        return [feature for feature in features if isinstance(feature, dict)] if isinstance(features, list) else []
    if isinstance(payload, bytes):
        if len(payload) > MAX_MRDS_RESPONSE_BYTES:
            raise ValueError("USGS MRDS response exceeded the configured size limit.")
        payload = payload.decode("utf-8", errors="strict")
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_MRDS_RESPONSE_BYTES:
        raise ValueError("USGS MRDS returned an invalid or oversized GML response.")

    root = ET.fromstring(payload)
    root_name = _local_name(root.tag).lower()
    if "exception" in root_name or root_name == "serviceexceptionreport":
        message = " ".join((node.text or "").strip() for node in root.iter() if node.text and node.text.strip())
        raise ValueError(f"USGS MRDS WFS exception: {message[:180] or 'request rejected'}")

    records: list[dict[str, Any]] = []
    for element in root.iter():
        if _local_name(element.tag).lower() != "mrds":
            continue
        properties: dict[str, Any] = {}
        for child in list(element):
            key = _local_name(child.tag)
            if key in {"boundedBy", "geometry"}:
                continue
            value = " ".join(part.strip() for part in child.itertext() if part and part.strip())
            if value:
                properties[key] = value[:1200]
        coordinates = _parse_point(element)
        if coordinates is None:
            continue
        feature_id = element.get("{http://www.opengis.net/gml}id") or properties.get("dep_id")
        record_id = str(properties.get("dep_id") or feature_id or "")[:80]
        record_url = str(properties.get("url") or "")
        if not record_url.startswith("https://mrdata.usgs.gov/"):
            record_url = ""
        properties["record_id"] = record_id
        properties["record_url"] = record_url
        properties["code_list"] = str(properties.get("code_list") or "").upper().strip()
        records.append({
            "type": "Feature",
            "id": record_id or None,
            "geometry": {"type": "Point", "coordinates": coordinates},
            "properties": properties,
        })
    return records


def _inside_geometry(feature: dict[str, Any], geometry: dict | None) -> bool:
    if geometry is None:
        return False
    coordinates = (feature.get("geometry") or {}).get("coordinates")
    try:
        from shapely.geometry import Point, shape
        return bool(shape(geometry).covers(Point(float(coordinates[0]), float(coordinates[1]))))
    except (TypeError, ValueError, IndexError, KeyError):
        return False


def _inside_bbox(feature: dict[str, Any], bbox: list[float]) -> bool:
    coordinates = (feature.get("geometry") or {}).get("coordinates")
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        return bbox[0] <= longitude <= bbox[2] and bbox[1] <= latitude <= bbox[3]
    except (TypeError, ValueError, IndexError):
        return False


def fetch_occurrences(
    bbox: list[float],
    geometry: dict | None = None,
    buffer_deg: float = 0.5,
    max_features: int = MAX_MRDS_FEATURES,
    fetcher: Fetcher = request_mrds_gml,
) -> dict[str, Any]:
    """Fetch historical MRDS points from its published GML WFS, then flag exact region matches."""
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("A valid west, south, east, north bounding box is required.")
    if not math.isfinite(buffer_deg) or not 0 <= buffer_deg <= 2:
        raise ValueError("Occurrence search buffer must be between 0 and 2 degrees.")
    max_features = max(1, min(int(max_features), MAX_MRDS_FEATURES))
    west, south, east, north = bbox
    search_bbox = [
        max(-180.0, west - buffer_deg), max(-90.0, south - buffer_deg),
        min(180.0, east + buffer_deg), min(90.0, north + buffer_deg),
    ]
    url = os.getenv("USGS_MRDS_WFS_URL", MRDS_WFS_URL).strip() or MRDS_WFS_URL

    try:
        payload, request_url = fetcher(
            url,
            provider="usgs-mrds",
            timeout=20.0,
            retries=1,
            params={
                "service": "WFS",
                "version": MRDS_WFS_VERSION,
                "request": "GetFeature",
                "typeName": "mrds",
                "outputFormat": "text/xml; subtype=gml/3.1.1",
                "maxFeatures": max_features,
                # This server accepts W,S,E,N for its WFS 1.1 bbox filter. GML positions
                # still use the EPSG:4326 authority axis order and are swapped on parse.
                "bbox": ",".join(f"{value:.5f}" for value in search_bbox),
            },
        )
        records = _parse_mrds_gml(payload)
        for feature in records:
            inside = _inside_geometry(feature, geometry) if geometry else _inside_bbox(feature, bbox)
            feature.setdefault("properties", {})["in_selected_region"] = inside
        notes = [
            "MRDS records are historical and unverified occurrence reports; USGS says systematic updates ceased in 2011.",
            "Occurrence records are contextual evidence only and do not contribute to an automatic prospectivity score.",
        ]
        if len(records) >= max_features:
            notes.append(f"The WFS response reached the {max_features}-record request cap; additional records may exist.")
        if not records:
            notes.append("USGS MRDS returned no point records in the expanded search extent.")
        return {
            "records": records,
            "available": True,
            "search_bbox": search_bbox,
            "source": "USGS MRDS",
            "source_url": request_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
    except Exception as exc:  # noqa: BLE001 - provider failures remain explicit, not false zeroes
        return {
            "records": [],
            "available": False,
            "search_bbox": search_bbox,
            "source": "USGS MRDS",
            "source_url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "notes": [f"USGS MRDS occurrence service unavailable ({str(exc)[:160]})."],
        }


def matches_mrds_commodity(properties: dict[str, Any], commodity: str, words: list[str] | None = None) -> bool:
    """Match exact USGS commodity codes, then explicit commodity text fields."""
    commodity = commodity.strip().lower()
    codes = MRDS_COMMODITY_CODES.get(commodity, frozenset())
    raw_codes = str(properties.get("code_list") or "").upper().replace(",", " ").replace(";", " ").split()
    if codes and any(code in codes for code in raw_codes):
        return True
    text = " ".join(
        str(value)
        for key, value in properties.items()
        if any(token in str(key).lower() for token in ("commod", "ore", "gangue")) and value
    ).lower()
    return any(word.lower() in text for word in (words or []))
