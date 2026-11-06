import { useCallback, useEffect, useRef, useState } from 'react';
import { downloadReportPdf, requestModule, requestProspectivity } from '../../services/analysisService.js';
import { AspectRose, ClimateChart, HBars, Ring, Sparkline, StackBar } from '../charts/MiniCharts.jsx';

const BASE = ['climate', 'terrain', 'soil', 'vegetation', 'water'];
const LABELS = { climate: 'Climate', terrain: 'Terrain', soil: 'Soil', vegetation: 'Vegetation & land cover', water: 'Water', suitability: 'Suitability', resources: 'Mineral & petroleum' };
const n = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : '—');
const sign = (v) => (v > 0 ? `+${v}` : `${v}`);

function Card({ title, icon, source, children, wide }) {
  return (
    <article className={`gi-card${wide ? ' gi-card--wide' : ''}`}>
      <header><span className="gi-card__icon" aria-hidden="true">{icon}</span><h3>{title}</h3></header>
      {children}
      {source && <footer>{source}</footer>}
    </article>
  );
}
const Skeleton = ({ title }) => <article className="gi-card gi-card--loading" aria-busy="true"><header><h3>{title}</h3></header><i /><i /><i /></article>;
const Kpi = ({ label, value, unit, hint }) => <div className="gi-kpi"><span>{label}</span><strong>{value}<small>{unit}</small></strong>{hint && <em>{hint}</em>}</div>;
const Chip = ({ children, tone = 'neutral' }) => <span className={`gi-chip gi-chip--${tone}`}>{children}</span>;
const toneFor = (c) => (c === 'high' || c === 'High' ? 'good' : c === 'moderate' || c === 'Moderate' ? 'mid' : 'neutral');

function ClimateCard({ d }) {
  const t = d.trends?.temperature_c; const r = d.trends?.rainfall_mm;
  return (
    <Card title="Climate" icon="◐" source={`${d.source}. ${d.period}.`} wide>
      <div className="gi-kpis">
        <Kpi label="Mean temperature" value={n(d.mean_temperature_c)} unit=" °C" />
        <Kpi label="Annual rainfall" value={n(d.annual_rainfall_mm, 0)} unit=" mm" />
        <Kpi label="Humidity" value={n(d.mean_humidity_pct, 0)} unit=" %" />
        {d.wind && <Kpi label="Wind" value={n(d.wind.mean_daily_max_kmh, 0)} unit=" km/h" hint={`mostly from ${d.wind.prevailing_direction}`} />}
        {d.aridity_class && <Kpi label="Aridity" value={n(d.aridity_index, 2)} unit="" hint={d.aridity_class} />}
      </div>
      <div className="gi-split">
        <div><h4>Seasonal pattern <small>bars: rain · line: temperature</small></h4><ClimateChart monthly={d.monthly} />
          <p className="gi-note">Hottest {d.seasons.hottest_month}, coolest {d.seasons.coolest_month}; wettest quarter {d.seasons.wettest_quarter}{d.seasons.wettest_quarter_share_pct ? ` (${d.seasons.wettest_quarter_share_pct}% of rain)` : ''}.</p></div>
        <div><h4>Annual mean temperature</h4><Sparkline points={d.yearly.map((y) => ({ year: y.year, value: y.mean_temperature_c }))} unit=" °C" />
          <div className="gi-trends">
            {t && <Chip tone={t.significant ? 'mid' : 'neutral'}>Temp {sign(t.per_decade)} °C/decade{t.significant ? '' : ' · not significant'}</Chip>}
            {r && <Chip tone={r.significant ? 'mid' : 'neutral'}>Rain {sign(r.per_decade)} mm/decade{r.significant ? '' : ' · not significant'}</Chip>}
          </div>
          <p className="gi-note">Trends are linear fits over {d.years_used} complete years; short records are weak evidence of climate change.</p></div>
      </div>
    </Card>
  );
}

function TerrainCard({ d }) {
  return (
    <Card title="Terrain" icon="△" source={`${d.source}. ${d.grid}.`}>
      <div className="gi-kpis">
        <Kpi label="Elevation" value={`${n(d.elevation_m.min, 0)}–${n(d.elevation_m.max, 0)}`} unit=" m" hint={`mean ${n(d.elevation_m.mean, 0)} m`} />
        <Kpi label="Relief" value={n(d.relief_m, 0)} unit=" m" hint={d.terrain_class} />
        <Kpi label="Mean slope" value={n(d.mean_slope_deg)} unit="°" hint={d.slope_class} />
      </div>
      <div className="gi-split gi-split--tight">
        <HBars items={Object.entries(d.slope_distribution_pct).map(([label, value]) => ({ label, value }))} max={100} unit="%" />
        <AspectRose shares={d.aspect_share_pct} />
      </div>
    </Card>
  );
}

