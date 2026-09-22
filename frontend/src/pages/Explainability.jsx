import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { Lightbulb, ArrowUp, ArrowDown } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api, ApiError } from "../lib/api";
import {
  SectionHeading,
  GlowCard,
  RiskBadge,
  ErrorState,
  Skeleton,
  PageTransition,
  EmptyState,
} from "../components/ui";

export default function Explainability() {
  const { location } = useApp();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .hazardForecast(location.latitude, location.longitude, { explain: true, topFactors: 8 })
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load explanation."))
      .finally(() => setLoading(false));
  }, [location]);

  useEffect(load, [load]);

  const explanation = data?.explanation;
  const maxImpact = explanation ? Math.max(...explanation.top_factors.map((f) => f.impact), 1e-9) : 1;

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Phase 11 · Explainability"
        title="Why is this location at risk?"
        description={`SHAP contribution of each feature to the trained model's 3-day forecast for ${location.label}.`}
      />

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <Skeleton className="h-96 rounded-2xl" />
      ) : !explanation ? (
        <EmptyState
          icon={Lightbulb}
          title="Explanation unavailable"
          message="SHAP could not be computed for this prediction (the explainer or trained model may be unavailable)."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <GlowCard className="p-6 lg:col-span-1 flex flex-col gap-4 h-fit">
            <div>
              <p className="text-xs text-ink-400 mb-2">3-day forecast</p>
              <RiskBadge level={data.predicted_category} size="lg" />
            </div>
            <p className="text-sm text-ink-300">{explanation.summary}</p>
            {explanation.base_value != null && (
              <p className="text-[11px] text-ink-500">
                Base value: {explanation.base_value.toFixed(3)} · Explained class:{" "}
                {explanation.explained_class}
              </p>
            )}
            <p className="text-[11px] text-ink-500 border-t border-ink-700 pt-3">{explanation.caveat}</p>
          </GlowCard>

          <GlowCard className="p-6 lg:col-span-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-400 mb-5">
              Top contributing factors
            </p>
            <div className="space-y-4">
              {explanation.top_factors.map((f, i) => (
                <FactorBar key={f.feature} factor={f} maxImpact={maxImpact} delay={i * 0.05} />
              ))}
            </div>
          </GlowCard>
        </div>
      )}
    </PageTransition>
  );
}

function FactorBar({ factor, maxImpact, delay }) {
  const positive = factor.direction === "increases_risk";
  const widthPct = (factor.impact / maxImpact) * 100;
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="font-medium text-ink-200">{factor.feature_label ?? factor.feature}</span>
        <span className={`flex items-center gap-1 ${positive ? "text-risk-veryhigh" : "text-risk-low"}`}>
          {positive ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
          {positive ? "Increased risk" : "Decreased risk"}
        </span>
      </div>
      <div className="h-2.5 rounded-full bg-ink-900 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.6, delay, ease: "easeOut" }}
          className="h-full rounded-full"
          style={{ background: positive ? "#EF4444" : "#10B981" }}
        />
      </div>
      <p className="text-[11px] text-ink-500 mt-1">
        value = {typeof factor.value === "number" ? factor.value.toFixed(2) : factor.value}
      </p>
    </div>
  );
}
