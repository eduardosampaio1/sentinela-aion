"use client";

import {
  BookOpen,
  Code2,
  Layers,
  ExternalLink,
  Keyboard,
  Terminal,
  GitBranch,
  MessageCircle,
  Mail,
  GitPullRequest,
  Rss,
  CheckCircle2,
  Clock,
  Zap,
} from "lucide-react";

const shortcuts: Array<{ keys: string[]; desc: string }> = [
  { keys: ["G", "H"], desc: "Ir para Visão Geral" },
  { keys: ["G", "O"], desc: "Ir para Operação" },
  { keys: ["G", "R"], desc: "Ir para Roteamento" },
  { keys: ["G", "P"], desc: "Ir para Proteção" },
  { keys: ["G", "S"], desc: "Ir para Sessões" },
  { keys: ["G", "E"], desc: "Ir para Economia" },
  { keys: ["?"], desc: "Mostrar / ocultar atalhos" },
  { keys: ["⌘", "K"], desc: "Pesquisa global (em breve)" },
  { keys: ["Esc"], desc: "Fechar modal / painel" },
  { keys: ["⌘", "/"], desc: "Alternar sidebar" },
];

const changelog: Array<{
  version: string;
  date: string;
  type: "release" | "patch";
  items: string[];
}> = [
  {
    version: "2.4.0",
    date: "Abr 2026",
    type: "release",
    items: [
      "Laboratório com modo A/B e rastreamento de experimentos",
      "Monitor de anomalias com histórico de 24h por métrica",
      "Fila de anotação humana para calibração de decisões",
    ],
  },
  {
    version: "2.3.1",
    date: "Mar 2026",
    type: "patch",
    items: [
      "Correção: falsos positivos no detector de PII para CNPJ",
      "Melhoria: topology map com seleção interativa de nós",
    ],
  },
  {
    version: "2.3.0",
    date: "Fev 2026",
    type: "release",
    items: [
      "Mapa de topologia de roteamento com fluxo visual",
      "Página Economia com comparativo de custo vs. baseline",
      "Proteção: Master Control com bypass global de emergência",
    ],
  },
];

export function HelpPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          Ajuda & Documentação
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          Guias, referências de API, atalhos e suporte
        </p>
      </div>

      {/* Quick links */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-[var(--color-text-muted)]/60">
          Documentação
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            {
              icon: BookOpen,
              title: "Guia de início rápido",
              desc: "Configure o AION em menos de 1 dia",
              href: "#",
              color: "text-[var(--color-primary)]",
              bg: "bg-[var(--color-primary)]/10",
            },
            {
              icon: Code2,
              title: "Referência de API",
              desc: "Endpoints, schemas, exemplos de código",
              href: "#",
              color: "text-blue-400",
              bg: "bg-blue-900/20",
            },
            {
              icon: Layers,
              title: "Conceitos do AION",
              desc: "Proteção, Roteamento, Otimização e o pipeline",
              href: "#",
              color: "text-violet-400",
              bg: "bg-violet-900/20",
            },
          ].map((card) => {
            const Icon = card.icon;
            return (
              <a
                key={card.title}
                href={card.href}
                className="group flex items-start gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 transition-colors hover:border-[var(--color-primary)]/30 hover:bg-white/5"
              >
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${card.bg}`}>
                  <Icon className={`h-4 w-4 ${card.color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <p className="text-sm font-semibold text-[var(--color-text)]">{card.title}</p>
                    <ExternalLink className="h-3 w-3 text-[var(--color-text-muted)] opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{card.desc}</p>
                </div>
              </a>
            );
          })}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Keyboard shortcuts */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Keyboard className="h-4 w-4 text-[var(--color-text-muted)]" />
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Atalhos de teclado</h2>
          </div>
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] divide-y divide-[var(--color-border)]">
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
          <div className="flex items-center gap-2 mb-3">
            <Rss className="h-4 w-4 text-[var(--color-text-muted)]" />
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Changelog</h2>
          </div>
          <div className="space-y-3">
            {changelog.map((entry) => (
              <div
                key={entry.version}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
              >
                <div className="flex items-center gap-2 mb-2">
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
                      <CheckCircle2 className="h-3 w-3 mt-0.5 shrink-0 text-green-500/60" />
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
          Suporte
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            {
              icon: MessageCircle,
              title: "Chat com suporte",
              desc: "Resposta em < 4h para planos Enterprise",
              action: "Abrir chat",
              color: "text-green-400",
            },
            {
              icon: Mail,
              title: "E-mail",
              desc: "suporte@aion.sentinela.io",
              action: "Enviar e-mail",
              color: "text-blue-400",
            },
            {
              icon: GitPullRequest,
              title: "Issues no GitHub",
              desc: "Bugs e sugestões de feature",
              action: "Abrir issue",
              color: "text-[var(--color-text-muted)]",
            },
          ].map((card) => {
            const Icon = card.icon;
            return (
              <div
                key={card.title}
                className="flex flex-col gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
              >
                <Icon className={`h-5 w-5 ${card.color}`} />
                <div>
                  <p className="text-sm font-semibold text-[var(--color-text)]">{card.title}</p>
                  <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{card.desc}</p>
                </div>
                <button className="mt-auto rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)] transition-colors cursor-pointer">
                  {card.action}
                </button>
              </div>
            );
          })}
        </div>
      </section>

      {/* System info */}
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Terminal className="h-4 w-4 text-[var(--color-text-muted)]" />
          <h2 className="text-sm font-semibold text-[var(--color-text)]">Informações do sistema</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-4 text-xs">
          {[
            { label: "Versão AION", value: "v2.4.0" },
            { label: "Console", value: "v2.4.0-rc3" },
            { label: "Pipeline", value: "hardened / 488 testes" },
            { label: "Status", value: "Todos os sistemas operacionais" },
          ].map((item) => (
            <div key={item.label}>
              <p className="text-[var(--color-text-muted)] mb-0.5">{item.label}</p>
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
