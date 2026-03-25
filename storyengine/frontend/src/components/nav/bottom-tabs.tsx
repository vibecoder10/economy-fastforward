"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  List,
  BarChart3,
  Settings,
  Palette,
} from "lucide-react";

const tabs = [
  { href: "/", icon: LayoutGrid, label: "Home" },
  { href: "/pipeline", icon: List, label: "Queue" },
  { href: "/profile", icon: Palette, label: "Profile" },
  { href: "/analytics", icon: BarChart3, label: "Stats" },
  { href: "/settings", icon: Settings, label: "Settings" },
];

export function BottomTabs() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 md:hidden"
      style={{
        background: "var(--bg-deep)",
        borderTop: "1px solid var(--border-subtle)",
        backdropFilter: "blur(12px)",
      }}
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
                color: isActive ? "var(--turquoise)" : "var(--text-tertiary)",
              }}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium font-body">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
