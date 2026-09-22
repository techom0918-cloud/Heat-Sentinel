import { NavLink } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  Map,
  CloudSun,
  Lightbulb,
  Users,
  Calculator,
  FileCheck2,
  Workflow,
  UserCircle2,
  BellRing,
  ShieldPlus,
  Info,
  Flame,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { useState } from "react";

const NAV = [
  { group: "Overview" },
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { group: "Heat Risk" },
  { to: "/calculator", label: "Risk Calculator", icon: Calculator },
  { to: "/map", label: "Hyperlocal GIS Map", icon: Map },
  { to: "/forecast", label: "Forecast & Trends", icon: CloudSun },
  { group: "Analysis" },
  { to: "/vulnerability", label: "Vulnerability & Health Risk", icon: Users },
  { to: "/explain", label: "Explainable AI", icon: Lightbulb },
  { to: "/validation", label: "Validation", icon: FileCheck2 },
  { group: "Personal" },
  { to: "/personal", label: "Personal Risk", icon: UserCircle2 },
  { group: "Action" },
  { to: "/interventions", label: "Simulator & Optimizer", icon: ShieldPlus },
  { to: "/alerts", label: "Alerts & Warnings", icon: BellRing },
  { to: "/decision", label: "Decision Intelligence", icon: Workflow },
  { group: "" },
  { to: "/about", label: "About HeatSentinel", icon: Info },
];

// This rail intentionally does NOT use the (now light-themed) `ink-*`
// scale for its own surface: the original HeatSentinel design always had
// a dark brand-gradient sidebar rail with white/translucent-white nav
// text, independent of whether the main content area is light or dark.
// That pairing (dark rail + light content) is preserved here explicitly.
export default function Sidebar({ mobileOpen, onCloseMobile }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 lg:hidden"
          onClick={onCloseMobile}
        />
      )}
      <motion.aside
        animate={{ width: collapsed ? 76 : 232 }}
        transition={{ type: "spring", stiffness: 260, damping: 28 }}
        className={`fixed lg:sticky top-0 h-screen z-50 flex flex-col
          bg-gradient-to-b from-brand-800 to-brand-900 border-r border-black/10
          ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
          transition-transform duration-300`}
      >
        <div className="flex items-center gap-2.5 px-4 h-16 border-b border-white/10 shrink-0">
          <div className="h-8 w-8 rounded-lg bg-white/15 flex items-center justify-center shrink-0">
            <Flame size={17} className="text-white" strokeWidth={2.3} />
          </div>
          {!collapsed && (
            <div className="leading-tight overflow-hidden">
              <p className="font-serif font-semibold text-white text-[15px] whitespace-nowrap">
                HeatSentinel
              </p>
              <p className="text-[10px] text-white/55 whitespace-nowrap">NCR Early Warning</p>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-2 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon, end, group }, idx) =>
            group !== undefined ? (
              collapsed ? (
                <div key={`g${idx}`} className="h-px bg-white/10 my-2 mx-2" />
              ) : (
                <p key={`g${idx}`} className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
                  {group}
                </p>
              )
            ) : (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onCloseMobile}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors group ${
                  isActive
                    ? "bg-white/15 text-white border border-white/20"
                    : "text-white/60 hover:bg-white/10 hover:text-white border border-transparent"
                }`
              }
              title={collapsed ? label : undefined}
            >
              <Icon size={17} strokeWidth={2} className="shrink-0" />
              {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </NavLink>
            )
          )}
        </nav>

        <button
          onClick={() => setCollapsed((c) => !c)}
          className="hidden lg:flex items-center justify-center gap-2 mx-2.5 mb-3 py-2 rounded-lg text-white/55 hover:text-white hover:bg-white/10 text-xs border border-white/10"
        >
          {collapsed ? <ChevronsRight size={15} /> : <><ChevronsLeft size={15} /> Collapse</>}
        </button>

        {!collapsed && (
          <div className="mx-2.5 mb-3 p-3 rounded-xl bg-white/10 border border-white/10 text-[11px] text-white/60 leading-relaxed">
            <p className="text-white/90 font-medium mb-0.5">SIH 2026 · PS 26083</p>
            Extreme Heatwave Early Warning &amp; Human Thermal Stress Index
          </div>
        )}
      </motion.aside>
    </>
  );
}