function VegetationCard({ d }) {
  const v = d.vegetation; const lc = d.land_cover; const ch = d.change;
  return (
    <Card title="Vegetation & land cover" icon="❋" source={`${d.source}. Scene ${d.scene.id}, ${d.scene.date}, cloud ${n(d.scene.cloud_cover_pct, 0)}%, ${n(d.valid_pixel_pct, 0)}% valid pixels.`} wide>
      <div className="gi-kpis">
        <Kpi label="Mean NDVI" value={n(v.mean_ndvi, 2)} unit="" hint={`p10–p90 ${v.p10_p90[0]} to ${v.p10_p90[1]}`} />
        {lc && <Kpi label="Forest cover" value={n(lc.forest_cover_pct, 0)} unit=" %" hint="ESA WorldCover 2021" />}
        {lc && <Kpi label="Cropland" value={n(lc.cropland_pct, 0)} unit=" %" />}
        {d.surface_water && <Kpi label="Surface water" value={n(d.surface_water.water_fraction_pct, 1)} unit=" %" />}
      </div>
      <div className="gi-split">
        <div><h4>Vegetation density</h4><StackBar parts={Object.entries(v.density_pct).map(([label, value], i) => ({ label, value, color: ['#0f7a3d', '#59b85f', '#c9d36b', '#8a6d4b'][i] }))} /></div>
        {lc && <div><h4>Land cover</h4><StackBar parts={Object.entries(lc.classes_pct).slice(0, 6).map(([label, value]) => ({ label, value }))} /></div>}
      </div>
      {ch && (
        <div className="gi-callout">
          <strong>Change vs {ch.previous_scene_date}</strong>
          <span>Mean NDVI {sign(ch.mean_ndvi_change)}; {ch.declined_pct}% of pixels declined and {ch.improved_pct}% improved{ch.tree_pixels_with_decline_pct != null ? `; ${ch.tree_pixels_with_decline_pct}% of tree-cover pixels declined` : ''}.</span>
          <small>{ch.note}</small>
        </div>
      )}
    </Card>
  );
}

function WaterCard({ d }) {
  const f = d.mapped_features; const sw = d.surface_water; const st = d.stress;
  return (
    <Card title="Water" icon="≈" source={[f?.source, sw && `Sentinel-2 scene ${sw.scene_date}`].filter(Boolean).join(' · ')}>
      {st && <div className="gi-stress"><Chip tone={st.level === 'low' ? 'good' : st.level === 'moderate' ? 'mid' : 'warn'}>Water stress: {st.level}</Chip><span>{st.aridity_class}, aridity {st.aridity_index}; balance {n(st.climatic_water_balance_mm, 0)} mm/yr</span></div>}
      <div className="gi-kpis">
        {f && <Kpi label="Rivers" value={f.river_segments} unit=" segments" hint={`${f.streams_and_canals} streams/canals`} />}
        {f && <Kpi label="Lakes & reservoirs" value={f.lakes_and_water_bodies + f.reservoirs} unit="" hint="mapped features" />}
        {sw && <Kpi label="Surface water" value={n(sw.water_fraction_pct, 1)} unit=" %" hint={sw.change_vs_last_year_pp != null ? `${sign(sw.change_vs_last_year_pp)} pp vs last year` : 'Sentinel-2'} />}
      </div>
      {st && <details className="gi-details"><summary>How water stress is derived</summary><p>{st.method}</p></details>}
    </Card>
  );
}

function SoilCard({ d }) {
  const p = d.properties; const f = d.fertility;
  return (
    <Card title="Soil" icon="◍" source={`${d.source}. Depth ${d.depth}.`}>
      <div className="gi-kpis">
        {d.texture_class && <Kpi label="Texture" value={d.texture_class} unit="" />}
        {d.classification && <Kpi label="WRB class" value={d.classification.wrb_class} unit="" hint="most probable" />}
        <Kpi label="pH" value={n(p.ph)} unit="" />
        <Kpi label="Organic carbon" value={n(p.organic_carbon_g_per_kg)} unit=" g/kg" />
      </div>
      {p.clay_pct != null && <StackBar parts={[{ label: 'Clay', value: Math.round(p.clay_pct), color: '#b07a5b' }, { label: 'Silt', value: Math.round(p.silt_pct), color: '#c9b79c' }, { label: 'Sand', value: Math.round(p.sand_pct), color: '#e8d9a8' }]} />}
      {f?.status === 'scored' && <details className="gi-details"><summary>Fertility index {f.score}/100 · {f.class}</summary><p>{f.method}</p></details>}
    </Card>
  );
}

