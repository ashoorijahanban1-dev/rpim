"use client";

import Link from "next/link";
import fa from "@/locales/fa.json";

// Nav items follow the approved mockup; labels come from locales/fa.json
// only (constitution: no hardcoded Persian in components).
const NAV_ITEMS = [
  { href: "/queue", label: fa.nav.queue },
  { href: "/briefs/new", label: fa.nav.new_brief },
  { href: "/brain", label: fa.nav.brain },
  { href: "/trends", label: fa.nav.trends },
  { href: "/studio", label: fa.nav.studio },
  { href: "/publish", label: fa.nav.publish },
  { href: "/channels", label: fa.nav.channels },
  { href: "/reports", label: fa.nav.reports },
  { href: "/insights", label: fa.nav.insights },
  { href: "/export", label: fa.nav.export },
  { href: "/onboarding", label: fa.nav.brand_settings },
] as const;

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar({ pathname }: { pathname: string }) {
  return (
    <aside className="sidebar">
      <div className="logo">
        <b>{fa.nav.logo}</b> <span className="tick">◆</span>
        <small>{fa.nav.subtitle}</small>
      </div>
      <div className="gold-rule" aria-hidden="true" />
      <nav className="side-nav">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(pathname, item.href) ? "active" : undefined}
            aria-current={isActive(pathname, item.href) ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="sys">
        <span>
          <span className="dot" aria-hidden="true" />
          {fa.nav.hitl}
        </span>
      </div>
    </aside>
  );
}
