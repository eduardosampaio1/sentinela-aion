import type { BehaviorDial } from "@/lib/types";

export interface DialImpact {
  token_change_pct: number;
  cost_change_pct: number;
  quality_risk: "none" | "low" | "medium" | "high";
  recommendation: string;
}

/**
 * Estimates the token/cost/quality impact of each BehaviorDial value.
 * All calculations are frontend estimates for UX feedback only.
 * The backend applies the actual behavior — these numbers guide the user, not control the system.
 */
export function estimateDialImpact(dial: BehaviorDial): Record<keyof BehaviorDial, DialImpact> {
  return {
    objectivity: {
      token_change_pct: dial.objectivity > 60 ? -(dial.objectivity - 50) * 0.4 : (50 - dial.objectivity) * 0.3,
      cost_change_pct: dial.objectivity > 60 ? -(dial.objectivity - 50) * 0.3 : (50 - dial.objectivity) * 0.2,
      quality_risk: dial.objectivity > 85 ? "medium" : "none",
      recommendation: dial.objectivity > 85
        ? "Respostas muito curtas podem perder contexto importante"
        : dial.objectivity < 30
        ? "Ideal para onboarding e treinamento"
        : "Bom equilíbrio entre contexto e objetividade",
    },
    verbosity: {
      token_change_pct: (dial.verbosity - 50) * 0.6,
      cost_change_pct: (dial.verbosity - 50) * 0.5,
      quality_risk: "none",
      recommendation: dial.verbosity > 70
        ? "Mais tokens = mais custo. Ideal para equipes novas."
        : dial.verbosity < 30
        ? "Respostas mínimas. Ideal para operação automatizada."
        : "Equilíbrio padrão",
    },
    economy: {
      token_change_pct: dial.economy > 50 ? -(dial.economy - 50) * 0.5 : 0,
      cost_change_pct: dial.economy > 50 ? -(dial.economy - 50) * 0.8 : (50 - dial.economy) * 0.4,
      quality_risk: dial.economy > 80 ? "high" : dial.economy > 60 ? "medium" : "low",
      recommendation: dial.economy > 80
        ? "Custo mínimo. Qualidade pode sofrer em perguntas complexas."
        : dial.economy < 30
        ? "Máxima qualidade. Custo elevado."
        : "Bom equilíbrio custo-qualidade",
    },
    explanation: {
      token_change_pct: (dial.explanation - 50) * 0.4,
      cost_change_pct: (dial.explanation - 50) * 0.3,
      quality_risk: "none",
      recommendation: dial.explanation > 70
        ? "Respostas incluem raciocínio. Bom para decisões críticas."
        : "Respostas diretas sem explicação do raciocínio.",
    },
    confidence: {
      token_change_pct: 0,
      cost_change_pct: dial.confidence > 70 ? (dial.confidence - 50) * 0.2 : 0,
      quality_risk: dial.confidence > 85 ? "low" : "none",
      recommendation: dial.confidence > 85
        ? "Alta confiança. Pode recusar perguntas ambíguas."
        : "Aceita respostas com incerteza moderada.",
    },
    safe_mode: {
      token_change_pct: 0,
      cost_change_pct: 0,
      quality_risk: dial.safe_mode < 30 ? "high" : "none",
      recommendation: dial.safe_mode < 30
        ? "Proteções reduzidas. Risco de respostas inadequadas."
        : dial.safe_mode > 80
        ? "Modo conservador. Pode bloquear conteúdo legítimo."
        : "Proteções padrão ativas.",
    },
    formality: {
      token_change_pct: (dial.formality - 50) * 0.1,
      cost_change_pct: 0,
      quality_risk: "none",
      recommendation: dial.formality > 70
        ? "Tom corporativo. Ideal para atendimento B2B."
        : dial.formality < 30
        ? "Tom casual. Ideal para produtos consumer."
        : "Tom neutro e profissional.",
    },
  };
}
