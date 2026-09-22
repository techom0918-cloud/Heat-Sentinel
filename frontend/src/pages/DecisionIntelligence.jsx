import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Play, Loader2, CheckCircle2, XCircle, CircleDashed, MapPinned } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/appContext";
import { SectionHeading, GlowCard, RiskBadge, PageTransition } from "../components/ui";

// Decision Intelligence = the existing engines run in sequence for one
// place. There is no separate "decision" endpoint in the backend, so this
// page does not invent one: each stage below is a real API call, and its
// card shows exactly what that engine returned (or why it failed).
const STAGES = [
  { key: "conditions", title: "1 · Current conditions", engine: "Weather + Thermal Stress Engine", needsZone: false },
  { key: "forecast", title: "2 · 3-day risk trajectory", engine: "Risk Forecast & Trajectory", needsZone: false },
  { key: "alert", title: "3 · Early-warning decision", engine: "Early Warning & Alerts", needsZone: true },
  { key: "plan", title: "4 · Recommended action plan", engine: "AI Action Optimizer", needsZone: true },
];

export default function DecisionIntelligence() {
  const { location } = useApp();
  const [results, setResults] = useState({});
  const [errors, setErrors] = useState({});
  const [running, setRunning] = useState(null);

  async function run() {
    setResults({});
    setErrors({});
    const calls = {
      conditions: () => api.currentThermal(location.latitude, location.longitude),
      forecast: () => api.riskTrajectory(location.latitude, location.longitude, 3),
      alert: () => api.evaluateAlert(location.zone_id, 3),
      plan: () => api.optimizeInterventions({
        zone_id: location.zone_id, budget: 500000,
        available_resources: { cooling_centers: 2, water_tankers: 10, field_workers: 50 },
      }),
    };
    for (const s of STAGES) {
      if (s.needsZone && !location.zone_id) continue;
      setRunning(s.key);
      try {
        const r = await calls[s.key]();
        setResults((p) => ({ ...p, [s.key]: r }));
      } catch (e) {
        setErrors((p) => ({ ...p, [s.key]: e instanceof ApiError ? e.message : "Stage failed." }));
      }
    }
    setRunning(null);
  }

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Decision Intelligence"
        title="From data to decision"
        description="Runs the HeatSentinel engines in sequence for the selected place — conditions, forecast, warning, action — and shows each engine's real output."
      />

      <GlowCard className="p-5 mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-ink-300">
          Location: <strong className="text-ink-100">{location.label}</strong>
          {!location.zone_id && (
            <span className="block text-xs text-ink-400 mt-0.5">
              Stages 3–4 need a zone — <Link to="/map" className="text-brand-600 underline">select one on the map</Link>.
            </span>
          )}
        </div>
        <button onClick={run} disabled={Boolean(running)} className="btn-primary flex items-center gap-2">
          {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          {running ? "Running pipeline…" : "Run decision pipeline"}
        </button>
      </GlowCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {STAGES.map((s, i) => {
          const r = results[s.key], err = errors[s.key];
          const skipped = s.needsZone && !location.zone_id;
          const icon = running === s.key ? <Loader2 size={16} className="animate-spin text-brand-600" />
            : r ? <CheckCircle2 size={16} className="text-risk-low" />
            : err ? <XCircle size={16} className="text-risk-veryhigh" />
            : <CircleDashed size={16} className="text-ink-500" />;
          return (
            <motion.div key={s.key} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <GlowCard className="p-5 h-full">
                <div className="flex items-center gap-2 mb-1">{icon}<h3 className="font-semibold text-ink-100">{s.title}</h3></div>
                <p className="text-[11px] text-ink-400 mb-3">{s.engine}</p>
                {skipped && <p className="text-xs text-ink-400 flex items-center gap-1.5"><MapPinned size={13} /> Needs a selected zone.</p>}
                {err && <p className="text-xs text-risk-veryhigh">{err}</p>}
                {r && <StageBody stage={s.key} r={r} />}
                {!r && !err && !skipped && running !== s.key && <p className="text-xs text-ink-500">Not run yet.</p>}
              </GlowCard>
            </motion.div>
          );
        })}
      </div>
    </PageTransition>
  );
}

function StageBody({ stage, r }) {
  if (stage === "conditions") {
    const t = r.thermal, w = r.weather;
    return (
      <div className="space-y-2 text-sm">
        <RiskBadge level={t.heat_index_category} />
        <p className="text-ink-300">
          {w.temperature_c}°C · {w.relative_humidity}% RH → Heat Index{" "}
          <strong className="text-ink-100">{t.heat_index?.toFixed(1) ?? "—"}°C</strong>, WBGT{" "}
          <strong className="text-ink-100">{t.wbgt?.toFixed(1) ?? "—"}°C</strong>, UTCI{" "}
          <strong className="text-ink-100">{t.utci?.toFixed(1) ?? "—"}°C</strong>
        </p>
      </div>
    );
  }
  if (stage === "forecast") {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-ink-300">Trend: <strong className="text-ink-100">{r.trend}</strong> · peak{" "}
          <RiskBadge level={r.peak_risk} size="sm" /> on {r.peak_date}</p>
        <div className="flex gap-2">
          {r.forecast.map((d) => (
            <div key={d.target_date} className="flex-1 rounded-lg bg-ink-800 border border-ink-700 p-2 text-center">
              <p className="text-[10px] text-ink-400">{d.target_date}</p>
              <RiskBadge level={d.risk_level} size="sm" />
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (stage === "alert") {
    return (
      <div className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <RiskBadge level={r.alert_level} />
          <span className="text-xs text-ink-400">{r.alert_required ? `Alert required · ${r.priority}` : "No alert required"}</span>
        </div>
        <p className="text-ink-300 text-xs">{r.reason}</p>
        {r.recommended_actions?.length > 0 && (
          <ul className="text-xs text-ink-300 space-y-1">{r.recommended_actions.slice(0, 4).map((a, i) => <li key={i}>· {a}</li>)}</ul>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <RiskBadge level={r.baseline_risk_level} size="sm" /><span className="text-ink-500">→</span>
        <RiskBadge level={r.optimized_risk_level} size="sm" />
        <span className="text-risk-low font-semibold ml-auto">−{r.estimated_risk_reduction_percent.toFixed(1)}%</span>
      </div>
      <ul className="text-xs text-ink-300 space-y-1">
        {r.recommended_actions.length === 0 ? <li>No affordable action improved risk further.</li>
          : r.recommended_actions.map((a, i) => <li key={i}>· {a.type.replace(/_/g, " ")} ×{a.quantity} — ₹{a.cost.toLocaleString("en-IN")}</li>)}
      </ul>
    </div>
  );
}
