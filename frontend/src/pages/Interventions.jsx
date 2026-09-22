import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Droplet, ShieldPlus, MapPinned, Play, Wand2 } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api, ApiError } from "../lib/api";
import { riskColor } from "../lib/risk";
import {
  SectionHeading,
  GlowCard,
  RiskBadge,
  ErrorState,
  Skeleton,
  EmptyState,
  PageTransition,
} from "../components/ui";

const DEFAULT_RESOURCES = { cooling_centers: 2, water_tankers: 10, field_workers: 50 };

export default function Interventions() {
  const { location } = useApp();
  const [catalogue, setCatalogue] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState([]);
  const [simResult, setSimResult] = useState(null);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState(null);

  const [budget, setBudget] = useState(500000);
  const [resources, setResources] = useState(DEFAULT_RESOURCES);
  const [optResult, setOptResult] = useState(null);
  const [optBusy, setOptBusy] = useState(false);
  const [optError, setOptError] = useState(null);

  useEffect(() => {
    api
      .interventionTypes()
      .then(setCatalogue)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load interventions."))
      .finally(() => setLoading(false));
  }, []);

  function toggle(type) {
    setSelected((s) => (s.includes(type) ? s.filter((t) => t !== type) : [...s, type]));
    setSimResult(null);
  }

  async function runSimulation() {
    if (!location.zone_id || !selected.length) return;
    setSimBusy(true);
    setSimError(null);
    try {
      const result = await api.simulateInterventions(
        location.zone_id,
        selected.map((type) => ({ type, coverage: 0.6 }))
      );
      setSimResult(result);
    } catch (e) {
      setSimError(e instanceof ApiError ? e.message : "Simulation failed.");
    } finally {
      setSimBusy(false);
    }
  }

  // AI Action Optimizer: given a budget and physical resource inventory,
  // recommends the best feasible mix of interventions -- a genuinely
  // different question from "simulate these specific choices" above.
  // Reuses the same catalogue selection as an optional filter: if the
  // user has picked types above, the optimizer is constrained to those;
  // otherwise it may choose from every supported type.
  async function runOptimizer() {
    if (!location.zone_id) return;
    setOptBusy(true);
    setOptError(null);
    try {
      const result = await api.optimizeInterventions({
        zone_id: location.zone_id,
        budget: Number(budget),
        available_resources: {
          cooling_centers: Number(resources.cooling_centers),
          water_tankers: Number(resources.water_tankers),
          field_workers: Number(resources.field_workers),
        },
        allowed_interventions: selected.length ? selected : null,
      });
      setOptResult(result);
    } catch (e) {
      setOptError(e instanceof ApiError ? e.message : "Optimization failed.");
    } finally {
      setOptBusy(false);
    }
  }

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Phase 14 · Interventions"
        title="Recommended Interventions"
        description="Supported interventions and their modelled effect. Select a few and simulate their combined impact on the chosen zone."
      />

      {error ? (
        <ErrorState message={error} />
      ) : loading ? (
        <Skeleton className="h-64 rounded-2xl" />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {catalogue.interventions.map((it, i) => (
              <motion.button
                key={it.type}
                onClick={() => toggle(it.type)}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className={`text-left rounded-2xl border p-4 transition-colors ${
                  selected.includes(it.type)
                    ? "border-brand-500 bg-brand-700/15"
                    : "border-ink-700 bg-ink-850 hover:border-ink-500"
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Droplet size={15} className="text-brand-400" />
                  <span className="font-medium text-ink-100 text-sm">{it.label}</span>
                </div>
                <p className="text-[11px] text-ink-400 mb-2">{it.assumption}</p>
                <div className="flex items-center justify-between text-[11px] text-ink-500">
                  <span>{it.channel}</span>
                  <span>Max effect: {(it.max_effect * 100).toFixed(0)}%</span>
                </div>
              </motion.button>
            ))}
          </div>

          <div className="space-y-4">
            <GlowCard className="p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-400 mb-3">
                Simulate on selected zone
              </p>
              {!location.zone_id ? (
                <EmptyState icon={MapPinned} title="No zone selected" message="Pick a zone on the map first." />
              ) : (
                <>
                  <p className="text-xs text-ink-400 mb-3">
                    Zone: <span className="text-ink-200">{location.label}</span> ·{" "}
                    {selected.length} intervention{selected.length === 1 ? "" : "s"} selected
                    (60% coverage each)
                  </p>
                  <button
                    onClick={runSimulation}
                    disabled={!selected.length || simBusy}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
                  >
                    <Play size={14} /> {simBusy ? "Simulating…" : "Run simulation"}
                  </button>
                </>
              )}
              {simError && <p className="text-xs text-risk-veryhigh mt-3">{simError}</p>}
            </GlowCard>

            {simResult && (
              <GlowCard className="p-5">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-400 mb-3">
                  Modelled impact
                </p>
                <div className="flex items-center gap-3 mb-3">
                  <RiskBadge level={simResult.baseline.risk_level} size="sm" />
                  <span className="text-ink-500">→</span>
                  <RiskBadge level={simResult.simulation.risk_level} size="sm" />
                </div>
                <p className="text-2xl font-serif font-semibold text-risk-low mb-1">
                  −{simResult.estimated_risk_reduction_percent.toFixed(1)}%
                </p>
                <p className="text-[11px] text-ink-500">Estimated modelled risk reduction</p>
              </GlowCard>
            )}

            <GlowCard className="p-5">
              <div className="flex items-center gap-2 mb-3">
                <Wand2 size={15} className="text-brand-600" />
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-400">
                  AI Action Optimizer
                </p>
              </div>
              {!location.zone_id ? (
                <EmptyState icon={MapPinned} title="No zone selected" message="Pick a zone on the map first." />
              ) : (
                <>
                  <p className="text-[11px] text-ink-400 mb-3">
                    Recommends the best feasible mix of interventions for a
                    budget and resource inventory
                    {selected.length ? " (constrained to your selection above)" : ""}.
                  </p>
                  <label className="text-[11px] text-ink-400">Budget (₹)</label>
                  <input
                    type="number" min={0} value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    className="input mb-2"
                  />
                  <div className="grid grid-cols-3 gap-2 mb-3">
                    {Object.keys(DEFAULT_RESOURCES).map((key) => (
                      <div key={key}>
                        <label className="text-[10px] text-ink-400 capitalize">
                          {key.replace(/_/g, " ")}
                        </label>
                        <input
                          type="number" min={0} value={resources[key]}
                          onChange={(e) => setResources((r) => ({ ...r, [key]: e.target.value }))}
                          className="input text-xs"
                        />
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={runOptimizer}
                    disabled={optBusy}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-brand-700 hover:bg-brand-600 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
                  >
                    <Wand2 size={14} /> {optBusy ? "Optimizing…" : "Recommend optimal plan"}
                  </button>
                </>
              )}
              {optError && <p className="text-xs text-risk-veryhigh mt-3">{optError}</p>}
            </GlowCard>

            {optResult && (
              <GlowCard className="p-5">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-400 mb-3">
                  Recommended plan
                </p>
                <div className="flex items-center gap-3 mb-3">
                  <RiskBadge level={optResult.baseline_risk_level} size="sm" />
                  <span className="text-ink-500">→</span>
                  <RiskBadge level={optResult.optimized_risk_level} size="sm" />
                  <span className="text-sm font-semibold text-risk-low ml-auto">
                    −{optResult.estimated_risk_reduction_percent.toFixed(1)}%
                  </span>
                </div>
                <div className="space-y-2 mb-3">
                  {optResult.recommended_actions.length === 0 ? (
                    <p className="text-xs text-ink-400">No affordable action improved risk further.</p>
                  ) : (
                    optResult.recommended_actions.map((a, i) => (
                      <div key={i} className="rounded-lg bg-ink-800 border border-ink-700 p-2.5 text-xs">
                        <div className="flex justify-between mb-0.5">
                          <span className="text-ink-100 font-medium">{a.type.replace(/_/g, " ")}</span>
                          <span className="text-ink-300">×{a.quantity}</span>
                        </div>
                        <div className="flex justify-between text-ink-400 text-[11px]">
                          <span>Coverage {(a.coverage * 100).toFixed(0)}%</span>
                          <span>₹{a.cost.toLocaleString("en-IN")}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <div className="flex justify-between text-[11px] text-ink-400 border-t border-ink-700 pt-2">
                  <span>Budget used</span>
                  <span className="text-ink-200">
                    ₹{optResult.budget_used.toLocaleString("en-IN")} / ₹{optResult.budget.toLocaleString("en-IN")}
                  </span>
                </div>
              </GlowCard>
            )}
          </div>
        </div>
      )}

      {catalogue && (
        <p className="text-[11px] text-ink-500 mt-6">{catalogue.disclaimer}</p>
      )}
    </PageTransition>
  );
}
