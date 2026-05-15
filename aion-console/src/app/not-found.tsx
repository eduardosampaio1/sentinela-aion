import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)]">
      <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-8 text-center">
        <p className="text-5xl font-bold text-[var(--color-text-muted)]/30">404</p>
        <h2 className="mt-4 text-lg font-bold text-[var(--color-text)]">
          Pagina nao encontrada
        </h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          A pagina que voce procura nao existe ou foi movida.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-lg bg-[var(--color-cta)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity"
        >
          Voltar ao dashboard
        </Link>
      </div>
    </div>
  );
}
