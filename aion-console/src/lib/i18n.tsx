"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { pt } from "./translations";
import { en } from "./translations";

export type Locale = "pt" | "en";

type Translations = typeof pt;

const STORAGE_KEY = "aion-locale";

const I18nContext = createContext<{
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string) => string;
}>({
  locale: "pt",
  setLocale: () => {},
  t: (key) => key,
});

function resolve(obj: Record<string, unknown>, key: string): string {
  return key.split(".").reduce<unknown>((cur, k) => {
    if (cur && typeof cur === "object") return (cur as Record<string, unknown>)[k];
    return undefined;
  }, obj) as string ?? key;
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("pt");

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as Locale | null;
    if (stored === "pt" || stored === "en") setLocaleState(stored);
  }, []);

  const setLocale = (l: Locale) => {
    localStorage.setItem(STORAGE_KEY, l);
    setLocaleState(l);
  };

  const dict = locale === "en" ? en : pt;

  const t = (key: string): string =>
    resolve(dict as unknown as Record<string, unknown>, key);

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

export function useT() {
  return useContext(I18nContext).t;
}
