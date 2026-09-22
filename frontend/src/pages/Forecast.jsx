import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Thermometer, Droplets, Wind, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api, ApiError } from "../lib/api";
import { riskColor, riskLabel } from "../lib/risk";
import {
  SectionHeading,
  GlowCard,
  RiskBadge,
  ErrorState,
  Skeleton,
  PageTransition,
} from "../components/ui";

const TREND_ICON = { WORSENING: TrendingUp, IMPROVING: TrendingDown, STABLE: Minus };
const METHOD_LABEL = {
  OBSERVED: "Observed today",
  NWP_DERIVED: "From weather forecast",
  ML_MODEL: "Trained ML model",
};

export default function Forecast() {
  const { location } = useApp();
  const [trajectory, setTrajectory] = useState(null);
  const [weather, setWeather] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.riskTrajectory(location.latitude, location.longitude, 3),
      api.weatherForecast(location.latitude, location.longitude, 3),
    ])
      .then(([t, w]) => {
        setTrajectory(t);
        setWeather(w);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load forecast."))
      .finally(() => setLoading(false));
  }, [location]);

  useEffect(load, [load]);

  const weatherByDate = new Map((weather?.forecast ?? []).map((d) => [d.date, d]));
  const TrendIcon = trajectory ? TREND_ICON[trajectory.trend] ?? Minus : Minus;

  const chartData = (trajectory?.forecast ?? []).map((d) => ({
    date: d.target_date.slice(5),
    heatIndex: d.heat_index_max,
  }));

  return (
    <PageTransition>
      <SectionHeading
        eyebrow="Phase 12 · Forecast"
        title="3-Day Heat Trajectory"
        description={`Risk trajectory for ${location.label}, combining observed conditions, weather forecast and the trained hazard model.`}
      />

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-52 rounded-2xl" />
          ))}
        </div>
      ) : (
        <>
          <GlowCard className="p-5 mb-6 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <TrendIcon size={18} className="text-brand-400" />
              <span className="text-sm text-ink-200">
                Trend: <span className="font-semibold text-ink-100">{trajectory.trend}</span>
              </span>
            </div>
            <div className="text-sm text-ink-300">
              Peak: <RiskBadge level={trajectory.peak_risk} size="sm" />{" "}
              <span className="text-ink-400">on {trajectory.peak_date}</span>
            </div>
            <div className="ml-auto text-xs text-ink-500">
              Based on observations through {trajectory.based_on}
            </div>
          </GlowCard>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {trajectory.forecast.map((day, i) => {
              const w = weatherByDate.get(day.target_date);
              return (
                <motion.div
                  key={day.target_date}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.08 }}
                >
                  <GlowCard className="p-5">
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <p className="text-xs text-ink-400">
                          Day {day.days_ahead === 0 ? "0 (today)" : `+${day.days_ahead}`}
                        </p>
                        <p className="font-semibold text-ink-100">{day.target_date}</p>
                      </div>
                      <RiskBadge level={day.risk_level} size="sm" />
                    </div>

                    <div
                      className="text-3xl font-serif font-semibold mb-1"
                      style={{ color: riskColor(day.risk_level) }}
                    >
                      {day.heat_index_max.toFixed(1)}°C
                    </div>
                    <p className="text-[11px] text-ink-500 mb-4">Peak Heat Index</p>

                    <div className="grid grid-cols-3 gap-2 text-xs text-ink-300 mb-4">
                      <WeatherMini icon={Thermometer} value={w?.temperature_max_c} unit="°C" />
                      <WeatherMini icon={Droplets} value={w?.relative_humidity_at_max_temp} unit="%" />
                      <WeatherMini icon={Wind} value={w?.wind_speed_max_ms} unit=" m/s" />
                    </div>

                    <div className="pt-3 border-t border-ink-700 flex items-center justify-between">
                      <span className="text-[11px] text-ink-400">{METHOD_LABEL[day.method]}</span>
                      {day.confidence != null && (
                        <span className="text-[11px] text-ink-500">
                          {(day.confidence * 100).toFixed(0)}% confidence
                        </span>
                      )}
                    </div>
                  </GlowCard>
                </motion.div>
              );
            })}
          </div>

          <GlowCard className="p-5 mb-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-400 mb-4">
              Heat Index trend
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData}>
                <CartesianGrid stroke="#26262D" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="#6B6B76" fontSize={12} />
                <YAxis stroke="#6B6B76" fontSize={12} unit="°C" />
                <Tooltip
                  contentStyle={{ background: "#16161A", border: "1px solid #26262D", borderRadius: 10 }}
                  labelStyle={{ color: "#DEDEE3" }}
                />
                <Line type="monotone" dataKey="heatIndex" stroke="#D6336C" strokeWidth={2.5} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </GlowCard>

          {trajectory.limitations?.length > 0 && (
            <div className="text-xs text-ink-500 space-y-1">
              {trajectory.limitations.map((l, i) => (
                <p key={i}>· {l}</p>
              ))}
            </div>
          )}
        </>
      )}
    </PageTransition>
  );
}

function WeatherMini({ icon: Icon, value, unit }) {
  return (
    <div className="flex flex-col items-center gap-1 bg-ink-900/60 rounded-lg py-2">
      <Icon size={13} className="text-ink-400" />
      <span>{value != null ? `${value.toFixed(0)}${unit}` : "—"}</span>
    </div>
  );
}
