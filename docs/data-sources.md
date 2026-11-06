# Geological Data Sources

This register covers only the sources wired into automatic mineral/petroleum geological context. Providers are queried on demand for the selected region; no source rasters or occurrence inventories are bundled with the application.

| Source | Data used | Coverage and format | License / currency | How the application uses it |
| --- | --- | --- | --- | --- |
| [Macrostrat API v2 `geologic_units/map`](https://macrostrat.org/api/v2/geologic_units/map) | Sampled map-unit identifiers, names, lithology/descriptions, age labels, map scale and original source IDs where returned | Public JSON point lookup; coverage and map detail vary by place and by source map scale. The application samples query points inside the selected polygon; it does not claim a complete polygon map or uniform spatial resolution. | Macrostrat API is documented under CC BY 4.0. The underlying source-map licenses may differ; retain returned map/source IDs and attribution context. | Supplies geological context only. Its response-point coverage is reported as `points_with_units / sampled_points`, not area coverage or evidence of a deposit. |
| [USGS MRDS WFS](https://mrdata.usgs.gov/services/wfs/mrds) and [official MRDS description](https://mrdata.usgs.gov/mrds/) | Reported mineral-locality records, including deposit ID, site name, reported development status, commodity code list, record URL and point geometry | Published WFS 1.1.0 `mrds` feature type. Bounded GetFeature requests return GML 3.1; the implementation parses the point and converts EPSG:4326 axis order (latitude, longitude) into GeoJSON order (longitude, latitude). Database is global but record density and quality are uneven. | Do not infer a single license for every underlying record. USGS describes MRDS as historical/problematic and says systematic updates ceased in 2011. Records are unverified reports, not a current mine/reserve inventory. | Query uses an expanded bbox to find candidate features, then exact selected geometry filtering. The UI and map expose only matched commodity records inside that geometry. Occurrences do not contribute to automatic scores. |

## Commodity-code handling

The implementation uses documented exact MRDS codes where available: `FE` for iron, `CU` variants for copper, `AU` variants for gold, `COA` variants for coal, `LST` variants for limestone, and `MN` variants for manganese. See the [USGS commodity-code reference](https://mrdata.usgs.gov/mrds/commodity-codes.html). `AL` denotes aluminum, not specifically bauxite; an `AL` code alone is therefore not accepted as a bauxite occurrence. Explicit commodity text can supplement an exact code only when the record exposes a commodity-named field.

## Not integrated as evidence

The automatic screen does not currently retrieve fault/fracture/fold/contact geometry, alteration mapping, geochemical anomalies, geophysical data, GSI local datasets, deposit-system training labels, quality-controlled subsurface basin/well data, source-rock TOC or maturity, reservoir/seal properties, traps, migration paths, or charge timing. Lack of a returned record is not evidence that a deposit or petroleum system is absent.

Weather, soil, vegetation, hydrology and terrain are separate environmental/surface-context products in the broader dashboard. They are not passed to the automatic underground-resource assessment as direct proof.

## Operational controls

- Provider requests use bounded timeouts, limited retries and response/feature caps.
- Network failures and no-record responses are distinguished; an unavailable service is not converted into a zero occurrence count.
- Macrostrat sample points preserve returned `map_id`, `source_id`, scale and age/lithology fields for attribution and inspection.
- Automatic score and confidence are withheld because these inputs do not constitute an independently validated commodity-specific predictive model.

## Provider documentation

- Macrostrat data services: <https://macrostrat.org/docs/data-services>
- Macrostrat geologic map methodology and source maps: <https://macrostrat.org/docs/maps/geologic-maps>
- Macrostrat About and data provenance: <https://macrostrat.org/about>
- USGS MRDS overview: <https://mrdata.usgs.gov/mrds/>
- USGS MRDS WFS capabilities: <https://mrdata.usgs.gov/services/wfs/mrds?request=GetCapabilities&service=WFS&version=1.1.0>
- USGS MRDS commodity codes: <https://mrdata.usgs.gov/mrds/commodity-codes.html>
