import { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import LoginModal from "./LoginModal";

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-ink-950">
      <Sidebar mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

      <div className="flex-1 min-w-0 flex flex-col">
        <Topbar onOpenMobile={() => setMobileOpen(true)} onOpenLogin={() => setLoginOpen(true)} />
        <main className="flex-1 p-4 lg:p-8 max-w-[1400px] w-full mx-auto">
          <Outlet />
        </main>
      </div>

      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
    </div>
  );
}
