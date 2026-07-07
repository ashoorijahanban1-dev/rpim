"use client";

import { usePathname } from "next/navigation";
import Sidebar from "@/components/Sidebar";

// Auth pages and the landing page render as centered luxury cards,
// outside the app shell. Everything else gets the sidebar shell.
const BARE_ROUTES = new Set(["/", "/login", "/register"]);

export default function ClientShell({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();

  if (BARE_ROUTES.has(pathname)) {
    return <div className="auth-ground">{children}</div>;
  }

  return (
    <div className="shell">
      <Sidebar pathname={pathname} />
      <div className="shell-content">{children}</div>
    </div>
  );
}
