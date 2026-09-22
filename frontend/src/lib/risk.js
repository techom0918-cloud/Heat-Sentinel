export const RISK_COLORS = {
  LOW: "#10B981",
  MODERATE: "#F59E0B",
  HIGH: "#F97316",
  VERY_HIGH: "#EF4444",
  EXTREME: "#B91C1C",
  NONE: "#6B7280",
};

export const RISK_LABELS = {
  LOW: "Low",
  MODERATE: "Moderate",
  HIGH: "High",
  VERY_HIGH: "Very High",
  EXTREME: "Extreme",
  NONE: "Unavailable",
};

export function riskColor(level) {
  return RISK_COLORS[level?.toUpperCase?.()] ?? RISK_COLORS.NONE;
}

export function riskLabel(level) {
  return RISK_LABELS[level?.toUpperCase?.()] ?? level ?? "Unknown";
}

/** 0..1 scale position for a risk level, e.g. for gauges/progress bars. */
export function riskScale(level) {
  const order = ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"];
  const idx = order.indexOf(level?.toUpperCase?.());
  return idx === -1 ? 0 : (idx + 1) / order.length;
}
