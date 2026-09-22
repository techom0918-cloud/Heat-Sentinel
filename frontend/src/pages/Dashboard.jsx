import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { Thermometer, Droplets, Wind, Sun, Flame, ArrowRight, RefreshCw, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { useApp } from "../lib/appContext";
import { api, ApiError } from "../lib/api";
import {
  StatCard,
  RiskBadge,
  GlowCard,
  Spotlight,
  ErrorState,
  Skeleton,
  PageTransition,
} from "../components/ui";

export default function Dashboard() {
  const { location } = useApp();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchedAt, setFetchedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .currentThermal(location.latitude, location.longitude)
      .then((d) => {
        setData(d);
        setFetchedAt(new Date());
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load."))
      .finally(() => setLoading(false));
  }, [location]);

  useEffect(load, [load]);

  // Exact shape of GET /thermal/current -- see backend/app/models/thermal.py
  const t = data?.thermal; // ThermalStressResult: heat_index, heat_index_category, wbgt, utci, ...
  const w = data?.weather; // CurrentWeather: temperature_c, relative_humidity, wind_speed_ms, solar_radiation_wm2
  const band = t?.heat_index_category; // real backend-computed prototype band, not re-derived here

  return (
    <PageTransition>
      <div className="relative">
        <Spotlight />

        <div className="relative mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-400 mb-2">
            Delhi NCR · Extreme Heat Intelligence
          </p>
          <h1 className="text-4xl font-semibold text-ink-100 mb-2">
            How dangerous is the heat, right now?
          </h1>
          <p className="text-ink-400 max-w-xl text-sm">
            Live weather translated into physiological heat stress — Heat Index, WBGT and
            UTCI — for {location.label}.
          </p>
          <div className="flex flex-wrap items-center gap-3 mt-4 text-xs text-ink-400">
            <span className="flex items-center gap-1.5">
              <Clock size={13} />
              {data?.observed_at
                ? <>Weather observed {new Date(data.observed_at).toLocaleString()}</>
                : loading ? "Loading live conditions…" : "No live data"}
              {fetchedAt && <> · fetched {fetchedAt.toLocaleTimeString()}</>}
              {data?.provider && <> · source: {data.provider}</>}
            </span>
            <button
              onClick={load}
              disabled={loading}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-ink-700 bg-ink-850 hover:border-brand-500 text-ink-300 disabled:opacity-50"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
            <span className="text-ink-500">
              {location.latitude.toFixed(4)}°N, {location.longitude.toFixed(4)}°E
            </span>
          </div>
        </div>

        {error ? (
          <ErrorState message={error} onRetry={load} />
        ) : (
          <>
            <GlowCard className="p-6 mb-6 flex flex-col md:flex-row md:items-center gap-6">
              <div className="flex items-center gap-4">
                <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-brand-600 to-brand-900 flex items-center justify-center shrink-0">
                  <Flame size={26} className="text-white" />
                </div>
                <div>
                  <p className="text-xs text-ink-400 mb-1">Current Heat Risk</p>
                  {loading ? (
                    <Skeleton className="h-7 w-28" />
                  ) : (
                    <RiskBadge level={band} size="lg" />
                  )}
                </div>
              </div>
              <div className="md:ml-auto grid grid-cols-3 gap-6 text-sm">
                <MiniStat icon={Thermometer} label="Temp" value={w?.temperature_c} unit="°C" loading={loading} />
                <MiniStat icon={Droplets} label="Humidity" value={w?.relative_humidity} unit="%" loading={loading} />
                <MiniStat icon={Wind} label="Wind" value={w?.wind_speed_ms} unit=" m/s" loading={loading} />
              </div>
            </GlowCard>

            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
              <StatCard
                icon={Flame} label="Heat Index" value={t?.heat_index} unit="°C" level={band}
                loading={loading} sub="Feels-like temperature from air temperature and humidity."
              />
              <StatCard
                icon={Sun} label="WBGT" value={t?.wbgt} unit="°C" loading={loading}
                sub="Wet-bulb globe temperature (shade approximation)."
              />
              <StatCard
                icon={Wind} label="UTCI" value={t?.utci} unit="°C" loading={loading}
                sub="Universal thermal climate index, incl. wind chill of heat."
              />
              <StatCard
                icon={Sun} label="Solar Radiation" value={w?.solar_radiation_wm2} unit=" W/m²" loading={loading}
                sub="Shortwave radiation at this location."
              />
            </div>
          </>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <QuickLink to="/map" title="NCR Heat Risk Map" desc="Explore zone-level risk across Delhi NCR." />
          <QuickLink to="/forecast" title="3-Day Forecast" desc="Where this risk is headed over the next 3 days." />
          <QuickLink to="/explain" title="Why this risk?" desc="SHAP-based explanation of the forecast model." />
        </div>
      </div>
    </PageTransition>
  );
}

function MiniStat({ icon: Icon, label, value, unit, loading }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-ink-400 text-[11px] mb-1">
        <Icon size={12} /> {label}
      </div>
      {loading ? (
        <Skeleton className="h-5 w-14" />
      ) : (
        <p className="text-ink-100 font-medium">
          {value !== null && value !== undefined ? `${Number(value).toFixed(1)}${unit}` : "—"}
        </p>
      )}
    </div>
  );
}

function QuickLink({ to, title, desc }) {
  return (
    <Link to={to}>
      <motion.div
        whileHover={{ y: -2 }}
        className="group rounded-2xl border border-ink-700 bg-ink-850 p-5 h-full hover:border-brand-600/50 transition-colors"
      >
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-ink-100 text-sm">{title}</h3>
          <ArrowRight size={15} className="text-ink-500 group-hover:text-brand-400 group-hover:translate-x-0.5 transition-all" />
        </div>
        <p className="text-xs text-ink-400">{desc}</p>
      </motion.div>
    </Link>
  );
}
