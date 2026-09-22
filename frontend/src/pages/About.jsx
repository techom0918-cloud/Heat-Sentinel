import { CheckCircle2, Layers } from "lucide-react";
import { SectionHeading, GlowCard, PageTransition } from "../components/ui";

const COMPLETED = [
  "NCR boundary & 300m x 300m environmental grid (618,373 cells)",
  "Landsat-derived LST, Sentinel-2 NDVI, land cover, and elevation layers",
  "2022-2025 hourly weather pipeline and derived thermal features",
  "Heat Index Category model (LightGBM) with SHAP explainability",
  "FastAPI backend: weather, thermal indices, risk, forecast, geospatial, personalization, alerts, interventions, and authentication",
  "This dashboard (React, Tailwind CSS, Framer Motion, Leaflet)",
];

const PLATFORM = [
  "Live current-conditions Heat Index, WBGT, and UTCI for any NCR location",
  "3-day risk forecast with trend and peak-risk timing",
  "Zone-level spatial risk map with a legend and location popups",
  "Model-contribution explanations for individual risk predictions",
  "Personal risk assessment from a user's own profile and daily exposure",
  "Alert and intervention recommendations tied to current and forecast risk",
];

export default function About() {
  return (
    <PageTransition>
      <SectionHeading
        eyebrow="About"
        title="HeatSentinel"
        description="Extreme Heatwave Early Warning & Human Thermal Stress Index — SIH 2026, PS 26083."
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <GlowCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle2 size={18} className="text-risk-low" />
            <h3 className="font-semibold text-ink-100">Completed</h3>
          </div>
          <ul className="text-sm text-ink-300 space-y-2">
            {COMPLETED.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-risk-low">·</span> {c}
              </li>
            ))}
          </ul>
        </GlowCard>

        <GlowCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Layers size={18} className="text-brand-600" />
            <h3 className="font-semibold text-ink-100">What the platform does</h3>
          </div>
          <ul className="text-sm text-ink-300 space-y-2">
            {PLATFORM.map((p, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-brand-600">·</span> {p}
              </li>
            ))}
          </ul>
        </GlowCard>
      </div>

      <GlowCard className="p-6 mt-5">
        <h3 className="font-semibold text-ink-100 mb-2">Data sources &amp; limitations</h3>
        <ul className="text-xs text-ink-400 space-y-1.5">
          <li>· Weather: point/reanalysis resolution (~10-25 km), not true 300m observations.</li>
          <li>· Heat Index Category model: EXTREME has zero training samples and cannot currently be predicted.</li>
          <li>· SHAP explanations describe model behaviour, not medical or causal claims.</li>
          <li>· Zone demographics on the Heat Risk Map are a synthetic prototype dataset, not census data.</li>
          <li>· This is a prototype decision-support tool, not a medically validated system.</li>
        </ul>
      </GlowCard>
    </PageTransition>
  );
}
