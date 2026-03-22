"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, ListVideo, CheckCircle, Activity, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

const links = [
  { href: "/", label: "Home", icon: Home },
  { href: "/pipeline", label: "Pipeline", icon: ListVideo },
  { href: "/review", label: "Review", icon: CheckCircle },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-40 hidden h-screen w-60 flex-col border-r border-[var(--border)] bg-[var(--surface)] md:flex">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 px-5">
        <div className="h-7 w-7 rounded-lg bg-[var(--accent)]" />
        <span className="text-lg font-semibold tracking-tight">StoryEngine</span>
      </div>

      {/* Nav links */}
      <nav className="mt-4 flex flex-1 flex-col gap-1 px-3">
        {links.map((link) => {
          const isActive = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          const Icon = link.icon;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-[var(--accent)]/10 text-[var(--accent)]"
                  : "text-[var(--text-secondary)] hover:bg-white/5 hover:text-[var(--text-primary)]"
              )}
            >
              <Icon size={18} />
              {link.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-[var(--border)] px-5 py-3">
        <p className="text-xs text-[var(--text-secondary)]">Economy FastForward</p>
      </div>
    </aside>
  );
}
