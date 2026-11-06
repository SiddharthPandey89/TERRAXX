"""Offline tests for source-grounded automatic geology context and score abstention."""
from __future__ import annotations

from app.ingestion.geodata import _parse_mrds_gml, fetch_occurrences, matches_mrds_commodity
from app.prospectivity.auto import run_auto

GML = '''<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"
 xmlns:gml="http://www.opengis.net/gml" xmlns:mrds="https://mrdata.usgs.gov/schema/mrds">
 <gml:featureMember>
  <mrds:mrds gml:id="mrds.123">
   <mrds:dep_id>123</mrds:dep_id>
   <mrds:site_name>Test gold locality</mrds:site_name>
   <mrds:dev_stat>Prospect</mrds:dev_stat>
   <mrds:code_list>AU CU</mrds:code_list>
   <mrds:url>https://mrdata.usgs.gov/mrds/show-mrds.php?dep_id=123</mrds:url>
   <mrds:shape><gml:Point srsName="EPSG:4326"><gml:pos>0.20 0.20</gml:pos></gml:Point></mrds:shape>
  </mrds:mrds>
 </gml:featureMember>
</wfs:FeatureCollection>'''


def _occurrence(longitude: float, latitude: float, record_id: str = "inside") -> dict:
    return {
        "type": "Feature",
        "id": record_id,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "record_id": record_id,
            "site_name": f"{record_id} gold locality",
            "dev_stat": "Prospect",
            "code_list": "AU",
            "record_url": "https://mrdata.usgs.gov/mrds/show-mrds.php?dep_id=1",
        },
    }


def _region_triangle() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [0, 2], [0, 0]]],
    }


def test_mrds_wfs_gml_axis_order_provenance_and_query_contract():
    seen = {}

    def fake_fetcher(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return GML, url + "?request=GetFeature"

    result = fetch_occurrences([0, 0, 1, 1], geometry=_region_triangle(), fetcher=fake_fetcher)

    assert seen["url"] == "https://mrdata.usgs.gov/services/wfs/mrds"
    assert seen["params"]["version"] == "1.1.0"
    assert seen["params"]["typeName"] == "mrds"
    assert "gml" in seen["params"]["outputFormat"].lower()
    assert result["available"] is True
    feature = result["records"][0]
    assert feature["geometry"]["coordinates"] == [0.2, 0.2]
    assert feature["properties"]["record_id"] == "123"
    assert feature["properties"]["code_list"] == "AU CU"
    assert feature["properties"]["in_selected_region"] is True
    assert feature["properties"]["record_url"].startswith("https://mrdata.usgs.gov/")
    assert any("2011" in note for note in result["notes"])


def test_mrds_commodity_codes_do_not_conflate_aluminum_with_bauxite():
    assert matches_mrds_commodity({"code_list": "FE CU"}, "iron ore", ["iron"])
    assert matches_mrds_commodity({"code_list": "AU"}, "gold", ["gold"])
    assert not matches_mrds_commodity({"code_list": "AL"}, "bauxite", ["bauxite"])
    assert matches_mrds_commodity({"primary_commodities": "bauxite ore"}, "bauxite", ["bauxite"])


def test_automatic_context_withholds_scores_and_filters_to_selected_polygon():
    geometry = _region_triangle()
    unit = {
        "map_id": 101,
        "source_id": 9001,
        "name": "Banded iron formation",
        "strat_name": "BIF member",
        "lith": "banded iron formation",
        "best_int_name": "Paleoproterozoic",
        "scale": "1:250000",
    }
    unit_data = {
        "units_per_point": [[unit]],
        "sample_locations": [{
            "longitude": 0.5,
            "latitude": 0.5,
            "unit_count": 1,
            "units": [unit],
        }],
        "points": 1,
        "answered": 1,
        "with_units": 1,
        "coverage": 1.0,
        "coverage_definition": "query-point coverage, not area weighted",
        "source_url": "https://macrostrat.org/api/v2/geologic_units/map",
        "notes": [],
    }
    occurrence_data = {
        "records": [_occurrence(0.2, 0.2, "inside"), _occurrence(1.8, 1.8, "bbox-only")],
        "available": True,
        "search_bbox": [0, 0, 2, 2],
        "source_url": "https://mrdata.usgs.gov/services/wfs/mrds",
        "notes": ["Historical source test fixture."],
    }

    result = run_auto(
        [0, 0, 2, 2],
        geometry,
        ["gold"],
        units_fn=lambda bbox, selected_geometry: unit_data,
        occ_fn=lambda bbox: occurrence_data,
    )

    gold = next(item for item in result["results"] if item["kind"] == "mineral" and item["commodity"] == "gold")
    assert result["automatic_score_status"] == "withheld_unvalidated_method"
    assert result["discovery_claim"] is False
    assert gold["status"] == "insufficient_data"
    assert gold["potential_score"] is None
    assert gold["category"] is None
    assert gold["assessment_status"] == "withheld"
    assert gold["confidence"]["label"] == "Not assessed"
    assert "Insufficient geological evidence for reliable assessment." in gold["assessment_message"]
    assert any("Banded iron formation" in item for item in gold["supporting_evidence"])
    assert len(gold["occurrence_records"]) == 1
    assert gold["occurrence_records"][0]["record_id"] == "inside"
    assert gold["occurrence_records"][0]["inside_region"] is True

    for item in result["results"]:
        assert item["potential_score"] is None
    layers = {layer["id"]: layer for layer in result["map_layers"]}
    assert len(layers["macrostrat-samples"]["geojson"]["features"]) == 1
    assert layers["macrostrat-samples"]["geojson"]["features"][0]["properties"]["source_ids"] == "9001"
    assert len(layers["mrds-occurrences"]["geojson"]["features"]) == 1
    assert layers["mrds-occurrences"]["geojson"]["features"][0]["id"] == "inside"


def test_pdf_report_includes_withheld_status_sources_and_in_region_records():
    from app.api.routes.report import ReportRequest, build_pdf

    prospectivity = {
        "assessment_status": "withheld",
        "assessment_message": "Insufficient geological evidence for reliable assessment.",
        "sources": [{
            "name": "USGS MRDS historical reported occurrences",
            "available": True,
            "url": "https://mrdata.usgs.gov/services/wfs/mrds",
            "data_status": "Historical records; systematic updates ceased in 2011.",
        }],
        "results": [{
            "kind": "mineral",
            "commodity": "gold",
            "status": "insufficient_data",
            "potential_score": None,
            "classification": "Insufficient geological evidence",
            "confidence": {"label": "Not assessed"},
            "assessment_message": "Insufficient geological evidence for reliable assessment.",
            "missing_criteria": ["host_lithology", "structural_setting"],
            "supporting_evidence": ["Macrostrat unit context is descriptive only."],
            "missing_datasets": ["geochemical anomaly measurements"],
            "occurrence_records": [{
                "name": "Test gold locality",
                "status": "Prospect",
                "commodity_codes": "AU",
                "coordinates": [0.2, 0.2],
                "inside_region": True,
            }],
            "limitations": ["The MRDS occurrence record is historical and unverified."],
        }],
        "limitations": ["No validated automatic prospectivity model is implemented."],
        "disclaimer": "Screening only; not a resource estimate.",
    }
    pdf = build_pdf(ReportRequest(
        region={"name": "Test region", "bbox": [0, 0, 2, 2]},
        prospectivity=prospectivity,
    ))
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 3000
