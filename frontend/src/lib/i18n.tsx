"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import fr from "@/messages/fr.json";
import en from "@/messages/en.json";

export type Locale = "fr" | "en";
type Messages = typeof fr;
const catalogs: Record<Locale, Messages> = { fr, en: en as Messages };

type Ctx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (path: string) => string;
  tl: (path: string) => string[];
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
};

const I18nContext = createContext<Ctx | null>(null);

function get(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, k) => (acc && typeof acc === "object" ? (acc as Record<string, unknown>)[k] : undefined), obj);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("fr");
  const [theme, setThemeState] = useState<"dark" | "light">("dark");

  useEffect(() => {
    try {
      const l = localStorage.getItem("jazzar.locale");
      if (l === "fr" || l === "en") setLocaleState(l);
      else if (navigator.language.toLowerCase().startsWith("en")) setLocaleState("en");
      const th = localStorage.getItem("jazzar.theme");
      if (th === "light" || th === "dark") setThemeState(th);
    } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dataset.theme = theme;
  }, [locale, theme]);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try { localStorage.setItem("jazzar.locale", l); } catch {}
  }, []);
  const setTheme = useCallback((th: "dark" | "light") => {
    setThemeState(th);
    try { localStorage.setItem("jazzar.theme", th); } catch {}
  }, []);

  const value = useMemo<Ctx>(() => ({
    locale, setLocale, theme, setTheme,
    t: (path) => {
      const v = get(catalogs[locale], path) ?? get(catalogs.fr, path);
      return typeof v === "string" ? v : path;
    },
    tl: (path) => {
      const v = get(catalogs[locale], path) ?? get(catalogs.fr, path);
      return Array.isArray(v) ? (v as string[]) : [];
    },
  }), [locale, setLocale, theme, setTheme]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
