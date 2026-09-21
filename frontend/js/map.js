/* Risk map. Renders the backend's real zone GeoJSON from /zones/risk.
 * There is no local geometry file and no hardcoded city marker: if the
 * endpoint fails, the map shows an error state rather than stale shapes. */
(function () {
  const UI = window.HS_UI, CFG = window.HS_CONFIG;

  let map = null, zoneLayer = null;

  function ensure(elId) {
    if (map) return map;
    map = L.map(elId, { zoomControl: true, scrollWheelZoom: false })
           .setView(CFG.MAP_CENTER, CFG.MAP_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors | HeatSentinal',
      maxZoom: 18
    }).addTo(map);
    // Tapping is the primary interaction on touch; wheel-zoom stays off so
    // the page still scrolls past the map on mobile.
    map.on('click', () => map.scrollWheelZoom.enable());
    return map;
  }

  /** Popup content is built entirely from ZoneProperties returned by the API. */
  function popup(p) {
    const row = (label, value) =>
      `<div style="display:flex;justify-content:space-between;gap:14px;padding:2px 0">
         <span style="color:#6F6A66">${UI.esc(label)}</span>
         <b>${value === null ? '<i style="color:#6F6A66;font-weight:400">Unavailable</i>' : UI.esc(value)}</b>
       </div>`;
    return `<div style="min-width:212px;font-family:Inter,sans-serif;font-size:12.5px">
      <div style="font-family:'Source Serif 4',Georgia,serif;font-size:15px;font-weight:600;margin-bottom:6px">
        ${UI.esc(p.name || p.zone_id)}</div>
      <div style="margin-bottom:7px">${UI.riskPill(p.risk_level)}</div>
      ${row('Heat Index', UI.num(p.heat_index, ' °C'))}
      ${row('WBGT', UI.num(p.wbgt, ' °C'))}
      ${row('UTCI', UI.num(p.utci, ' °C'))}
      ${row('Vulnerability', UI.num(p.vulnerability, '', 2))}
      ${row('Priority', p.priority)}
      <a href="#/map" style="display:inline-block;margin-top:7px;font-size:12px">Open in GIS view</a>
    </div>`;
  }

  function style(p) {
    return {
      color: '#fff', weight: 1.5, opacity: .9,
      fillColor: UI.riskMeta(p.risk_level).color, fillOpacity: .62
    };
  }

  /** @param {object} collection ZoneRiskCollection from the API */
  function renderZones(elId, collection) {
    const m = ensure(elId);
    if (zoneLayer) { m.removeLayer(zoneLayer); zoneLayer = null; }

    const feats = (collection.features || []).filter(f => f.geometry);
    if (!feats.length) return 0;

    zoneLayer = L.geoJSON({ type: 'FeatureCollection', features: feats }, {
      style: (f) => style(f.properties),
      onEachFeature: (f, layer) => {
        layer.bindPopup(popup(f.properties));
        layer.on('mouseover', () => layer.setStyle({ weight: 3, fillOpacity: .78 }));
        layer.on('mouseout',  () => layer.setStyle(style(f.properties)));
      }
    }).addTo(m);

    m.fitBounds(zoneLayer.getBounds(), { padding: [22, 22] });
    setTimeout(() => m.invalidateSize(), 60);
    return feats.length;
  }

  function destroy() {
    if (map) { map.remove(); map = null; zoneLayer = null; }
  }

  window.HS_MAP = { renderZones, destroy, ensure };
})();
