import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2, ArrowLeft, RotateCcw, AlertTriangle, ShieldCheck, UserCircle2, Info,
} from "lucide-react";
import { api, ApiError, getToken } from "../lib/api";
import { useApp } from "../lib/appContext";
import { SectionHeading, GlowCard, RiskBadge, ErrorState, PageTransition } from "../components/ui";

// Every `value` below is the backend's exact enum string
// (app/models/personalization.py). Nothing here is invented client-side.
const AGE = [
  ["under_18", "Under 18"], ["18_30", "18–30"], ["31_50", "31–50"],
  ["51_65", "51–65"], ["over_65", "65+"],
];
const CLIMATE = [["cold", "Cold"], ["mild", "Mild"], ["warm", "Warm"], ["hot_humid", "Hot / Humid"]];
const TIME_IN_REGION = [
  ["first_3_days", "First 3 days"], ["days_4_7", "4–7 days"],
  ["weeks_1_4", "1–4 weeks"], ["over_a_month", "More than a month"],
];
const COMFORT = [
  ["very_comfortable", "Very comfortable"], ["somewhat_comfortable", "Somewhat comfortable"],
  ["uncomfortable", "Uncomfortable"], ["extremely_uncomfortable", "Extremely uncomfortable"],
];
const DURATION = [
  ["under_30_min", "Less than 30 minutes"], ["min_30_to_2h", "30 minutes – 2 hours"],
  ["h2_to_4", "2 – 4 hours"], ["over_4h", "More than 4 hours"],
];
const WINDOW = [
  ["morning", "Morning (before 11 AM)"], ["midday", "11 AM – 3 PM"],
  ["afternoon", "3 PM – 6 PM"], ["evening_night", "Evening / Night"],
];
const ACTIVITY = [
  ["sightseeing", "Sightseeing / walking"], ["sports", "Sports / exercise"], ["work", "Work"],
  ["shopping", "Shopping"], ["travelling", "Travelling"], ["mostly_indoors", "Mostly indoors"],
];
const FLUIDS = [["yes", "Yes"], ["not_sure", "Not sure"], ["no", "No"]];
const CLOTHING = [
  ["light_loose", "Light, loose clothing"], ["normal", "Normal clothing"], ["heavy_dark", "Heavy / dark clothing"],
];
const TRISTATE = [["yes", "Yes"], ["no", "No"], ["prefer_not_to_say", "Prefer not to say"]];
const YESNO = [[true, "Yes"], [false, "No"]];

// Questionnaire label -> backend symptom codes (from
// PERSONAL_EARLY_WARNING_SYMPTOMS / PERSONAL_RED_FLAG_SYMPTOMS in config).
// Some labels deliberately map to two codes, e.g. "Dizziness or
// light-headedness" -> dizziness + light_headedness.
const SYMPTOMS = [
  ["Unusual thirst", ["unusual_thirst"]],
  ["Muscle cramps", ["muscle_cramps"]],
  ["Headache", ["headache"]],
  ["Heavy sweating", ["heavy_sweating"]],
  ["Dizziness or light-headedness", ["dizziness", "light_headedness"]],
  ["Confusion or unusual behaviour", ["confusion"]],
  ["Weakness or unusual tiredness", ["weakness", "unusual_tiredness"]],
  ["Fainting", ["fainting"]],
  ["Nausea / vomiting", ["nausea", "vomiting"]],
  ["Difficulty staying awake", ["difficulty_staying_awake"]],
];

const COUNTRIES = [
  "India", "Bangladesh", "Nepal", "Sri Lanka", "Pakistan", "United States", "United Kingdom",
  "Canada", "Australia", "Germany", "France", "Japan", "China", "Singapore",
  "United Arab Emirates", "Saudi Arabia", "Russia", "Brazil", "South Africa", "Other",
];

