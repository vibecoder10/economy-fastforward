"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  LayoutList,
  FileText,
  Users,
  BarChart3,
  Settings,
} from "lucide-react";

const tabs = [
  { href: "/", icon: Home, label: "Home" },
  { href: "/pipeline", icon: LayoutList, label: "Pipeline" },
  { href: "/review", icon: FileText, label: "Script" },
  { href: "/competitors", icon: Users, label: "Compete" },
  { href: "/analytics", icon: BarChart3, label: "Stats" },
  { href: "/settings", icon: Settings, label: "Settings" },
];

export function BottomTabs() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 md:hidden"
      style={{ background: "var(--bg-card)", borderTop: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-around h-16 px-2">
        {tabs.map(({ href, icon: Icon, label }) => {
          const isActive =
            href === "/"
              ? pathname === "/"
              : pathname.startsWith(href.split("?")[0]);

          return (
            <Link
              key={href}
              href={href}
              className="flex flex-col items-center justify-center gap-1 py-2 px-3 rounded-lg transition-colors"
              style={{
                color: isActive ? "var(--amber)" : "var(--text-muted)",
              }}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
