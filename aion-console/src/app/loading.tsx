export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)]">
      <div className="flex flex-col items-center gap-4">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--color-primary)]/20 border-t-[var(--color-primary)]" />
        <p className="text-sm text-[var(--color-text-muted)]">Carregando...</p>
      </div>
    </div>
  );
}
