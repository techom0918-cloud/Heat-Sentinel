import { useEffect, useState } from "react";
import { Menu, MapPin, Clock, LogIn, LogOut, User } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api } from "../lib/api";

export default function Topbar({ onOpenMobile, onOpenLogin }) {
  const { location, user, logout } = useApp();
  const [now, setNow] = useState(new Date());
  const [apiUp, setApiUp] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000 * 30);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then(() => alive && setApiUp(true))
      .catch(() => alive && setApiUp(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <header className="sticky top-0 z-30 h-16 flex items-center gap-4 px-4 lg:px-6 bg-ink-900/85 backdrop-blur-md border-b border-ink-700">
      <button onClick={onOpenMobile} className="lg:hidden text-ink-300">
        <Menu size={22} />
      </button>

      <div className="flex items-center gap-2 text-sm text-ink-200 min-w-0">
        <MapPin size={15} className="text-brand-400 shrink-0" />
        <span className="truncate font-medium">{location.label}</span>
      </div>

      <div className="hidden md:flex items-center gap-1.5 text-xs text-ink-400">
        <Clock size={13} />
        {now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} IST
      </div>

      <div className="hidden md:flex items-center gap-1.5 text-xs ml-2">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            apiUp === null ? "bg-ink-500" : apiUp ? "bg-risk-low" : "bg-risk-veryhigh"
          }`}
        />
        <span className="text-ink-400">
          {apiUp === null ? "Checking backend…" : apiUp ? "Backend live" : "Backend unreachable"}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3">
        {user ? (
          <div className="flex items-center gap-2">
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-ink-300">
              <User size={14} />
              {user.email}
            </div>
            <button
              onClick={logout}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-ink-600 text-ink-300 hover:text-ink-100 hover:border-brand-500 transition-colors"
            >
              <LogOut size={13} /> Sign out
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenLogin}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-brand-700 hover:bg-brand-600 text-white transition-colors"
          >
            <LogIn size={13} /> Sign in
          </button>
        )}
      </div>
    </header>
  );
}
