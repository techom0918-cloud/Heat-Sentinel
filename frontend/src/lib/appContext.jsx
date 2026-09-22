import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken as persistToken } from "./api";
import { geometryCentroid } from "./geo";

const AppCtx = createContext(null);

const DEFAULT_LOCATION = {
  label: "New Delhi (default)",
  latitude: 28.6139,
  longitude: 77.209,
  zone_id: null,
};

export function AppProvider({ children }) {
  const [location, setLocation] = useState(DEFAULT_LOCATION);
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setAuthChecked(true);
      return;
    }
    api
      .me()
      .then((me) => setUser(me))
      .catch(() => persistToken(null))
      .finally(() => setAuthChecked(true));
  }, []);

  const login = useCallback(async (email, password) => {
    const result = await api.login(email, password);
    persistToken(result.session_token);
    const me = await api.me();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    persistToken(null);
    setUser(null);
  }, []);

  const selectZone = useCallback((feature) => {
    const [lat, lon] = geometryCentroid(feature.geometry) ?? [
      DEFAULT_LOCATION.latitude,
      DEFAULT_LOCATION.longitude,
    ];
    setLocation({
      label: feature.properties.name ?? feature.properties.zone_id,
      latitude: lat,
      longitude: lon,
      zone_id: feature.properties.zone_id,
    });
  }, []);

  return (
    <AppCtx.Provider
      value={{ location, setLocation, selectZone, user, authChecked, login, logout }}
    >
      {children}
    </AppCtx.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
