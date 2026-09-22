import { useEffect, useState, useCallback } from "react";
import { BellRing, MapPinned, ShieldCheck } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api, ApiError } from "../lib/api";
import {
  SectionHeading,
  GlowCard,
  RiskBadge,
  ErrorState,
  Skeleton,
  EmptyState,
  PageTransition,
} from "../components/ui";

export default function Alerts() {
  const { location } = useApp();
  const [alert, setAlert] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!location.zone_id) {
      setLoading(false);
      setAlert(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .evaluateAlert(location.zone_id, 3)
      .then(setAlert)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to evaluate alert."))
      .finally(() => setLoading(false));
  }, [location.zone_id]);

  useEffect(load, [load]);

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Phase 14 · Alerts"
        title="Alert Center"
        description="Evaluates whether the selected zone's forecast trajectory warrants an early warning."
      />

      {!location.zone_id ? (
        <EmptyState
          icon={MapPinned}
          title="No zone selected"
          message="Select a zone on the Heat Risk Map first — alerts are evaluated per zone, not per arbitrary coordinate."
        />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <Skeleton className="h-64 rounded-2xl" />
      ) : !alert ? null : alert.alert_required ? (
        <GlowCard className="p-6 border-risk-veryhigh/40">
          <div className="flex items-start gap-4">
            <div className="h-12 w-12 rounded-xl bg-risk-veryhigh/15 flex items-center justify-center shrink-0">
              <BellRing size={22} className="text-risk-veryhigh" />
            </div>
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <RiskBadge level={alert.alert_level} size="lg" />
                <span className="text-xs px-2.5 py-1 rounded-full bg-ink-800 text-ink-300 border border-ink-600">
                  Priority: {alert.priority}
                </span>
              </div>
              <p className="text-sm text-ink-200 mb-3">{alert.reason}</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <Info label="Zone" value={alert.zone_id} />
                <Info label="Current" value={alert.current_risk} />
                <Info label="Forecast peak" value={alert.forecast_peak} />
                <Info label="Peak date" value={alert.peak_date} />
              </div>
            </div>
          </div>
        </GlowCard>
      ) : (
        <GlowCard className="p-6 border-risk-low/30">
          <div className="flex items-center gap-4">
            <div className="h-12 w-12 rounded-xl bg-risk-low/15 flex items-center justify-center shrink-0">
              <ShieldCheck size={22} className="text-risk-low" />
            </div>
            <div>
              <p className="font-semibold text-ink-100 mb-1">No alert required for this zone</p>
              <p className="text-sm text-ink-400">{alert.reason}</p>
            </div>
          </div>
        </GlowCard>
      )}
    </PageTransition>
  );
}

function Info({ label, value }) {
  return (
    <div className="bg-ink-900/60 rounded-lg p-2.5">
      <p className="text-ink-500 mb-0.5">{label}</p>
      <p className="text-ink-100 font-medium">{value}</p>
    </div>
  );
}
