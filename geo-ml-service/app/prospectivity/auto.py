"""Automatic geology context for a selected region, with a deliberate score gate.

Macrostrat map-unit samples and historical USGS MRDS occurrence reports can help
users inspect geological context. These inputs are not sufficient for a validated
commodity-specific prospectivity model, so this module never derives an automatic
potential score or confidence rating from keyword matches or known occurrences.
The evidence-weighted manual API remains available in ``prospectivity.engine``.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ..ingestion.geodata import fetch_occurrences, fetch_units, matches_mrds_commodity
from .engine import ProspectivityTarget, TargetRequest, analyze_prospectivity

UNIT_SRC = "Macrostrat geologic_units/map (sampled grid)"
OCC_SRC = "USGS MRDS historical reported occurrences"
INSUFFICIENT_MESSAGE = "Insufficient geological evidence for reliable assessment."
WITHHELD_MESSAGE = (
    "Automatic scoring is withheld: the integrated map-unit and historical occurrence data "
    "have not been validated as a commodity-specific predictive model."
)

# Separate, transparent lithology-context terms for each target. These patterns
# only surface map-unit text for review; they do not produce favourability values.
MINERALS: dict[str, dict[str, Any]] = {
    "iron ore": {"words": ["iron"], "rules": [
        ("banded iron formation, itabirite, ironstone, hematite, or magnetite", r"banded iron|iron formation|itabirite|ironstone|hematite|magnetite"),
        ("lateritic or ferruginous unit", r"laterit|ferrugin"),
        ("greenstone, metavolcanic rock, or amphibolite", r"greenstone|metavolcan|amphibolite"),
        ("quartzite, phyllite, schist, metasediment, or chert", r"quartzite|phyllite|schist|metasediment|chert"),
    ]},
    "copper": {"words": ["copper"], "rules": [
        ("porphyry, skarn, or volcanogenic setting term", r"porphyr|skarn|volcanogenic"),
        ("intermediate to felsic igneous or volcanic unit", r"andesit|diorite|granodiorite|dacit|rhyolit|volcanic"),
        ("mafic or greenstone unit", r"basalt|greenstone|amphibolite|mafic"),
        ("red-bed or clastic sedimentary unit", r"red.?bed|arkose|sandstone|shale"),
        ("metamorphic or metavolcanic unit", r"schist|phyllite|gneiss|metavolcan"),
    ]},
    "gold": {"words": ["gold"], "rules": [
        ("greenstone, quartz-vein, or auriferous unit", r"greenstone|quartz vein|auriferous"),
        ("banded iron formation or conglomerate", r"banded iron|conglomerate"),
        ("metasedimentary or turbidite unit", r"schist|phyllite|slate|metasediment|metavolcan|turbidite"),
        ("volcanic or felsic intrusive unit", r"volcanic|andesit|rhyolit|granite|granodiorite|diorite"),
    ]},
    "bauxite": {"words": ["bauxite"], "rules": [
        ("bauxite-bearing unit term", r"bauxit"),
        ("lateritic unit term", r"laterit"),
        ("basaltic or trap-rock unit", r"basalt|trap\b|deccan"),
        ("aluminous crystalline unit term", r"khondalite|gneiss|granite|syenite|nepheline|alkalin"),
        ("carbonate or karst unit", r"limestone|dolo|karst"),
    ]},
    "coal": {"words": ["coal", "lignite", "anthracite"], "rules": [
        ("coal, lignite, or anthracite term", r"coal|lignite|anthracite"),
        ("carbonaceous or Gondwana unit term", r"carbonaceous|coaly|gondwana"),
        ("shale, mudstone, siltstone, or sandstone", r"shale|mudstone|siltstone|sandstone"),
    ]},
    "limestone": {"words": ["limestone", "dolomite", "cement", "carbonate"], "rules": [
        ("limestone, dolomite, marble, chalk, or carbonate unit", r"limestone|dolomit|marble|chalk|calcarenite|carbonate"),
        ("marl, calcareous, or calc-silicate unit", r"marl|calcareous|calc.?silicate"),
    ]},
    "manganese": {"words": ["manganese"], "rules": [
        ("manganese, gondite, or psilomelane term", r"mangan|gondite|psilomelane"),
        ("banded iron or lateritic unit", r"banded iron|laterit"),
        ("metasedimentary unit term", r"phyllite|quartzite|chert|shale|metasediment"),
        ("volcanic or greenstone unit", r"volcan|greenstone"),
    ]},
}

MINERAL_MISSING_DATASETS = [
    "fault and fracture maps at a comparable map scale",
    "geochemical anomaly measurements",
    "geophysical indicators and alteration mapping",
    "deposit-system-specific training labels and independent spatial validation",
]
HYDROCARBON_MISSING_DATASETS = [
    "sedimentary basin boundaries and stratigraphic subsurface framework",
    "source-rock richness and thermal-maturity measurements such as TOC and vitrinite reflectance",
    "reservoir porosity, permeability, thickness, and seal-integrity measurements",
    "trap, fault, migration-pathway, and charge-timing evidence",
    "quality-controlled well and field records for validation",
]


def _unit_text(unit: dict[str, Any]) -> str:
    return " ".join(str(unit.get(key) or "") for key in ("lith", "name", "strat_name", "descrip", "comments")).lower()


def _unique_units(units_per_point: list[Any]) -> list[dict[str, Any]]:
    seen: dict[Any, dict[str, Any]] = {}
    for units in units_per_point:
        for unit in units or []:
            if not isinstance(unit, dict):
                continue
            key = unit.get("map_id") or unit.get("name") or id(unit)
            seen.setdefault(key, unit)
    return list(seen.values())


def _unit_label(unit: dict[str, Any]) -> str:
    name = str(unit.get("name") or unit.get("strat_name") or "unnamed mapped unit")[:100]
    lithology = str(unit.get("lith") or "").strip()[:60]
    age = str(unit.get("best_int_name") or unit.get("t_int_name") or "").strip()[:50]
    parts = [name]
    if lithology:
        parts.append(lithology)
    if age:
        parts.append(f"age label: {age}")
    return " · ".join(parts)


def _unit_context(commodity: str, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    context = []
    for unit in units:
        text = _unit_text(unit)
        if not text:
            continue
        matches = [label for label, pattern in MINERALS[commodity]["rules"] if re.search(pattern, text)]
        if not matches:
            continue
        context.append({
            "name": str(unit.get("name") or unit.get("strat_name") or "unnamed mapped unit")[:120],
            "lithology": str(unit.get("lith") or "")[:100],
            "geologic_age": str(unit.get("best_int_name") or unit.get("t_int_name") or "")[:80],
            "map_id": unit.get("map_id"),
            "source_id": unit.get("source_id"),
            "scale": unit.get("scale"),
            "matched_context": matches[:3],
        })
        if len(context) >= 8:
            break
    return context


def _in_region(feature: dict[str, Any], bbox: list[float], geometry: dict | None) -> bool:
    coordinates = (feature.get("geometry") or {}).get("coordinates")
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError, IndexError):
        return False
    if geometry is None:
        return bbox[0] <= longitude <= bbox[2] and bbox[1] <= latitude <= bbox[3]
    try:
        from shapely.geometry import Point, shape
        return bool(shape(geometry).covers(Point(longitude, latitude)))
    except (TypeError, ValueError, KeyError):
        return False


def _commodity_records(records: list[dict[str, Any]], commodity: str) -> list[dict[str, Any]]:
    matches = []
    words = MINERALS[commodity]["words"]
    for feature in records:
        properties = feature.get("properties") or {}
        if matches_mrds_commodity(properties, commodity, words):
            matches.append(feature)
    return matches


def _occurrence_records(
    commodity: str,
    occurrence_data: dict[str, Any],
    bbox: list[float],
    geometry: dict | None,
) -> tuple[list[dict[str, Any]], int, int]:
    matched = _commodity_records(occurrence_data.get("records") or [], commodity)
    inside = [feature for feature in matched if _in_region(feature, bbox, geometry)]
    search_bbox = occurrence_data.get("search_bbox") or bbox
    nearby = [
        feature for feature in matched
        if feature not in inside and _in_region(feature, search_bbox, None)
    ]
    rows = []
    for feature in inside:
        props = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        rows.append({
            "name": str(props.get("site_name") or props.get("dep_name") or "Unnamed MRDS record")[:200],
            "status": str(props.get("dev_stat") or "Status not supplied")[:120],
            "source": OCC_SRC,
            "verified": False,
            "record_id": str(props.get("record_id") or props.get("dep_id") or "")[:80],
            "record_url": str(props.get("record_url") or "")[:300],
            "commodity_codes": str(props.get("code_list") or "")[:120],
            "coordinates": [coordinates[0], coordinates[1]] if len(coordinates) >= 2 else None,
            "inside_region": True,
        })
        if len(rows) >= 12:
            break
    return rows, len(inside), len(nearby)


def _build_map_layers(unit_data: dict[str, Any], occurrence_data: dict[str, Any], names: list[str], bbox: list[float], geometry: dict | None) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    sample_features = []
    for index, sample in enumerate(unit_data.get("sample_locations") or [], start=1):
        try:
            longitude, latitude = float(sample["longitude"]), float(sample["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        units = sample.get("units") or []
        names_text = "; ".join(str(unit.get("name") or unit.get("strat_name") or "")[:90] for unit in units[:4] if unit.get("name") or unit.get("strat_name"))
        age_text = "; ".join(dict.fromkeys(str(unit.get("best_int_name") or unit.get("t_int_name") or "") for unit in units if unit.get("best_int_name") or unit.get("t_int_name")))
        sample_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": {
                "label": f"Macrostrat sample {index} · {len(units)} mapped unit(s)",
                "unit_names": names_text[:320],
                "age_labels": age_text[:160],
                "map_ids": ", ".join(str(unit.get("map_id")) for unit in units if unit.get("map_id"))[:160],
                "source_ids": ", ".join(str(unit.get("source_id")) for unit in units if unit.get("source_id"))[:160],
                "source": UNIT_SRC,
            },
        })
    if sample_features:
        layers.append({
            "id": "macrostrat-samples",
            "label": "Macrostrat query points",
            "type": "geojson",
            "source": UNIT_SRC,
            "note": "Sample locations only; not full mapped-unit polygons or area coverage.",
            "color": "#5ee1ff",
            "legend": [{"label": "Map-unit query location", "color": "#5ee1ff"}],
            "geojson": {"type": "FeatureCollection", "features": sample_features[:256]},
        })

    occurrence_features = []
    seen_ids: set[str] = set()
    if occurrence_data.get("available"):
        for commodity in names:
            for feature in _commodity_records(occurrence_data.get("records") or [], commodity):
                if not _in_region(feature, bbox, geometry):
                    continue
                props = feature.get("properties") or {}
                record_id = str(props.get("record_id") or props.get("dep_id") or "")
                dedupe_key = record_id or repr((feature.get("geometry") or {}).get("coordinates"))
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                coords = (feature.get("geometry") or {}).get("coordinates")
                if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                    continue
                try:
                    longitude, latitude = float(coords[0]), float(coords[1])
                except (TypeError, ValueError):
                    continue
                occurrence_features.append({
                    "type": "Feature",
                    "id": record_id or None,
                    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                    "properties": {
                        "label": f"Reported {commodity} record · {props.get('site_name') or 'Unnamed'}",
                        "commodity": commodity,
                        "record_id": record_id[:80],
                        "record_url": str(props.get("record_url") or "")[:300],
                        "dev_stat": str(props.get("dev_stat") or "")[:120],
                        "code_list": str(props.get("code_list") or "")[:120],
                        "source": OCC_SRC,
                        "verified": False,
                    },
                })
                if len(occurrence_features) >= 250:
                    break
            if len(occurrence_features) >= 250:
                break
    if occurrence_features:
        layers.append({
            "id": "mrds-occurrences",
            "label": "Reported MRDS occurrences",
            "type": "geojson",
            "source": OCC_SRC,
            "note": "Historical, unverified occurrence points inside the selected geometry; context only, not a prediction.",
            "color": "#ffc857",
            "legend": [{"label": "Reported occurrence · unverified", "color": "#ffc857"}],
            "geojson": {"type": "FeatureCollection", "features": occurrence_features},
        })
    return layers


def run_auto(
    bbox: list[float],
    geometry: dict | None = None,
    minerals: list[str] | None = None,
    units_fn: Callable[..., dict] = fetch_units,
    occ_fn: Callable[..., dict] = fetch_occurrences,
) -> dict[str, Any]:
    """Retrieve geological context and withhold unvalidated automatic scores."""
    names = [name for name in (minerals or list(MINERALS)) if name in MINERALS]
    if not names:
        names = list(MINERALS)
    unit_data = units_fn(bbox, geometry)
    occurrence_data = occ_fn(bbox, geometry=geometry) if occ_fn is fetch_occurrences else occ_fn(bbox)
    units = _unique_units(unit_data.get("units_per_point") or [])
    coverage = round(float(unit_data.get("coverage") or 0.0), 3)
    limits = list(unit_data.get("notes") or []) + list(occurrence_data.get("notes") or [])
    limits.extend([
        "Macrostrat is a multiscale compilation; this request samples map units at query points and does not represent area-weighted coverage.",
        "MRDS contains historical, unverified occurrence reports; USGS says systematic updates ceased in 2011.",
        "Weather, vegetation, soil, and terrain are not treated as direct evidence of underground mineral deposits.",
        "The integrated sources do not provide the structural, alteration, geochemical, geophysical, or subsurface evidence needed for validated automatic prospectivity scores.",
        "No calibrated AI model or independently validated spatial prediction model is implemented for this automatic screen; numeric scores and confidence are withheld.",
    ])

    requests = [
        TargetRequest(target=ProspectivityTarget("mineral", commodity), evidence=[])
        for commodity in names
    ]
    requests.extend([
        TargetRequest(target=ProspectivityTarget("petroleum"), evidence=[]),
        TargetRequest(target=ProspectivityTarget("gas"), evidence=[]),
    ])
    report = analyze_prospectivity(requests).to_dict()

    occurrences_by_target: dict[str, list[dict[str, Any]]] = {}
    counts_by_target: dict[str, tuple[int, int]] = {}
    context_by_target: dict[str, list[dict[str, Any]]] = {}
    for commodity in names:
        context = _unit_context(commodity, units)
        rows, inside_count, nearby_count = _occurrence_records(commodity, occurrence_data, bbox, geometry)
        context_by_target[commodity] = context
        occurrences_by_target[commodity] = rows
        counts_by_target[commodity] = (inside_count, nearby_count)

    results: list[dict[str, Any]] = []
    for result in report["results"]:
        kind = result["kind"]
        commodity = result.get("commodity")
        key = commodity if kind == "mineral" else kind
        supporting: list[str] = []
        missing_datasets = MINERAL_MISSING_DATASETS if kind == "mineral" else HYDROCARBON_MISSING_DATASETS
        occurrence_rows = occurrences_by_target.get(commodity, []) if kind == "mineral" else []

        if kind == "mineral":
            for unit in context_by_target.get(commodity, []):
                supporting.append(
                    f"Macrostrat mapped unit: {unit['name']}"
                    + (f" ({unit['lithology']})" if unit.get("lithology") else "")
                    + (f"; age label: {unit['geologic_age']}" if unit.get("geologic_age") else "")
                    + ". A target-specific lithology term matched; this is descriptive context, not a favourability score."
                )
            inside_count, nearby_count = counts_by_target.get(commodity, (0, 0))
            if inside_count:
                supporting.append(
                    f"{inside_count} historical MRDS {commodity} report(s) fall inside the selected geometry; records are unverified and are not used to calculate potential."
                )
            if nearby_count:
                supporting.append(
                    f"{nearby_count} matching historical MRDS {commodity} report(s) fall outside the selected geometry and were excluded from in-region evidence and map layers."
                )
            if not context and not inside_count and not nearby_count:
                supporting.append("No target-specific lithology term or matched MRDS occurrence was returned; this does not establish absence of the commodity.")
        else:
            if units:
                sedimentary = sum(
                    1 for unit in units
                    if re.search(r"sandstone|shale|mudstone|limestone|dolomit|siltstone|conglomerate|evaporit|marl|claystone|coal|sediment|alluvi|clastic", _unit_text(unit))
                )
                supporting.append(
                    f"Macrostrat returned {len(units)} distinct sampled map unit(s); {sedimentary} unit(s) contain a sedimentary descriptor. This does not establish basin presence, source-rock maturity, reservoir quality, seal integrity, traps, migration, or charge timing."
                )
            else:
                supporting.append("No mapped geological units were returned for interpretation.")

        result.update({
            "status": "insufficient_data",
            "potential_score": None,
            "category": None,
            "classification": "Insufficient geological evidence",
            "confidence": {"label": "Not assessed", "score": None, "reason": WITHHELD_MESSAGE},
            "assessment_status": "withheld",
            "assessment_method": "automatic geological context only; no calibrated predictive model",
            "assessment_message": INSUFFICIENT_MESSAGE,
            "reasons": list(dict.fromkeys([INSUFFICIENT_MESSAGE, WITHHELD_MESSAGE, *result.get("reasons", [])])),
            "supporting_evidence": supporting,
            "occurrence_records": occurrence_rows,
            "geological_context": context_by_target.get(commodity, []) if kind == "mineral" else [],
            "missing_datasets": list(missing_datasets),
            "limitations": list(dict.fromkeys(limits)),
        })
        results.append(result)

    sources = [
        {
            "name": UNIT_SRC,
            "available": int(unit_data.get("answered") or 0) > 0,
            "url": unit_data.get("source_url") or "https://macrostrat.org/api/v2/geologic_units/map",
            "license": "Macrostrat API data are provided under CC BY 4.0; original map-source terms may vary.",
            "retrieved_at": unit_data.get("retrieved_at"),
        },
        {
            "name": OCC_SRC,
            "available": bool(occurrence_data.get("available")),
            "url": occurrence_data.get("source_url") or "https://mrdata.usgs.gov/services/wfs/mrds",
            "data_status": "Historical records; systematic updates ceased in 2011.",
            "retrieved_at": occurrence_data.get("retrieved_at"),
        },
    ]
    map_layers = _build_map_layers(unit_data, occurrence_data, names, bbox, geometry)
    return {
        "success": True,
        "bbox": bbox,
        "results": results,
        "assessment_status": "withheld",
        "assessment_message": INSUFFICIENT_MESSAGE,
        "automatic_score_status": "withheld_unvalidated_method",
        "sampling": {
            "points": int(unit_data.get("points") or 0),
            "points_with_units": int(unit_data.get("with_units") or 0),
            "distinct_units": len(units),
            "coverage": coverage,
            "coverage_definition": unit_data.get("coverage_definition") or "fraction of sampled query points with at least one returned map unit; not area-weighted",
        },
        "sources": sources,
        "map_layers": map_layers,
        "limitations": list(dict.fromkeys(limits)),
        "resource_status": report["resource_status"],
        "disclaimer": report["disclaimer"],
        "discovery_claim": False,
    }
