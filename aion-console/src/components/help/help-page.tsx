"use client";

import {
  BookOpen,
  Code2,
  Layers,
  ExternalLink,
  Keyboard,
  Terminal,
  MessageCircle,
  Mail,
  GitPullRequest,
  Rss,
  CheckCircle2,
  Clock,
  Zap,
} from "lucide-react";
import { useT } from "@/lib/i18n";

export function HelpPage() {
  const t = useT();

  const shortcuts: Array<{ keys: string[]; desc: string }> = [
    { keys: ["G", "H"], desc: t("help.shortcuts.go_overview") },
    { keys: ["G", "O"], desc: t("help.shortcuts.go_operations") },
    { keys: ["G", "R"], desc: t("help.shortcuts.go_routing") },
    { keys: ["G", "P"], desc: t("help.shortcuts.go_protection") },
    { keys: ["G", "S"], desc: t("help.shortcuts.go_sessions") },
    { keys: ["G", "E"], desc: t("help.shortcuts.go_economy") },
    { keys: ["?"],      desc: t("help.shortcuts.show_shortcuts") },
    { keys: ["⌘", "K"], desc: t("help.shortcuts.global_search") },
    { keys: ["Esc"],    desc: t("help.shortcuts.close_modal") },
    { keys: ["⌘", "/"], desc: t("help.shortcuts.toggle_sidebar") },
  ];

  const changelog: Array<{
    version: string;
    date: string;
    type: "release" | "patch";
    items: string[];
  }> = [
    {
      version: "2.4.0",
      date: t("help.changelog_dates.v240"),
      type: "release",
      items: [
        t("help.changelog_items.v240_0"),
        t("help.changelog_items.v240_1"),
        t("help.changelog_items.v240_2"),
      ],
    },
    {
      version: "2.3.1",
      date: t("help.changelog_dates.v231"),
      type: "patch",
      items: [
        t("help.changelog_items.v231_0"),
        t("help.changelog_items.v231_1"),
      ],
    },
    {
      version: "2.3.0",
      date: t("help.changelog_dates.v230"),
      type: "release",
      items: [
        t("help.changelog_items.v230_0"),
        t("help.changelog_items.v230_1"),
        t("help.changelog_items.v230_2"),
      ],
    },
  ];

  const docCards = [
    { icon: BookOpen, title: t("help.docs_cards.quickstart_title"), desc: t("help.docs_cards.quickstart_desc"), color: "text-[var(--color-primary)]", bg: "bg-[var(--color-primary)]/10" },
    { icon: Code2,   title: t("help.docs_cards.api_title"),         desc: t("help.docs_cards.api_desc"),         color: "text-blue-400",                 bg: "bg-blue-900/20" },
    { icon: Layers,  title: t("help.docs_cards.concepts_title"),    desc: t("help.docs_cards.concepts_desc"),    color: "text-violet-400",               bg: "bg-violet-900/20" },
  ];

  const supportCards = [
    { icon: MessageCircle, title: t("help.support_cards.chat_title"),   desc: t("help.support_cards.chat_desc"),   action: t("help.support_cards.chat_action"),   color: "text-green-400" },
    { icon: Mail,          title: t("help.support_cards.email_title"),  desc: t("help.support_cards.email_desc"),  action: t("help.support_cards.email_action"),  color: "text-blue-400" },
    { icon: GitPullRequest,title: t("help.support_cards.github_title"), desc: t("help.support_cards.github_desc"), action: t("help.support_cards.github_action"), color: "text-[var(--color-text-muted)]" },
  ];

  const systemInfo = [
    { label: t("help.system_labels.version"),  value: "v2.4.0" },
    { label: t("help.system_labels.console"),  value: "v2.4.0-rc3" },
    { label: t("help.system_labels.pipeline"), value: t("help.system_labels.pipeline_value") },
    { label: t("help.system_labels.status"),   value: t("help.system_labels.status_value") },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          {t("help.title")}
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          {t("help.subtitle")}
        </p>
      </div>

      {/* Quick links */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-[var(--color-text-muted)]/60">
          {t("help.docs_section")}
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {docCards.map((card) => {
            const Icon = card.icon;
            return (
              <a
                key={card.title}
                href="#"
                className="group flex items-start gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 transition-colors hover:border-[var(--color-primary)]/30 hover:bg-white/5"
              >
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${card.bg}`}>
                  <Icon className={`h-4 w-4 ${card.color}`} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1">
                    <p className="text-sm font-semibold text-[var(--color-text)]">{card.title}</p>
                    <ExternalLink className="h-3 w-3 text-[var(--color-text-muted)] opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{card.desc}</p>
                </div>
              </a>
            );
          })}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Keyboard shortcuts */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Keyboard className="h-4 w-4 text-[var(--color-text-muted)]" />
            <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("help.shortcuts_section")}</h2>
          </div>
          <div className="divide-y divide-[var(--color-border)] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            {shortcuts.map((s, i) => (
              <div key={i} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-xs text-[var(--color-text-muted)]">{s.desc}</span>
                <div className="flex items-center gap-1">
                  {s.keys.map((k) => (
                    <kbd
                      key={k}
                      className="inline-flex h-5 min-w-[20px] items-center justify-center rounded border border-[var(--color-border)] bg-white/5 px-1.5 text-[10px] font-[family-name:var(--font-mono)] text-[var(--color-text-muted)]"
                    >
                      {k}
                    </kbd>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Changelog */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Rss className="h-4 w-4 text-[var(--color-text-muted)]" />
            <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("help.changelog_section")}</h2>
          </div>
          <div className="space-y-3">
            {changelog.map((entry) => (
              <div
                key={entry.version}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
              >
                <div className="mb-2 flex items-center gap-2">
                  <span className="font-[family-name:var(--font-mono)] text-sm font-semibold text-[var(--color-text)]">
                    v{entry.version}
                  </span>
                  {entry.type === "release" ? (
                    <span className="inline-flex items-center gap-1 rounded-md bg-[var(--color-primary)]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-primary)]">
                      <Zap className="h-2.5 w-2.5" />
                      release
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-md bg-amber-900/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
                      patch
                    </span>
                  )}
                  <span className="ml-auto flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                    <Clock className="h-3 w-3" />
                    {entry.date}
                  </span>
                </div>
                <ul className="space-y-1">
                  {entry.items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-[var(--color-text-muted)]">
                      <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-green-500/60" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Support */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-[var(--color-text-muted)]/60">
          {t("help.support_section")}
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {supportCards.map((card) => {
            const Icon = card.icon;
            return (
              <div
                key={card.title}
                className="flex flex-col gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
              >
                <Icon className={`h-5 w-5 ${card.color}`} />
                <div>
                  <p className="text-sm font-semibold text-[var(--color-text)]">{card.title}</p>
                  <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{card.desc}</p>
                </div>
                <button className="mt-auto cursor-pointer rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--color-text)]">
                  {card.action}
                </button>
              </div>
            );
          })}
        </div>
      </section>

      {/* System info */}
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <div className="mb-4 flex items-center gap-2">
          <Terminal className="h-4 w-4 text-[var(--color-text-muted)]" />
          <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("help.system_section")}</h2>
        </div>
        <div className="grid gap-3 text-xs sm:grid-cols-4">
          {systemInfo.map((item) => (
            <div key={item.label}>
              <p className="mb-0.5 text-[var(--color-text-muted)]">{item.label}</p>
              <p className="font-[family-name:var(--font-mono)] font-medium text-[var(--color-text)]">
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
