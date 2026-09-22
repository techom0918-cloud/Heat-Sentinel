import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppProvider } from "./lib/appContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import RiskMap from "./pages/RiskMap";
import Forecast from "./pages/Forecast";
import Explainability from "./pages/Explainability";
import Vulnerability from "./pages/Vulnerability";
import RiskCalculator from "./pages/RiskCalculator";
import Validation from "./pages/Validation";
import DecisionIntelligence from "./pages/DecisionIntelligence";
import PersonalRisk from "./pages/PersonalRisk";
import Alerts from "./pages/Alerts";
import Interventions from "./pages/Interventions";
import About from "./pages/About";

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="map" element={<RiskMap />} />
            <Route path="forecast" element={<Forecast />} />
            <Route path="explain" element={<Explainability />} />
            <Route path="vulnerability" element={<Vulnerability />} />
            <Route path="calculator" element={<RiskCalculator />} />
            <Route path="validation" element={<Validation />} />
            <Route path="decision" element={<DecisionIntelligence />} />
            <Route path="personal" element={<PersonalRisk />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="interventions" element={<Interventions />} />
            <Route path="about" element={<About />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
