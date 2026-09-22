import { useEffect, useState, useMemo } from "react";
import { MapContainer, TileLayer, Polygon, Popup, useMap } from "react-leaflet";
import { motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/appContext";
import { toLeafletPositions } from "../lib/geo";
import { riskColor, riskLabel } from "../lib/risk";
import {
  SectionHeading,
  PrototypeTag,
  ErrorState,
  EmptyState,
  RiskBadge,
  Skeleton,
  PageTransition,
} from "../components/ui";

const NCR_CENTER = [28.6139, 77.209];

export default function RiskMap() {
  const { selectZone } = useApp();
  const [collection, setCollection] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    setLoading(true);
    api
      .zoneRisk()
      .then(setCollection)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load zones."))
      .finally(() => setLoading(false));
  }, []);

  const features = useMemo(() => {
    const all = collection?.features ?? [];
    if (filter === "ALL") return all;
    return all.filter((f) => f.properties.risk_level === filter);
  }, [collection, filter]);

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Phase 10 · Spatial Risk"
        title="NCR Heat Risk Map"
        description="Zone-level heat risk combining thermal stress with population vulnerability."
      />

      {collection && (
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <PrototypeTag>
            {collection.data_status === "SYNTHETIC_DEMO"
              ? "Prototype visualization — synthetic demo zones"
              : collection.data_status}
          </PrototypeTag>
          <p className="text-xs text-ink-400">{collection.warning}</p>
        </div>
      )}

      {error ? (
        <ErrorState message={error} />
      ) : loading ? (
        <Skeleton className="h-[560px] w-full rounded-2xl" />
      ) : !features.length ? (
        <EmptyState
          icon={AlertTriangle}
          title="No zones to show"
          message="The demo zone dataset returned no features for this filter."
        />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
          <div className="xl:col-span-3 rounded-2xl overflow-hidden border border-ink-700 h-[560px] relative">
            <MapContainer center={NCR_CENTER} zoom={10} className="h-full w-full" scrollWheelZoom>
              <TileLayer
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              />
              {features.map((f) => (
                <ZonePolygon key={f.properties.zone_id} feature={f} onSelect={selectZone} />
              ))}
            </MapContainer>

            <div className="absolute bottom-3 left-3 z-[1000] bg-ink-900/90 backdrop-blur border border-ink-700 rounded-xl px-3 py-2.5 text-[11px] space-y-1.5">
              <p className="font-semibold text-ink-200 mb-1">Risk level</p>
              {["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"].map((lvl) => (
                <div key={lvl} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: riskColor(lvl) }} />
                  <span className="text-ink-300">{riskLabel(lvl)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {["ALL", "LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"].map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => setFilter(lvl)}
                  className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                    filter === lvl
                      ? "bg-brand-700 border-brand-600 text-white"
                      : "border-ink-600 text-ink-400 hover:text-ink-100"
                  }`}
                >
                  {lvl === "ALL" ? "All zones" : riskLabel(lvl)}
                </button>
              ))}
            </div>

            <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
              {[...features]
                .sort((a, b) => b.properties.human_risk - a.properties.human_risk)
                .map((f) => (
                  <ZoneListItem key={f.properties.zone_id} feature={f} onSelect={selectZone} />
                ))}
            </div>
          </div>
        </div>
      )}
    </PageTransition>
  );
}

function ZonePolygon({ feature, onSelect }) {
  const color = riskColor(feature.properties.risk_level);
  const positions = toLeafletPositions(feature.geometry);
  if (!positions.length) return null;

  return (
    <Polygon
      positions={positions}
      pathOptions={{ color, weight: 1.5, fillColor: color, fillOpacity: 0.35 }}
      eventHandlers={{ click: () => onSelect(feature) }}
    >
      <Popup>
        <ZonePopup feature={feature} />
      </Popup>
    </Polygon>
  );
}

function ZonePopup({ feature }) {
  const p = feature.properties;
  return (
    <div className="text-ink-900 text-xs space-y-1 min-w-[180px]">
      <p className="font-semibold text-sm mb-1">{p.name ?? p.zone_id}</p>
      <Row label="Risk" value={riskLabel(p.risk_level)} />
      <Row label="Priority" value={p.priority} />
      {p.heat_index != null && <Row label="Heat Index" value={`${p.heat_index.toFixed(1)} °C`} />}
      {p.wbgt != null && <Row label="WBGT" value={`${p.wbgt.toFixed(1)} °C`} />}
      {p.utci != null && <Row label="UTCI" value={`${p.utci.toFixed(1)} °C`} />}
      <Row label="Vulnerability" value={riskLabel(p.vulnerability_level)} />
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-ink-500">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function ZoneListItem({ feature, onSelect }) {
  const p = feature.properties;
  return (
    <motion.button
      whileHover={{ x: 2 }}
      onClick={() => onSelect(feature)}
      className="w-full text-left rounded-xl border border-ink-700 bg-ink-850 p-3 hover:border-brand-600/50 transition-colors"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium text-ink-100">{p.name ?? p.zone_id}</span>
        <RiskBadge level={p.risk_level} size="sm" />
      </div>
      <p className="text-[11px] text-ink-400">
        Priority: <span className="text-ink-200">{p.priority}</span> · Vulnerability:{" "}
        {riskLabel(p.vulnerability_level)}
      </p>
    </motion.button>
  );
}