function AgricultureCard({ d }) {
  return (
    <Card title="Agricultural & crop suitability" icon="✿" source="Climate normals (ERA5) + SoilGrids pH">
      <div className="gi-split gi-split--ring"><Ring value={d.score} label={`${d.class} suitability`} tone="#4fd1a5" />
        <HBars items={d.crops.slice(0, 5).map((c) => ({ label: `${c.crop} · limited by ${c.limiting_factor}`, value: c.score }))} max={100} /></div>
      <details className="gi-details"><summary>How it is calculated</summary><p>{d.method}</p></details>
    </Card>
  );
}

function ResourceRow({ item }) {
  const [open, setOpen] = useState(false);
  const label = item.kind === 'mineral' ? item.commodity : item.kind === 'petroleum' ? 'Petroleum' : 'Natural gas';
  const scored = item.status === 'scored';
  const missingCriteria = (item.criteria || []).filter((criterion) => !criterion.evidence_count).map((criterion) => criterion.label);
  const occurrences = item.occurrence_records || [];
  return (
    <li className="gi-res">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        <strong>{label}</strong>
        {scored ? <div className="gi-res__bar"><em style={{ width: `${item.potential_score}%` }} /></div> : <span className="gi-res__empty">Score withheld</span>}
        <span>{scored ? n(item.potential_score, 0) : '—'}</span>
        <Chip tone={scored ? toneFor(item.classification) : 'neutral'}>{scored ? item.classification : 'Not assessed'}</Chip>
      </button>
      {open && (
        <div className="gi-res__detail">
          <p><b>{item.assessment_message || 'Insufficient geological evidence for reliable assessment.'}</b></p>
          <p>Confidence: <b>{item.confidence?.label || 'Not assessed'}</b>. Automatic score withheld; no validated predictive model is applied to these data.</p>
          {missingCriteria.length > 0 && <p><strong>Model criteria without submitted evidence:</strong> {missingCriteria.join(', ')}.</p>}
          {(item.supporting_evidence || []).map((e) => <p key={e}>• {e}</p>)}
          {occurrences.length > 0 && (
            <div className="gi-occurrences">
              <strong>Historical reports inside this selection · unverified</strong>
              <ul>{occurrences.map((record, index) => (
                <li key={record.record_id || `${record.name}-${index}`}>
                  <span><b>{record.name || 'Unnamed MRDS record'}</b><small>{record.status || 'Status not supplied'}{record.commodity_codes ? ` · codes ${record.commodity_codes}` : ''}</small></span>
                  {record.record_url?.startsWith('https://mrdata.usgs.gov/') && <a href={record.record_url} target="_blank" rel="noreferrer">USGS record</a>}
                </li>
              ))}</ul>
              <small>These are historical reported localities, not verified deposits, active mines, or reserves.</small>
            </div>
          )}
          {(item.missing_datasets || []).length > 0 && <details className="gi-details"><summary>Required datasets not integrated</summary><ul>{item.missing_datasets.map((dataset) => <li key={dataset}>{dataset}</li>)}</ul></details>}
        </div>
      )}
    </li>
  );
}

