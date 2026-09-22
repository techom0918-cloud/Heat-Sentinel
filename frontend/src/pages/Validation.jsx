import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { FileCheck2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { SectionHeading, GlowCard, ErrorState, Skeleton, EmptyState, PageTransition } from "../components/ui";

// GET /health-data/validation -- a DESCRIPTIVE summary of government-
// reported heat-wave mortality. The backend deliberately does not compute
// skill scores against model output (no matched prediction series exists),
// and this page shows only what that endpoint returns.
export default function Validation() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    api.healthDataValidation()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load validation data."))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Health / Mortality Validation"
        title="Observed Heat-Wave Mortality"
        description="Government-reported heat-wave deaths used as the evidence base for validating heat-risk outputs."
      />

      {error ? <ErrorState message={error} onRetry={load} />
        : loading ? <Skeleton className="h-72 rounded-2xl" />
        : !data || data.observations === 0 ? (
          <EmptyState icon={FileCheck2} title="No observations" message="The health dataset returned no rows." />
        ) : (
          <div className="space-y-5">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                ["Period", data.period],
                ["Observations", data.observations.toLocaleString()],
                ["Regions evaluated", data.regions_evaluated],
                [`High-risk state-years (≥${data.high_risk_threshold} deaths)`, data.high_risk_events],
              ].map(([label, v]) => (
                <GlowCard key={label} className="p-4">
                  <p className="text-[11px] text-ink-400 mb-1">{label}</p>
                  <p className="text-xl font-serif font-semibold text-ink-100">{v}</p>
                </GlowCard>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <GlowCard className="p-6">
                <h3 className="font-semibold text-ink-100 mb-4">Reported deaths by year</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.yearly_totals}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E3DCD0" />
                      <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#6F6A66" }} />
                      <YAxis tick={{ fontSize: 11, fill: "#6F6A66" }} />
                      <Tooltip />
                      <Bar dataKey="total_deaths" name="Reported deaths" fill="#8B004A" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </GlowCard>

              <GlowCard className="p-6">
                <h3 className="font-semibold text-ink-100 mb-4">Top regions by reported deaths</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[11px] uppercase tracking-wide text-ink-400 border-b border-ink-700">
                        <th className="py-2">State</th><th className="py-2 text-right">Deaths</th>
                        <th className="py-2 text-right">Years</th><th className="py-2 text-right">High-risk yrs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_regions.map((r) => (
                        <tr key={r.state} className="border-b border-ink-800 text-ink-200">
                          <td className="py-2">{r.state}</td>
                          <td className="py-2 text-right font-medium">{r.total_deaths.toLocaleString()}</td>
                          <td className="py-2 text-right">{r.years_reporting}</td>
                          <td className="py-2 text-right">{r.high_risk_years}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </GlowCard>
            </div>

            {data.notes?.length > 0 && (
              <GlowCard className="p-6">
                <h3 className="font-semibold text-ink-100 mb-2">Notes on this data</h3>
                <ul className="text-xs text-ink-400 space-y-1.5">
                  {data.notes.map((n, i) => <li key={i}>· {n}</li>)}
                </ul>
              </GlowCard>
            )}
          </div>
        )}
    </PageTransition>
  );
}
