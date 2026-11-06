# Methodology

## Automatic mineral and petroleum geology context

The automatic regional workflow is a source-grounded context screen, not a commodity-probability model.

1. **Region definition.** The frontend sends the user's WGS84 polygon when one is selected; otherwise it sends the selected WGS84 bounds. The API validates the region and caps its extent. Data-provider sampling and occurrence filtering use that submitted geometry, not a global mean.
2. **Geologic-unit context.** Macrostrat API v2 is queried at a bounded grid of locations. For a polygon, grid points outside it are excluded; if the grid has no interior sample, a representative point within the polygon is used. Returned map ID, source ID, unit name, lithology/description, age labels and scale are retained where present. `points_with_units / sampled_points` is response-point coverage only, never area-weighted coverage. Macrostrat combines maps at different scales; this is not equivalent to a uniform-resolution polygon layer.
3. **Reported occurrences.** USGS MRDS WFS 1.1.0 `GetFeature` requests use the published `mrds` feature type and bounded GML responses. The parser reads point geometry and swaps the WFS EPSG:4326 authority-axis order to GeoJSON longitude/latitude. A modest expanded bbox retrieves candidate records, but only records covered by the actual selected polygon (or the selected bounds when no polygon exists) are returned to the user and placed on the map. Nearby candidates outside the selection may be counted as excluded context, never as in-region evidence.
4. **Commodity-specific context.** Iron ore, copper, gold, bauxite, coal, limestone and manganese use separate transparent lithology text patterns and, when available, distinct documented MRDS commodity codes. These are descriptive term matches for analyst review; no match produces a favourability number. `AL` alone is not used for bauxite because it is an aluminum code.
5. **Abstention.** Automatic scores and confidence are always withheld until relevant datasets and an independently validated commodity-specific predictive model are available. The UI says “Insufficient geological evidence for reliable assessment.” Missing geochemistry/geophysics/structure/alteration and independent validation are exposed rather than replaced by generated values.

MRDS is a historical dataset: USGS says systematic updates ceased in 2011, and record quality varies. An MRDS locality is an unverified report, not proof of a deposit, an active mine, a resource/reserve, or commercial viability. Macrostrat point samples also have variable map scales and should not be interpreted as complete formation coverage.

## Petroleum and natural gas

Petroleum and gas are treated as separate petroleum-system targets, not as another mineral score. The manual evidence-weighted analysis keeps source rock, maturity, reservoir, seal, trap, migration and charge timing as distinct necessary system elements and uses a weighted geometric combination only when its essential evidence and coverage requirements are met. Its weights and thresholds remain heuristic modelling assumptions and the result is an unconfirmed relative favourability index—not a discovery probability or reserve estimate.

The automatic regional screen does not have the subsurface basin, source-rock TOC/maturity, porosity/permeability, seal integrity, trap/fault, migration/timing and validated well/field data required for a reliable petroleum or gas assessment. Macrostrat unit descriptors may provide surface geology context, but they do not establish a working petroleum system. Consequently automatic petroleum and gas scores/confidence are withheld.

## Manual evidence-weighted endpoint

The existing `/prospectivity/analyze` route remains distinct from automatic context retrieval. A caller must provide evidence items and provenance for model-specific criteria. The engine rejects invalid inputs, reports missing/essential criteria and criterion-weight coverage, and returns no score when its configured gates are unmet. Where a model does return a score, it is a heuristic relative favourability index from supplied evidence only, not a probability or resource estimate. User-supplied source labels are not independently verified.

## Environmental and surface context

Climate, soil, terrain, vegetation, hydrology, elevation, and weather analysis remain in their existing environmental/surface modules and reports. They are not treated as direct subsurface mineral or petroleum evidence. Their values and overlays are not mixed into the automatic geology context score because that automatic score is withheld.

## AI and uncertainty

No trained AI prospectivity model or independent validation dataset is shipped or called in this workflow. The application does not synthesize measurements, fabricate geological observations, generate discovery locations, or claim model confidence. The contextual keyword filters are deterministic text matching and should not be described as AI interpretation. Data outages, sparse provider coverage, record age, map-scale differences, missing subsurface evidence and lack of independent validation remain explicit limitations.
