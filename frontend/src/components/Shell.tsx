"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { BarChart3, BookOpen, FileText, Languages, MessageSquare, Moon, Search, Sun, Telescope } from "lucide-react";
import clsx from "clsx";
import { useI18n } from "@/lib/i18n";
import { api, type Health } from "@/lib/api";
import { Logo } from "./Logo";

const NAV = [
  { href: "/", key: "ask", icon: MessageSquare },
  { href: "/explore", key: "explore", icon: Search },
  { href: "/dossiers", key: "dossiers", icon: FileText },
  { href: "/insights", key: "insights", icon: BarChart3 },
  { href: "/library", key: "library", icon: BookOpen },
  { href: "/observatory", key: "observatory", icon: Telescope },
];

export function Shell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale, theme, setTheme } = useI18n();
  const [health, setHealth] = useState<Health | null>(null);
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = () => api.health().then((h) => { if (alive) { setHealth(h); setApiDown(false); } }).catch(() => { if (alive) setApiDown(true); });
    tick();
    const id = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <div className="flex min-h-screen">
      <aside className="hidden md:flex w-60 shrink-0 flex-col border-r border-border px-4 py-5 gap-6 sticky top-0 h-screen">
        <Link href="/" className="flex items-center gap-3 px-1">
          <Logo size={34} />
          <div>
            <div className="display text-xl leading-none tracking-tight">{t("app.name")}</div>
            <div className="text-[11px] text-faint mt-1">{t("app.tagline")}</div>
          </div>
        </Link>
        <Suspense fallback={<SideNav pathname="" />}><SideNavLive /></Suspense>
        <div className="mt-auto flex flex-col gap-3 text-xs pb-10">
          <div className="flex items-center gap-2">
            <button onClick={() => setLocale(locale === "fr" ? "en" : "fr")} className="btn btn-ghost !px-3 !py-1.5 text-xs" title={t("common.lang")}>
              <Languages size={14} /> {locale.toUpperCase()}
            </button>
            <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="btn btn-ghost !px-3 !py-1.5 text-xs" aria-label="theme">
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
            </button>
          </div>
          <StatusBadge health={health} apiDown={apiDown} />
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="md:hidden flex items-center justify-between px-4 py-3 border-b border-border">
          <Link href="/" className="flex items-center gap-2"><Logo size={26} /><span className="display text-lg">{t("app.name")}</span></Link>
          <div className="flex items-center gap-2">
            <button onClick={() => setLocale(locale === "fr" ? "en" : "fr")} className="btn btn-ghost !px-2 !py-1 text-xs">{locale.toUpperCase()}</button>
            <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="btn btn-ghost !px-2 !py-1 text-xs">{theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}</button>
          </div>
        </header>
        <Suspense fallback={<MobileNav pathname="" />}><MobileNavLive /></Suspense>
        <main className="flex-1 px-4 md:px-10 py-6 md:py-10 max-w-6xl w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}

function StatusBadge({ health, apiDown }: { health: Health | null; apiDown: boolean }) {
  const { t } = useI18n();
  if (apiDown) return <span className="chip chip-danger w-fit">API ✕</span>;
  if (!health) return <span className="chip w-fit">{t("app.loading")}</span>;
  return (
    <div className="flex flex-col gap-1.5">
      <span className={clsx("chip w-fit", health.llm_available ? "chip-ok" : "chip-danger")}>
        <span className="w-1.5 h-1.5 rounded-full bg-current" /> {health.llm_available ? t("app.online") : t("app.offline")}
      </span>
      <span className="text-faint mono text-[10px] leading-tight">
        {health.documents} docs · {health.chunks} chunks · {health.text_backend}
      </span>
    </div>
  );
}

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function SideNav({ pathname }: { pathname: string }) {
  const { t } = useI18n();
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ href, key, icon: Icon }) => (
        <Link key={href} href={href} className={clsx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition", isActive(pathname, href) ? "bg-elev-2 text-accent" : "text-muted hover:bg-elev hover:text-fg")}>
          <Icon size={17} /> {t(`nav.${key}`)}
        </Link>
      ))}
    </nav>
  );
}
function SideNavLive() { return <SideNav pathname={usePathname()} />; }

function MobileNav({ pathname }: { pathname: string }) {
  const { t } = useI18n();
  return (
    <nav className="md:hidden flex gap-1 overflow-x-auto px-3 py-2 border-b border-border">
      {NAV.map(({ href, key, icon: Icon }) => (
        <Link key={href} href={href} className={clsx("chip whitespace-nowrap", isActive(pathname, href) && "chip-accent")}><Icon size={13} />{t(`nav.${key}`)}</Link>
      ))}
    </nav>
  );
}
function MobileNavLive() { return <MobileNav pathname={usePathname()} />; }
