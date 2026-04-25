"use client";

import { useState } from "react";
import {
  Store,
  Star,
  Download,
  Shield,
  Tag,
  CheckCircle2,
  RefreshCw,
  ChevronRight,
  Package,
  Globe,
  AlertTriangle,
  Lock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/demo-banner";
import { useApiData } from "@/lib/use-api-data";
import { browseMarketplace, installMarketplacePolicy, rateMarketplacePolicy } from "@/lib/api";

// ─── Mock data ─────────────────────────────────────────────────────────────────

const mockPolicies: Record<string, unknown>[] = [
  {
    id: "pol-jailbreak-v2",
    name: "Anti-Jailbreak Pro v2",
    description: "Detecção avançada de tentativas de jailbreak com 98.7% de precisão. Inclui cobertura para DAN, roleplay malicioso, e escalada de autoridade.",
    author_tenant: "security-research",
    version: "2.1.0",
    category: "jailbreak",
    tags: ["jailbreak", "safety", "enterprise"],
    price_usd: 0,
    downloads: 1247,
    rating: 4.8,
    rating_count: 89,
    is_verified: true,
    published_at: Date.now() / 1000 - 86400 * 45,
  },
  {
    id: "pol-pii-br-v1",
    name: "PII Brasil Enhanced",
    description: "Cobertura completa de PII brasileiro: CPF, CNPJ, RG, CNH, PIS/PASEP, título de eleitor, NIS. Compatível com LGPD.",
    author_tenant: "compliance-team",
    version: "1.3.2",
    category: "pii",
    tags: ["pii", "lgpd", "brasil", "compliance"],
    price_usd: 0,
    downloads: 892,
    rating: 4.9,
    rating_count: 63,
    is_verified: true,
    published_at: Date.now() / 1000 - 86400 * 30,
  },
  {
    id: "pol-financial-guard",
    name: "Financial Guard",
    description: "Proteção para contextos de serviços financeiros: detecta tentativas de manipulação de transações, fraude, e exfiltração de dados bancários.",
    author_tenant: "fintech-alliance",
    version: "1.0.0",
    category: "domain",
    tags: ["finance", "fraud", "banking", "compliance"],
    price_usd: 49.0,
    downloads: 234,
    rating: 4.6,
    rating_count: 18,
    is_verified: true,
    published_at: Date.now() / 1000 - 86400 * 15,
  },
  {
    id: "pol-prompt-injection",
    name: "Prompt Injection Shield",
    description: "Detecta e bloqueia prompt injection em multi-turn e em conteúdo de sistema. Cobre variantes clássicas e emergentes.",
    author_tenant: "red-team-labs",
    version: "3.0.1",
    category: "jailbreak",
    tags: ["injection", "multi-turn", "system-prompt"],
    price_usd: 0,
    downloads: 2103,
    rating: 4.7,
    rating_count: 142,
    is_verified: false,
    published_at: Date.now() / 1000 - 86400 * 60,
  },
  {
    id: "pol-hipaa-compliance",
    name: "HIPAA Compliance Pack",
    description: "Proteção para dados de saúde: PHI detection, bloqueio de diagnósticos não autorizados, conformidade com HIPAA.",
    author_tenant: "healthtech-security",
    version: "2.0.0",
    category: "compliance",
    tags: ["hipaa", "health", "phi", "usa"],
    price_usd: 99.0,
    downloads: 156,
    rating: 4.5,
    rating_count: 12,
    is_verified: true,
    published_at: Date.now() / 1000 - 86400 * 20,
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  jailbreak: { label: "Jailbreak", color: "bg-red-900/30 text-red-400 border-red-800/50", icon: <Shield className="h-3 w-3" /> },
  pii: { label: "PII", color: "bg-amber-900/30 text-amber-400 border-amber-800/50", icon: <Lock className="h-3 w-3" /> },
  compliance: { label: "Compliance", color: "bg-sky-900/30 text-sky-400 border-sky-800/50", icon: <CheckCircle2 className="h-3 w-3" /> },
  domain: { label: "Domínio", color: "bg-violet-900/30 text-violet-400 border-violet-800/50", icon: <Globe className="h-3 w-3" /> },
  custom: { label: "Custom", color: "bg-slate-800/60 text-slate-400 border-slate-700/50", icon: <Package className="h-3 w-3" /> },
};

const ALL_CATEGORIES = ["todos", "jailbreak", "pii", "compliance", "domain", "custom"] as const;
type Category = (typeof ALL_CATEGORIES)[number];

function fmtAge(ts: number): string {
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  if (days === 0) return "hoje";
  if (days === 1) return "ontem";
  if (days < 30) return `${days}d atrás`;
  return `${Math.floor(days / 30)}m atrás`;
}

function StarRating({ value, count }: { value: number; count: number }) {
  return (
    <div className="flex items-center gap-1">
      <Star className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
      <span className="text-xs font-medium text-yellow-400">{value.toFixed(1)}</span>
      <span className="text-xs text-[var(--color-text-muted)]">({count})</span>
    </div>
  );
}

// ─── Policy card ───────────────────────────────────────────────────────────────

function PolicyCard({
  policy,
  onInstall,
  installedIds,
}: {
  policy: Record<string, unknown>;
  onInstall: (id: string) => void;
  installedIds: Set<string>;
}) {
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [rated, setRated] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const id = policy.id as string;
  const cat = (policy.category as string) ?? "custom";
  const catCfg = CATEGORY_CONFIG[cat] ?? CATEGORY_CONFIG.custom;
  const isInstalled = installedIds.has(id);
  const isPremium = (policy.price_usd as number) > 0;
  const isVerified = policy.is_verified as boolean;

  const handleRate = async (stars: number) => {
    try {
      await rateMarketplacePolicy(id, stars);
      setRating(stars);
      setRated(true);
    } catch {
      setRating(stars);
      setRated(true);
    }
  };

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden transition-colors hover:border-white/20">
      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">{policy.name as string}</h3>
              {isVerified && (
                <span className="flex items-center gap-0.5 text-[10px] font-medium text-teal-400">
                  <CheckCircle2 className="h-3 w-3" />
                  verificado
                </span>
              )}
              {isPremium && (
                <span className="rounded-full border border-yellow-800/50 bg-yellow-900/20 px-2 py-0.5 text-[10px] font-medium text-yellow-400">
                  ${(policy.price_usd as number).toFixed(0)}/mês
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${catCfg.color}`}
              >
                {catCfg.icon}
                {catCfg.label}
              </span>
              <span className="text-[10px] text-[var(--color-text-muted)]">v{policy.version as string}</span>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                por {(policy.author_tenant as string).replace(/-/g, " ")}
              </span>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 flex-shrink-0">
            <StarRating value={policy.rating as number} count={policy.rating_count as number} />
            <div className="flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
              <Download className="h-3 w-3" />
              {(policy.downloads as number).toLocaleString("pt-BR")}
            </div>
          </div>
        </div>

        <p className="text-xs text-[var(--color-text-muted)] mb-3 leading-relaxed">
          {policy.description as string}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {(policy.tags as string[]).map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-0.5 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-[var(--color-text-muted)]"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isInstalled ? (
              <span className="flex items-center gap-1.5 text-xs text-teal-400">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Instalado em Shadow Mode
              </span>
            ) : (
              <button
                onClick={() => onInstall(id)}
                className="flex items-center gap-1.5 rounded-lg bg-[var(--color-primary)]/10 border border-[var(--color-primary)]/30 px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/20 transition-colors"
              >
                <Download className="h-3.5 w-3.5" />
                Instalar
              </button>
            )}
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
            >
              {expanded ? "Menos" : "Detalhes"}
              <ChevronRight className={`inline ml-0.5 h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`} />
            </button>
          </div>
          <span className="text-[10px] text-[var(--color-text-muted)]">
            publicado {fmtAge(policy.published_at as number)}
          </span>
        </div>

        {/* Expanded: rate */}
        {expanded && (
          <div className="mt-4 border-t border-[var(--color-border)] pt-4">
            <p className="mb-2 text-xs text-[var(--color-text-muted)]">Avalie esta política:</p>
            {rated ? (
              <p className="text-xs text-teal-400">
                <CheckCircle2 className="inline h-3 w-3 mr-1" />
                Avaliação enviada — obrigado!
              </p>
            ) : (
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => handleRate(star)}
                    onMouseEnter={() => setHoverRating(star)}
                    onMouseLeave={() => setHoverRating(0)}
                    className="transition-transform hover:scale-110"
                  >
                    <Star
                      className={`h-5 w-5 ${
                        star <= (hoverRating || rating)
                          ? "fill-yellow-400 text-yellow-400"
                          : "text-[var(--color-text-muted)]"
                      }`}
                    />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function MarketplacePage() {
  const [category, setCategory] = useState<Category>("todos");
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set());
  const [installing, setInstalling] = useState<string | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);

  const fetcher = () =>
    browseMarketplace(category !== "todos" ? { category, limit: 50 } : { limit: 50 });

  const { data: policies, isDemo, refetch } = useApiData(fetcher, mockPolicies, {});

  const handleInstall = async (policyId: string) => {
    setInstalling(policyId);
    setInstallError(null);
    try {
      await installMarketplacePolicy(policyId, true);
      setInstalledIds((prev) => new Set([...prev, policyId]));
    } catch (err) {
      // Optimistic: mark installed anyway (shadow mode)
      setInstalledIds((prev) => new Set([...prev, policyId]));
      setInstallError(err instanceof Error ? err.message : "Erro ao instalar");
    } finally {
      setInstalling(null);
    }
  };

  const filteredPolicies =
    category === "todos"
      ? policies
      : policies.filter((p) => (p.category as string) === category);

  const freeCount = filteredPolicies.filter((p) => (p.price_usd as number) === 0).length;
  const premiumCount = filteredPolicies.filter((p) => (p.price_usd as number) > 0).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Marketplace de Políticas
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Instale políticas validadas pela comunidade e pela equipe AION
          </p>
        </div>
        <button
          onClick={refetch}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Atualizar
        </button>
      </div>

      {isDemo && <DemoBanner onRetry={refetch} />}

      {installError && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-800/50 bg-amber-900/10 px-4 py-3 text-sm text-amber-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {installError} — política instalada em Shadow Mode localmente.
        </div>
      )}

      {/* Stats bar */}
      <div className="flex items-center gap-6 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-5 py-3">
        <div className="flex items-center gap-2">
          <Store className="h-4 w-4 text-[var(--color-text-muted)]" />
          <span className="text-sm font-semibold text-[var(--color-text)]">{filteredPolicies.length}</span>
          <span className="text-xs text-[var(--color-text-muted)]">políticas</span>
        </div>
        <div className="h-4 w-px bg-[var(--color-border)]" />
        <div className="text-xs text-[var(--color-text-muted)]">
          <span className="font-medium text-teal-400">{freeCount} grátis</span>
          {premiumCount > 0 && (
            <> · <span className="font-medium text-yellow-400">{premiumCount} premium</span></>
          )}
        </div>
        <div className="h-4 w-px bg-[var(--color-border)]" />
        <div className="text-xs text-[var(--color-text-muted)]">
          Políticas instaladas em <strong className="text-[var(--color-text)]">Shadow Mode</strong> —
          avalie o impacto antes de promover para live
        </div>
      </div>

      {/* Category filter */}
      <div className="flex flex-wrap gap-2">
        {ALL_CATEGORIES.map((cat) => {
          const cfg = cat === "todos" ? null : CATEGORY_CONFIG[cat];
          return (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                category === cat
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                  : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              }`}
            >
              {cfg?.icon}
              {cat === "todos" ? "Todos" : cfg?.label ?? cat}
            </button>
          );
        })}
      </div>

      {/* Policy grid */}
      {filteredPolicies.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16">
          <Store className="mb-3 h-10 w-10 text-[var(--color-text-muted)] opacity-40" />
          <p className="text-sm font-medium text-[var(--color-text)]">Nenhuma política nesta categoria</p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Seja o primeiro a publicar uma política aqui
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filteredPolicies.map((policy, i) => (
            <PolicyCard
              key={(policy.id as string) ?? i}
              policy={policy}
              onInstall={(id) => {
                if (!installing) void handleInstall(id);
              }}
              installedIds={installedIds}
            />
          ))}
        </div>
      )}

      {/* Info banner */}
      <div className="rounded-xl border border-[var(--color-border)] bg-sky-900/10 p-5">
        <div className="flex items-start gap-3">
          <Store className="h-4 w-4 flex-shrink-0 mt-0.5 text-sky-400" />
          <div>
            <p className="text-sm font-medium text-sky-400">Como funciona o Marketplace</p>
            <p className="mt-1 text-xs text-[var(--color-text-muted)]">
              Políticas são instaladas automaticamente em <strong>Shadow Mode</strong> para avaliação de impacto.
              Use a página <strong>Shadow Mode</strong> para comparar concordância e promover para live quando satisfeito.
              Políticas verificadas <CheckCircle2 className="inline h-3 w-3 text-teal-400" /> passam por revisão da equipe AION.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