const INITIAL = {
  age_group: "", height_cm: "", weight_kg: "", country_of_residence: "India",
  usual_climate: "mild", time_in_region: "over_a_month", experienced_over_40c: null,
  heat_comfort: "somewhat_comfortable", outdoor_duration: "min_30_to_2h",
  outdoor_window: "morning", activity: "sightseeing", daily_water_litres: "",
  fluids_today: "not_sure", alcohol_today: false, caffeine_today: false, clothing: "normal",
  water_access: true, shade_access: true, hat_access: false, sunscreen_access: false,
  heat_sensitive: "prefer_not_to_say", condition_note: "", symptoms: [], no_symptoms: false,
};

function Section({ n, title, hint, children }) {
  return (
    <GlowCard className="p-5 sm:p-6">
      <div className="flex items-start gap-3 mb-4">
        <span className="h-7 w-7 shrink-0 rounded-full bg-brand-700 text-white text-xs font-bold flex items-center justify-center">
          {n}
        </span>
        <div>
          <h3 className="font-semibold text-ink-100 text-[15px] leading-tight">{title}</h3>
          {hint && <p className="text-xs text-ink-400 mt-0.5">{hint}</p>}
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </GlowCard>
  );
}

function Pills({ options, value, onChange, cols = "sm:grid-cols-3" }) {
  return (
    <div className={`grid grid-cols-2 ${cols} gap-2`}>
      {options.map(([v, label]) => {
        const active = value === v;
        return (
          <button
            key={String(v)} type="button" onClick={() => onChange(v)}
            className={`text-left text-[13px] px-3 py-2.5 rounded-lg border transition-colors ${
              active
                ? "border-brand-600 bg-brand-50 text-brand-800 font-semibold"
                : "border-ink-700 bg-ink-850 text-ink-300 hover:border-brand-400"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function Toggle({ label, checked, onChange }) {
  return (
    <button
      type="button" onClick={() => onChange(!checked)}
      className={`flex items-center gap-2 text-[13px] px-3 py-2.5 rounded-lg border transition-colors ${
        checked ? "border-brand-600 bg-brand-50 text-brand-800 font-semibold"
                : "border-ink-700 bg-ink-850 text-ink-300 hover:border-brand-400"
      }`}
    >
      <span className={`h-4 w-4 rounded border flex items-center justify-center text-[10px] ${
        checked ? "bg-brand-700 border-brand-700 text-white" : "border-ink-500"}`}>
        {checked ? "✓" : ""}
      </span>
      {label}
    </button>
  );
}

const Label = ({ children }) => <p className="text-xs font-medium text-ink-300 mb-2">{children}</p>;

export default function PersonalRisk() {
  const { location, user } = useApp();
  const [form, setForm] = useState(INITIAL);
  const [errors, setErrors] = useState({});
  const [stage, setStage] = useState(null); // progress text while submitting
  const [submitError, setSubmitError] = useState(null);
  const [result, setResult] = useState(null);

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  // Prefill from any profile/health data already saved for this user.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const merged = {};
      try {
        const p = await api.getProfile();
        ["age_group", "height_cm", "weight_kg", "country_of_residence", "usual_climate",
          "time_in_region", "experienced_over_40c", "heat_comfort"].forEach((k) => {
          if (p[k] !== null && p[k] !== undefined) merged[k] = p[k];
        });
      } catch { /* 404 = no saved profile yet; that's fine */ }
      try {
        const h = await api.getHealth();
        if (h.heat_sensitive) merged.heat_sensitive = h.heat_sensitive;
        if (h.condition_note) merged.condition_note = h.condition_note;
      } catch { /* none saved yet */ }
      if (!cancelled && Object.keys(merged).length) setForm((f) => ({ ...f, ...merged }));
    })();
    return () => { cancelled = true; };
  }, [user]);

  const bmi = useMemo(() => {
    const h = Number(form.height_cm), w = Number(form.weight_kg);
    if (!h || !w) return null;
    return w / ((h / 100) ** 2);
  }, [form.height_cm, form.weight_kg]);

  function validate() {
    const e = {};
    if (!form.age_group) e.age_group = "Please select your age group.";
    if (form.height_cm && (Number(form.height_cm) <= 0 || Number(form.height_cm) > 260))
      e.height_cm = "Height must be between 1 and 260 cm.";
    if (form.weight_kg && (Number(form.weight_kg) <= 0 || Number(form.weight_kg) > 400))
      e.weight_kg = "Weight must be between 1 and 400 kg.";
    if (form.experienced_over_40c === null) e.experienced_over_40c = "Please answer yes or no.";
    if (form.daily_water_litres && (Number(form.daily_water_litres) < 0 || Number(form.daily_water_litres) > 15))
      e.daily_water_litres = "Enter a daily intake between 0 and 15 litres.";
    if (!form.no_symptoms && form.symptoms.length === 0)
      e.symptoms = "Select any symptoms, or choose “None of these”.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit() {
    if (!validate()) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    setSubmitError(null);
    try {
      setStage("Saving your profile…");
      await api.putProfile({
        user_id: "demo_user_001", // overridden server-side by the signed-in identity
        age_group: form.age_group,
        height_cm: form.height_cm ? Number(form.height_cm) : null,
        weight_kg: form.weight_kg ? Number(form.weight_kg) : null,
        country_of_residence: form.country_of_residence || null,
        usual_climate: form.usual_climate,
        time_in_region: form.time_in_region,
        experienced_over_40c: form.experienced_over_40c,
        heat_comfort: form.heat_comfort,
      });

      setStage("Saving health information…");
      await api.putHealth({
        user_id: "demo_user_001",
        heat_sensitive: form.heat_sensitive,
        condition_note: form.heat_sensitive === "yes" && form.condition_note.trim()
          ? form.condition_note.trim() : null,
        status: form.heat_sensitive === "yes" ? "active" : "unknown",
      });

      setStage("Saving today's exposure…");
      const symptomCodes = form.no_symptoms
        ? []
        : [...new Set(SYMPTOMS.filter(([label]) => form.symptoms.includes(label)).flatMap(([, c]) => c))];
      await api.putAssessment({
        user_id: "demo_user_001",
        outdoor_duration: form.outdoor_duration,
        outdoor_window: form.outdoor_window,
        activity: form.activity,
        daily_water_litres: form.daily_water_litres ? Number(form.daily_water_litres) : null,
        fluids_today: form.fluids_today,
        alcohol_today: form.alcohol_today,
        caffeine_today: form.caffeine_today,
        clothing: form.clothing,
        water_access: form.water_access,
        shade_access: form.shade_access,
        hat_access: form.hat_access,
        sunscreen_access: form.sunscreen_access,
        current_symptoms: symptomCodes,
      });

      setStage("Calculating your heat risk with live conditions…");
      const res = await api.personalRisk({
        user_id: "demo_user_001",
        latitude: location.latitude,
        longitude: location.longitude,
      });
      setResult(res);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Could not complete the assessment.");
    } finally {
      setStage(null);
    }
  }

  function toggleSymptom(label) {
    setForm((f) => ({
      ...f,
      no_symptoms: false,
      symptoms: f.symptoms.includes(label) ? f.symptoms.filter((s) => s !== label) : [...f.symptoms, label],
    }));
  }

  if (result) {
    return <ResultView result={result} location={location} onUpdate={() => setResult(null)} />;
  }

  const signedIn = Boolean(user && getToken());

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Personal Risk · Assessment"
        title="Your Personal Heat Risk Assessment"
        description="Twelve short sections. Your answers are combined with live heat conditions to estimate your personal heat risk. This is guidance, not a medical diagnosis."
      />

      <div className={`mb-5 rounded-xl border px-4 py-3 text-sm flex items-start gap-2 ${
        signedIn ? "border-risk-low/40 bg-risk-low/10 text-ink-200" : "border-amber-400/50 bg-amber-50 text-ink-200"}`}>
        <UserCircle2 size={17} className="mt-0.5 shrink-0" />
        {signedIn
          ? <span>Signed in as <strong>{user.email}</strong> — this assessment is saved to your own account.</span>
          : <span>You are not signed in. Use <strong>Sign in</strong> (top right) to save this assessment to your own account; otherwise it is stored under the shared demo profile.</span>}
      </div>

      {Object.keys(errors).length > 0 && (
        <div className="mb-5 rounded-xl border border-risk-veryhigh/40 bg-red-50 px-4 py-3 text-sm text-risk-veryhigh">
          Please fix the highlighted questions before submitting.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Section n={1} title="Age">
          <Pills options={AGE} value={form.age_group} onChange={set("age_group")} />
          {errors.age_group && <p className="text-xs text-risk-veryhigh">{errors.age_group}</p>}
        </Section>

        <Section n={2} title="Height & weight" hint="Used to calculate BMI.">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Height (cm)</Label>
              <input type="number" className="input" value={form.height_cm} placeholder="e.g. 170"
                onChange={(e) => set("height_cm")(e.target.value)} />
              {errors.height_cm && <p className="text-xs text-risk-veryhigh mt-1">{errors.height_cm}</p>}
            </div>
            <div>
              <Label>Weight (kg)</Label>
              <input type="number" className="input" value={form.weight_kg} placeholder="e.g. 68"
                onChange={(e) => set("weight_kg")(e.target.value)} />
              {errors.weight_kg && <p className="text-xs text-risk-veryhigh mt-1">{errors.weight_kg}</p>}
            </div>
          </div>
          {bmi && (
            <p className="text-sm text-ink-300">
              BMI: <strong className="text-ink-100">{bmi.toFixed(1)}</strong>
            </p>
          )}
        </Section>

        <Section n={3} title="Country of residence">
          <div>
            <Label>Country</Label>
            <select className="input" value={form.country_of_residence}
              onChange={(e) => set("country_of_residence")(e.target.value)}>
              {COUNTRIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <Label>Usual climate where you live</Label>
            <Pills options={CLIMATE} value={form.usual_climate} onChange={set("usual_climate")} cols="sm:grid-cols-4" />
          </div>
        </Section>

        <Section n={4} title="How long have you been in Delhi-NCR?">
          <Pills options={TIME_IN_REGION} value={form.time_in_region} onChange={set("time_in_region")} cols="sm:grid-cols-2" />
        </Section>

        <Section n={5} title="Previous heat exposure">
          <div>
            <Label>Have you previously experienced temperatures above 40°C?</Label>
            <Pills options={YESNO} value={form.experienced_over_40c} onChange={set("experienced_over_40c")} cols="sm:grid-cols-2" />
            {errors.experienced_over_40c && <p className="text-xs text-risk-veryhigh mt-1">{errors.experienced_over_40c}</p>}
          </div>
          <div>
            <Label>How comfortable are you currently in Delhi's heat?</Label>
            <Pills options={COMFORT} value={form.heat_comfort} onChange={set("heat_comfort")} cols="sm:grid-cols-2" />
          </div>
        </Section>

        <Section n={6} title="Outdoor time today">
          <Pills options={DURATION} value={form.outdoor_duration} onChange={set("outdoor_duration")} cols="sm:grid-cols-2" />
        </Section>

        <Section n={7} title="Main outdoor time">
          <Pills options={WINDOW} value={form.outdoor_window} onChange={set("outdoor_window")} cols="sm:grid-cols-2" />
        </Section>

        <Section n={8} title="Outdoor activity">
          <Pills options={ACTIVITY} value={form.activity} onChange={set("activity")} />
        </Section>

        <Section n={9} title="Hydration & habits">
          <div>
            <Label>Daily water intake (litres)</Label>
            <input type="number" step="0.1" className="input" value={form.daily_water_litres} placeholder="e.g. 2.5"
              onChange={(e) => set("daily_water_litres")(e.target.value)} />
            {errors.daily_water_litres && <p className="text-xs text-risk-veryhigh mt-1">{errors.daily_water_litres}</p>}
          </div>
          <div>
            <Label>Have you had enough fluids today?</Label>
            <Pills options={FLUIDS} value={form.fluids_today} onChange={set("fluids_today")} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Alcohol today?</Label>
              <Pills options={YESNO} value={form.alcohol_today} onChange={set("alcohol_today")} cols="grid-cols-2" />
            </div>
            <div>
              <Label>A lot of caffeine today?</Label>
              <Pills options={YESNO} value={form.caffeine_today} onChange={set("caffeine_today")} cols="grid-cols-2" />
            </div>
          </div>
        </Section>

        <Section n={10} title="Clothing & protection">
          <div>
            <Label>What will you be wearing outdoors?</Label>
            <Pills options={CLOTHING} value={form.clothing} onChange={set("clothing")} />
          </div>
          <div>
            <Label>Will you have access to:</Label>
            <div className="grid grid-cols-2 gap-2">
              <Toggle label="Water" checked={form.water_access} onChange={set("water_access")} />
              <Toggle label="Shade / AC" checked={form.shade_access} onChange={set("shade_access")} />
              <Toggle label="Hat / umbrella" checked={form.hat_access} onChange={set("hat_access")} />
              <Toggle label="Sunscreen" checked={form.sunscreen_access} onChange={set("sunscreen_access")} />
            </div>
          </div>
        </Section>

        <Section n={11} title="Health conditions & other risk factors"
          hint="Do you have any condition or take any medication that may make you more sensitive to heat?">
          <Pills options={TRISTATE} value={form.heat_sensitive} onChange={set("heat_sensitive")} />
          {form.heat_sensitive === "yes" && (
            <div>
              <Label>Optional — describe it (not required)</Label>
              <textarea className="input min-h-[72px]" maxLength={500} value={form.condition_note}
                placeholder="Optional"
                onChange={(e) => set("condition_note")(e.target.value)} />
            </div>
          )}
          <p className="text-[11px] text-ink-400 flex gap-1.5">
            <Info size={13} className="shrink-0 mt-0.5" />
            Examples: heart or kidney disease, diabetes, pregnancy, or medicines such as diuretics or
            some blood-pressure and mental-health medications. You never have to share details.
          </p>
        </Section>

        <Section n={12} title="Current symptoms" hint="Select all that apply right now.">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {SYMPTOMS.map(([label]) => (
              <Toggle key={label} label={label} checked={form.symptoms.includes(label)}
                onChange={() => toggleSymptom(label)} />
            ))}
            <Toggle label="None of these" checked={form.no_symptoms}
              onChange={(v) => setForm((f) => ({ ...f, no_symptoms: v, symptoms: v ? [] : f.symptoms }))} />
          </div>
          {errors.symptoms && <p className="text-xs text-risk-veryhigh">{errors.symptoms}</p>}
        </Section>
      </div>

      <div className="mt-6 flex flex-col items-center gap-3">
        {submitError && (
          <div className="w-full max-w-xl"><ErrorState title="Assessment failed" message={submitError} onRetry={submit} /></div>
        )}
        <button onClick={submit} disabled={Boolean(stage)}
          className="btn-primary px-8 py-3 text-base flex items-center gap-2">
          {stage && <Loader2 size={17} className="animate-spin" />}
          {stage ?? "Get My Heat Risk Result"}
        </button>
        <p className="text-[11px] text-ink-400">
          Location used for live conditions: <span className="text-ink-200">{location.label}</span>
        </p>
      </div>
    </PageTransition>
  );
}

const THERMAL_LABELS = { heat_index: "Heat Index", wbgt: "WBGT", utci: "UTCI", temperature_c: "Temperature" };

function ResultView({ result, location, onUpdate }) {
  const thermalEntries = Object.entries(result.thermal ?? {}).filter(([, v]) => v !== null && v !== undefined);
  return (
    <PageTransition>
      <SectionHeading eyebrow="Personal Risk · Result" title="Your Heat Risk"
        description={`Based on your answers and live conditions at ${location.label}.`} />

      <AnimatePresence>
        {result.safety_notice && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
            className={`mb-5 rounded-2xl border p-4 flex gap-3 ${
              result.safety_notice.urgent ? "border-risk-extreme bg-red-50" : "border-amber-400 bg-amber-50"}`}>
            <AlertTriangle size={20} className={result.safety_notice.urgent ? "text-risk-extreme" : "text-amber-600"} />
            <div>
              <p className="font-semibold text-ink-100 mb-0.5">
                {result.safety_notice.urgent ? "Urgent — act now" : "Early warning signs"}
              </p>
              <p className="text-sm text-ink-200">{result.safety_notice.message}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <GlowCard className="p-6 lg:col-span-1">
          <p className="text-xs text-ink-400 mb-2">Personalised heat risk</p>
          <div className="flex items-center gap-3 mb-4">
            <RiskBadge level={result.risk_level} size="lg" />
            <span className="text-3xl font-serif font-semibold text-ink-100">
              {(result.personalised_risk_score * 100).toFixed(0)}%
            </span>
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-ink-400">Environmental risk</span>
              <RiskBadge level={result.environmental_risk_level} size="sm" /></div>
            <div className="flex justify-between"><span className="text-ink-400">Personal vulnerability</span>
              <span className="font-semibold text-ink-100">{(result.personal_vulnerability_score * 100).toFixed(0)}%</span></div>
          </div>
          {thermalEntries.length > 0 && (
            <div className="grid grid-cols-3 gap-2 mt-5">
              {thermalEntries.map(([k, v]) => (
                <div key={k} className="rounded-lg bg-ink-800 border border-ink-700 p-2 text-center">
                  <p className="text-[10px] text-ink-400">{THERMAL_LABELS[k] ?? k}</p>
                  <p className="text-sm font-semibold text-ink-100">{Number(v).toFixed(1)}°C</p>
                </div>
              ))}
            </div>
          )}
        </GlowCard>

        <GlowCard className="p-6 lg:col-span-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-300 mb-3">Personal risk factors</h4>
          <div className="space-y-3">
            {result.factors.map((f) => (
              <div key={f.key}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-ink-200 font-medium">{f.label}</span>
                  <span className="text-ink-400">contributes {(f.contribution * 100).toFixed(1)}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-ink-700 overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${f.score * 100}%` }}
                    transition={{ duration: 0.5 }} className="h-full bg-brand-600 rounded-full" />
                </div>
                <p className="text-[11px] text-ink-400 mt-0.5">{f.detail}</p>
              </div>
            ))}
          </div>
          {result.top_drivers?.length > 0 && (
            <p className="text-xs text-ink-300 mt-4">
              <strong>Main contributors:</strong> {result.top_drivers.join(", ")}
            </p>
          )}
        </GlowCard>

        <GlowCard className="p-6 lg:col-span-3">
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck size={17} className="text-risk-low" />
            <h4 className="font-semibold text-ink-100">What you should do now</h4>
          </div>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {result.recommendations.map((r, i) => (
              <li key={i} className="text-sm text-ink-200 rounded-lg bg-ink-800 border border-ink-700 px-3 py-2">{r}</li>
            ))}
          </ul>
        </GlowCard>
      </div>

      <div className="flex flex-wrap gap-3 mt-6">
        <Link to="/" className="btn-ghost flex items-center gap-2"><ArrowLeft size={15} /> Back to Dashboard</Link>
        <button onClick={onUpdate} className="btn-primary flex items-center gap-2"><RotateCcw size={15} /> Update Assessment</button>
      </div>

      <p className="text-[11px] text-ink-400 mt-6">{result.disclaimer}</p>
    </PageTransition>
  );
}
