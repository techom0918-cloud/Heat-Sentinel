import { motion } from "framer-motion";
import { riskColor, riskLabel } from "../lib/risk";

/** A card with a subtle animated glow border on hover -- Aceternity/Magic-UI
 * style "spotlight card", built directly with Tailwind + Framer Motion
 * rather than a copy-pasted third-party component, since neither ships as
 * an installable package. */
export function GlowCard({ children, className = "", ...props }) {
  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      className={
        "relative rounded-2xl border border-ink-700 bg-ink-850/80 backdrop-blur-sm " +
        "shadow-[0_1px_0_rgba(255,255,255,0.04)_inset] " +
        "hover:border-brand-600/50 hover:shadow-glow transition-colors duration-300 " +
        className
      }
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function RiskBadge({ level, size = "md" }) {
  const color = riskColor(level);
  const sizes = { sm: "text-[11px] px-2 py-0.5", md: "text-xs px-2.5 py-1", lg: "text-sm px-3 py-1.5" };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold tracking-wide uppercase ${sizes[size]}`}
      style={{ backgroundColor: `${color}1f`, color, border: `1px solid ${color}55` }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full animate-pulseSoft"
        style={{ backgroundColor: color }}
      />
      {riskLabel(level)}
    </span>
  );
}

export function AnimatedNumber({ value, decimals = 1, suffix = "" }) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return <span className="text-ink-400">—</span>;
  }
  return (
    <motion.span
      key={value}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      {Number(value).toFixed(decimals)}
      {suffix}
    </motion.span>
  );
}

export function StatCard({ icon: Icon, label, value, unit, level, sub, loading, error }) {
  return (
    <GlowCard className="p-5 flex flex-col gap-3 min-h-[148px]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-ink-300">
          {Icon && <Icon size={16} strokeWidth={2} />}
          <span className="text-[11px] font-semibold uppercase tracking-wider">{label}</span>
        </div>
        {level && !loading && !error && <RiskBadge level={level} size="sm" />}
      </div>

      {loading ? (
        <Skeleton className="h-9 w-24" />
      ) : error ? (
        <span className="text-sm text-risk-high">Unavailable</span>
      ) : (
        <div className="text-3xl font-semibold text-ink-100 font-serif">
          <AnimatedNumber value={value} />
          {unit && <span className="text-base text-ink-400 ml-1 font-sans">{unit}</span>}
        </div>
      )}

      {sub && !loading && <p className="text-xs text-ink-400 leading-snug">{sub}</p>}
    </GlowCard>
  );
}

export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-lg bg-ink-700/70 ${className}`} />;
}

export function ErrorState({ title = "Something went wrong", message, onRetry }) {
  return (
    <div className="rounded-2xl border border-risk-veryhigh/30 bg-risk-veryhigh/5 p-6 text-center">
      <p className="font-semibold text-risk-veryhigh mb-1">{title}</p>
      <p className="text-sm text-ink-300 mb-3">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-ink-800 border border-ink-600 hover:border-brand-500 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, message, icon: Icon }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-600 p-10 text-center flex flex-col items-center gap-2">
      {Icon && <Icon size={28} className="text-ink-500 mb-1" />}
      <p className="font-semibold text-ink-200">{title}</p>
      {message && <p className="text-sm text-ink-400 max-w-md">{message}</p>}
    </div>
  );
}

export function SectionHeading({ eyebrow, title, description }) {
  return (
    <div className="mb-6">
      {eyebrow && (
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-400 mb-1.5">
          {eyebrow}
        </p>
      )}
      <h2 className="text-2xl font-semibold text-ink-100">{title}</h2>
      {description && <p className="text-sm text-ink-400 mt-1.5 max-w-2xl">{description}</p>}
    </div>
  );
}

/** Subtle hero-region glow, not a distracting particle effect. */
export function Spotlight() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-grid-fade"
    />
  );
}

export function PrototypeTag({ children = "Prototype visualization" }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-full px-2.5 py-1">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
      {children}
    </span>
  );
}

export function PageTransition({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
