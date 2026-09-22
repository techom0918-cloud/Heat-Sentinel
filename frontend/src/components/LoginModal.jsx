import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useApp } from "../lib/appContext";
import { api } from "../lib/api";

export default function LoginModal({ open, onClose }) {
  const { login } = useApp();
  const [mode, setMode] = useState("login"); // login | signup
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pet, setPet] = useState("");
  const [city, setCity] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        await api.signup(email, password, [
          { question_index: 0, answer: pet },
          { question_index: 2, answer: city },
        ]);
      }
      await login(email, password);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: "spring", stiffness: 340, damping: 28 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-2xl border border-ink-700 bg-ink-850 p-6 relative"
          >
            <button onClick={onClose} className="absolute top-4 right-4 text-ink-400 hover:text-ink-100">
              <X size={18} />
            </button>
            <h3 className="font-serif text-xl text-ink-100 mb-1">
              {mode === "login" ? "Sign in" : "Create account"}
            </h3>
            <p className="text-xs text-ink-400 mb-5">
              Needed for Personal Risk — otherwise it uses a standalone demo profile.
            </p>

            <form onSubmit={submit} className="space-y-3">
              <Field label="Email">
                <input
                  type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  className="input" placeholder="you@example.com"
                />
              </Field>
              <Field label="Password">
                <input
                  type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                  className="input" placeholder="••••••••" minLength={8}
                />
              </Field>

              {mode === "signup" && (
                <>
                  <Field label="Security answer — pet's name">
                    <input value={pet} onChange={(e) => setPet(e.target.value)} required className="input" />
                  </Field>
                  <Field label="Security answer — city">
                    <input value={city} onChange={(e) => setCity(e.target.value)} required className="input" />
                  </Field>
                </>
              )}

              {error && <p className="text-xs text-risk-veryhigh">{error}</p>}

              <button
                disabled={busy}
                className="w-full py-2.5 rounded-lg bg-brand-700 hover:bg-brand-600 text-white text-sm font-semibold transition-colors disabled:opacity-50"
              >
                {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account & sign in"}
              </button>
            </form>

            <button
              onClick={() => setMode(mode === "login" ? "signup" : "login")}
              className="w-full text-center text-xs text-ink-400 hover:text-brand-400 mt-4"
            >
              {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-[11px] font-medium text-ink-400 mb-1">{label}</span>
      {children}
    </label>
  );
}
