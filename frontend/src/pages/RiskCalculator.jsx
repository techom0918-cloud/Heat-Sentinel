import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Calculator, Loader2, MapPin, UserCircle2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/appContext";
import { SectionHeading, GlowCard, RiskBadge, ErrorState, PageTransition } from "../components/ui";

const INPUTS = [
  { key: "temperature", label: "Air temperature", unit: "°C", min: -10, max: 55, step: 0.5 },
  { key: "relative_humidity", label: "Relative humidity", unit: "%", min: 0, max: 100, step: 1 },
  { key: "wind_speed", label: "Wind speed", unit: "m/s", min: 0, max: 20, step: 0.1 },
  { key: "solar_radiation", label: "Solar radiation", unit: "W/m²", min: 0, max: 1200, step: 10 },
];

// The calculation pipeline is entirely server-side:
//   POST /thermal/calculate  -> Heat Index, WBGT, UTCI (Thermal Stress Engine)
//   POST /risk/predict       -> combined risk (Health Risk Engine)
// This page only collects inputs and renders the backend's answers.
export default function RiskCalculator() {
  const { location } = useApp();
  const [inputs, setInputs] = useState({
    temperature: 40, relative_humidity: 45, wind_speed: 2, solar_radiation: 700,
  });
  const [vulnerability, setVulnerability] = useState(0.5);
  const [prefilling, setPrefilling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [thermal, setThermal] = useState(null);
  const [risk, setRisk] = useState(null);

  const set = (k, v) => setInputs((p) => ({ ...p, [k]: v }));

  async function useCurrentConditions() {
    setPrefilling(true);
    setError(null);
    try {
      const d = await api.currentThermal(location.latitude, location.longitude);
      setInputs({
        temperature: d.weather.temperature_c,
        relative_humidity: d.weather.relative_humidity,
        wind_speed: d.weather.wind_speed_ms ?? 0,
        solar_radiation: d.weather.solar_radiation_wm2 ?? 0,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load current conditions.");
    } finally {
      setPrefilling(false);
    }
  }

  async function calculate() {
    setBusy(true);
    setError(null);
    setThermal(null);
    setRisk(null);
    try {
      const th = await api.calculateThermal({
        temperature: Number(inputs.temperature),
        relative_humidity: Number(inputs.relative_humidity),
        wind_speed: Number(inputs.wind_speed),
        solar_radiation: Number(inputs.solar_radiation),
      });
      setThermal(th);
      if (th.heat_index === null || th.wbgt === null) {
        throw new ApiError(
          "The thermal engine could not compute Heat Index/WBGT for these inputs, so no risk was calculated.",
          422, null
        );
      }
      const r = await api.predictRisk({
        temperature_c: th.temperature,
        relative_humidity: th.relative_humidity,
        wind_speed: th.wind_speed,
        solar_radiation: th.solar_radiation,
        heat_index: th.heat_index,
        wbgt: th.wbgt,
        utci: th.utci,
        vulnerability_score: Number(vulnerability),
      });
      setRisk(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Risk calculation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Heat Risk · Calculator"
        title="Heat Risk Calculator"
        description="Enter conditions (or load the current ones). The Thermal Stress Engine and Health Risk Engine on the backend compute the result."
      />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <GlowCard className="p-6 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Calculator size={17} className="text-brand-600" />
              <h3 className="font-semibold text-ink-100">Inputs</h3>
            </div>
            <button onClick={useCurrentConditions} disabled={prefilling}
              className="text-xs flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-ink-700 hover:border-brand-500 text-ink-300 disabled:opacity-50">
              {prefilling ? <Loader2 size={12} className="animate-spin" /> : <MapPin size={12} />}
              Use current conditions
            </button>
          </div>

          <div className="space-y-4">
            {INPUTS.map((f) => (
              <div key={f.key}>
                <div className="flex justify-between mb-1">
                  <label className="text-xs font-medium text-ink-300">{f.label}</label>
                  <span className="text-xs font-semibold text-ink-100">{inputs[f.key]} {f.unit}</span>
                </div>
                <input type="range" min={f.min} max={f.max} step={f.step} value={inputs[f.key]}
                  onChange={(e) => set(f.key, e.target.value)} className="w-full accent-brand-600" />
              </div>
            ))}

            <div className="pt-2 border-t border-ink-700">
              <div className="flex justify-between mb-1">
                <label className="text-xs font-medium text-ink-300">Population vulnerability score</label>
                <span className="text-xs font-semibold text-ink-100">{Number(vulnerability).toFixed(2)}</span>
              </div>
              <input type="range" min={0} max={1} step={0.01} value={vulnerability}
                onChange={(e) => setVulnerability(e.target.value)} className="w-full accent-brand-600" />
              <p className="text-[11px] text-ink-400 mt-1">
                0 = least, 1 = most vulnerable population. Compute a real score on the{" "}
                <Link to="/vulnerability" className="text-brand-600 underline">Vulnerability</Link> page.
              </p>
            </div>

            <button onClick={calculate} disabled={busy}
              className="btn-primary w-full flex items-center justify-center gap-2">
              {busy && <Loader2 size={15} className="animate-spin" />} Calculate heat risk
            </button>

            <p className="text-[11px] text-ink-400 flex gap-1.5">
              <UserCircle2 size={13} className="shrink-0 mt-0.5" />
              <span>Exposure time, activity, time of day and personal factors are scored by the{" "}
              <Link to="/personal" className="text-brand-600 underline">Personal Risk assessment</Link>.</span>
            </p>
          </div>
        </GlowCard>

        <div className="lg:col-span-3 space-y-4">
          {error && <ErrorState message={error} onRetry={calculate} />}

          {!thermal && !error && (
            <GlowCard className="p-8 text-center text-sm text-ink-400 min-h-[260px] flex items-center justify-center">
              Set the inputs and press “Calculate heat risk”.
            </GlowCard>
          )}

          {thermal && (
            <div className="grid grid-cols-3 gap-3">
              {[
                ["Heat Index", thermal.heat_index, thermal.heat_index_category],
                ["WBGT", thermal.wbgt, thermal.wbgt_category],
                ["UTCI", thermal.utci, thermal.utci_category],
              ].map(([label, v, cat]) => (
                <GlowCard key={label} className="p-4">
                  <p className="text-[11px] text-ink-400 mb-1">{label}</p>
                  <p className="text-2xl font-serif font-semibold text-ink-100">
                    {v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}°C`}
                  </p>
                  <p className="text-[10px] text-ink-400 mt-1 truncate" title={cat}>{cat?.replace(/_/g, " ")}</p>
                </GlowCard>
              ))}
            </div>
          )}

          {risk && (
            <GlowCard className="p-6">
              <p className="text-xs text-ink-400 mb-2">Combined heat-health risk</p>
              <div className="flex items-center gap-3 mb-4">
                <RiskBadge level={risk.risk_level} size="lg" />
                <span className="text-3xl font-serif font-semibold text-ink-100">
                  {(risk.risk_score * 100).toFixed(0)}%
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4 text-xs">
                <div className="rounded-lg bg-ink-800 border border-ink-700 p-3">
                  <p className="text-ink-400">Thermal stress component</p>
                  <p className="text-ink-100 font-semibold">{(risk.components.thermal_stress * 100).toFixed(0)}%</p>
                </div>
                <div className="rounded-lg bg-ink-800 border border-ink-700 p-3">
                  <p className="text-ink-400">Vulnerability component</p>
                  <p className="text-ink-100 font-semibold">{(risk.components.vulnerability * 100).toFixed(0)}%</p>
                </div>
              </div>

              <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-300 mb-2">Main risk factors</h4>
              <div className="space-y-2">
                {[...risk.contributors].sort((a, b) => b.impact - a.impact).map((c) => (
                  <div key={c.factor}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-ink-200">{c.factor.replace(/_/g, " ")}</span>
                      <span className="text-ink-400">{(c.impact * 100).toFixed(1)}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-ink-700 overflow-hidden">
                      <motion.div initial={{ width: 0 }}
                        animate={{ width: `${risk.risk_score ? (c.impact / risk.risk_score) * 100 : 0}%` }}
                        className="h-full bg-brand-600 rounded-full" />
                    </div>
                  </div>
                ))}
              </div>

              {risk.notes?.length > 0 && (
                <ul className="text-[11px] text-ink-400 mt-4 space-y-1">
                  {risk.notes.map((n, i) => <li key={i}>· {n}</li>)}
                </ul>
              )}
              <div className="flex flex-wrap gap-2 mt-4">
                <Link to="/personal" className="btn-ghost text-xs">Get personalised recommendations</Link>
                <Link to="/interventions" className="btn-ghost text-xs">See interventions</Link>
              </div>
              <p className="text-[11px] text-ink-400 mt-4">{risk.disclaimer}</p>
            </GlowCard>
          )}
        </div>
      </div>
    </PageTransition>
  );
}
