import ptBR from "../../copy/pt-BR.json";
import en from "../../copy/en.json";

export type Locale = "pt-BR" | "en";

const messages: Record<Locale, typeof ptBR> = {
  "pt-BR": ptBR,
  en: en as typeof ptBR,
};

let currentLocale: Locale = "pt-BR";

export function setLocale(locale: Locale) {
  currentLocale = locale;
}

export function getLocale(): Locale {
  return currentLocale;
}

export function t(path: string): string {
  const keys = path.split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = messages[currentLocale];
  for (const key of keys) {
    value = value?.[key];
  }
  return typeof value === "string" ? value : path;
}

export { ptBR, en };