function ResourceCard({ data }) {
  const res = data.results || [];
  const minerals = res.filter((result) => result.kind === 'mineral');
  const hydrocarbons = res.filter((result) => result.kind !== 'mineral');
  const sampling = data.sampling || {};
  return (
    <Card title="Mineral & petroleum geology context" icon="◆" source="Macrostrat mapped-unit samples · historical USGS MRDS reports" wide>
      <div className="gi-evidence-gate" role="status">
        <span className="gi-evidence-gate__label">AUTOMATIC SCORE WITHHELD</span>
        <strong>{data.assessment_message || 'Insufficient geological evidence for reliable assessment.'}</strong>
        <p>These sources provide geological context, not a validated mineral or petroleum prediction. Weather, vegetation, soil and terrain are not treated as direct proof of underground resources.</p>
      </div>
      <div className="gi-sampling-note">
        <strong>{n(sampling.points_with_units, 0)} / {n(sampling.points, 0)} Macrostrat query points returned mapped units</strong>
        <span>{sampling.coverage_definition || 'Query-point response only; not area-weighted coverage.'}</span>
      </div>
      <div className="gi-source-grid">
        {(data.sources || []).map((source) => (
          <div className="gi-source-card" key={source.name}>
            <div><strong>{source.name}</strong><Chip tone={source.available ? 'good' : 'warn'}>{source.available ? 'Responded' : 'Unavailable'}</Chip></div>
            <p>{source.data_status || source.license || 'Provider status only; no prospectivity score is derived.'}</p>
            {source.url && <small className="gi-source-card__url">{source.url}</small>}
          </div>
        ))}
      </div>
      <div className="gi-split">
        <div><h4>Mineral-specific context</h4><ul className="gi-reslist">{minerals.map((item) => <ResourceRow item={item} key={item.model} />)}</ul></div>
        <div><h4>Petroleum system context</h4><ul className="gi-reslist">{hydrocarbons.map((item) => <ResourceRow item={item} key={item.model} />)}</ul></div>
      </div>
      <details className="gi-details"><summary>Data limitations and interpretation</summary><ul>{[...new Set(res.flatMap((item) => item.limitations || []))].map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></details>
    </Card>
  );
}

export default function AutoAnalysisPanel({ region, regionError, analyzeSignal = 0, onOverlays = () => {} }) {
  const [mods, setMods] = useState({});
  const [resources, setResources] = useState(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState('');
  const run = useRef(0);
  const started = Object.keys(mods).length > 0;

  const load = useCallback(async (name, id, bbox) => {
    setMods((m) => ({ ...m, [name]: { status: 'loading' } }));
    let result;
    try { result = await requestModule(bbox, name); } catch (e) { result = { status: 'na', reason: e.message }; }
    if (id === run.current) setMods((m) => ({ ...m, [name]: result }));
    return result;
  }, []);

  const analyze = useCallback(async () => {
    if (!region || region.tooLarge) return;
    const id = ++run.current; const { bbox } = region;
    setMods({}); setResources({ status: 'loading' }); setPdfError('');
    requestProspectivity(region).then((r) => { if (id === run.current) setResources({ status: 'ok', data: r }); })
      .catch((e) => { if (id === run.current) setResources({ status: 'na', reason: e.message }); });
    await Promise.allSettled(BASE.map((m) => load(m, id, bbox)));
    if (id === run.current) load('suitability', id, bbox);
  }, [region, load]);

  useEffect(() => { if (analyzeSignal > 0) analyze(); }, [analyzeSignal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setMods({}); setResources(null); run.current += 1; }, [region]);
  useEffect(() => {
    const environmentLayers = Object.values(mods).flatMap((module) => module.overlays || []);
    const geologyLayers = resources?.status === 'ok' ? (resources.data?.map_layers || []) : [];
    onOverlays([...environmentLayers, ...geologyLayers]);
  }, [mods, resources]); // eslint-disable-line react-hooks/exhaustive-deps

  const ok = (k) => mods[k]?.status === 'ok';
  const d = (k) => mods[k]?.data;
  const loading = Object.values(mods).some((m) => m.status === 'loading') || resources?.status === 'loading';
  const failed = [...BASE.filter((k) => mods[k]?.status === 'na').map((k) => [k, mods[k].reason])];
  if (resources?.status === 'na') failed.push(['resources', resources.reason]);
  const suit = d('suitability'); const hab = suit?.habitability; const ag = suit?.agriculture;
  const reportSections = [
    ...BASE.filter(ok).map((key) => LABELS[key]),
    ...(ok('suitability') ? [LABELS.suitability] : []),
    ...(resources?.status === 'ok' ? ['Mineral & petroleum geology context'] : []),
  ];

  const pdf = async () => {
    setPdfBusy(true); setPdfError('');
    try {
      const modules = Object.fromEntries(Object.entries(mods).filter(([, v]) => v.status === 'ok').map(([k, v]) => [k, v.data]));
      const prospectivity = resources?.status === 'ok' ? { ...resources.data, map_layers: undefined } : undefined;
      await downloadReportPdf({ region: { name: region.name, bbox: region.bbox, boundarySource: region.boundarySource, geometryType: region.geometry?.type || 'BoundingBox', geometry: region.geometry }, modules, overlays: Object.values(mods).flatMap((m) => m.overlays || []).filter((o) => o.id === 'ndvi' || o.id === 'landcover'), prospectivity });
    } catch (e) { setPdfError(e.message); } finally { setPdfBusy(false); }
  };

  return (
    <section className="gi-analysis" id="region-analysis" aria-labelledby="gi-title">
      <div className="gi-head">
        <div><p className="eyebrow">REGION INTELLIGENCE</p><h2 id="gi-title">{region ? region.name : 'Select a region'}</h2>
          {region ? <p className="gi-sub">W {n(region.bbox[0], 3)} · S {n(region.bbox[1], 3)} · E {n(region.bbox[2], 3)} · N {n(region.bbox[3], 3)} — {region.boundarySource}</p>
            : <p className="gi-sub">Search a place, click the map, or draw an area, then analyze.</p>}
        </div>
        <div className="gi-actions">
          <button type="button" className="gi-btn gi-btn--primary" onClick={analyze} disabled={!region || region.tooLarge || loading}>{loading ? 'Analyzing…' : started ? 'Re-run analysis' : 'Analyze region'}</button>
          {started && !loading && <button type="button" className="gi-btn" onClick={pdf} disabled={pdfBusy}>{pdfBusy ? 'Preparing PDF…' : 'Download PDF report'}</button>}
        </div>
      </div>
      {regionError && <p className="gi-hint" role="status">{regionError}</p>}
      {pdfError && <p className="gi-hint" role="status">{pdfError}</p>}
      {loading && <div className="gi-progress" role="progressbar" aria-label="Analysis in progress"><i /></div>}
      {started && !loading && (
        <details className="gi-report-preview">
          <summary>Report preview · {reportSections.length} available section{reportSections.length === 1 ? '' : 's'}</summary>
          <div>
            <p><strong>Region:</strong> {region?.name || 'Selected region'} · {region?.boundarySource || 'WGS84 selection'}.</p>
            <p><strong>Available sections:</strong> {reportSections.length ? reportSections.join(' · ') : 'No provider-backed sections returned.'}</p>
            {resources?.status === 'ok' && <p><strong>Mineral/petroleum:</strong> automatic score and confidence are withheld unless a validated model and suitable evidence are available.</p>}
            {failed.length > 0 && <p><strong>Not included:</strong> {failed.map(([key]) => LABELS[key]).join(', ')} did not return data.</p>}
          </div>
        </details>
      )}

      {(hab?.status === 'scored' || ag?.score != null) && (
        <div className="gi-summary">
          {hab?.status === 'scored' && <div className="gi-summary__item"><Ring value={hab.score} label={`Habitability · ${hab.class}`} />
            <div><h3>Regional suitability</h3><ul className="gi-comp">{hab.components.map((c) => <li key={c.name}><span>{c.name}</span><div><em style={{ width: `${c.score}%` }} /></div><b>{n(c.score, 0)}</b><small>{c.basis}</small></li>)}</ul>
              <details className="gi-details"><summary>How this score is calculated</summary><p>{hab.method}</p></details></div></div>}
        </div>
      )}

      <div className="gi-grid">
        {mods.climate?.status === 'loading' && <Skeleton title="Climate" />}{ok('climate') && <ClimateCard d={d('climate')} />}
        {mods.vegetation?.status === 'loading' && <Skeleton title="Vegetation & land cover" />}{ok('vegetation') && <VegetationCard d={d('vegetation')} />}
        {mods.water?.status === 'loading' && <Skeleton title="Water" />}{ok('water') && <WaterCard d={d('water')} />}
        {mods.terrain?.status === 'loading' && <Skeleton title="Terrain" />}{ok('terrain') && <TerrainCard d={d('terrain')} />}
        {mods.soil?.status === 'loading' && <Skeleton title="Soil" />}{ok('soil') && <SoilCard d={d('soil')} />}
        {ag?.score != null && <AgricultureCard d={ag} />}
        {resources?.status === 'loading' && <Skeleton title="Mineral & petroleum prospectivity" />}{resources?.status === 'ok' && <ResourceCard data={resources.data} />}
      </div>

      {!loading && failed.length > 0 && (
        <div className="gi-quiet" role="status">
          <span>Some public data sources did not respond for this region:</span>
          {failed.map(([k, reason]) => (
            <span key={k} className="gi-quiet__item" title={reason}>{LABELS[k]}{k !== 'resources' && <button type="button" onClick={() => load(k, run.current, region.bbox)}>retry</button>}</span>
          ))}
        </div>
      )}
    </section>
  );
}
