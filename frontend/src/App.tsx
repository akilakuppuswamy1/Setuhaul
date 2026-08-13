import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { AppointmentsPage } from "@/pages/AppointmentsPage";
import { ConcurrencyPage } from "@/pages/ConcurrencyPage";
import { DemoScenariosPage } from "@/pages/DemoScenariosPage";
import { DriverConsolePage } from "@/pages/DriverConsolePage";
import { FacilitySchedulePage } from "@/pages/FacilitySchedulePage";
import { ShipmentsPage } from "@/pages/ShipmentsPage";
import { OpsProvider } from "@/state/OpsProvider";

export default function App() {
  return (
    <OpsProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<DriverConsolePage />} />
            <Route path="/shipments" element={<ShipmentsPage />} />
            <Route path="/appointments" element={<AppointmentsPage />} />
            <Route path="/facility-schedule" element={<FacilitySchedulePage />} />
            <Route path="/demo" element={<DemoScenariosPage />} />
            <Route path="/concurrency" element={<ConcurrencyPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </OpsProvider>
  );
}
