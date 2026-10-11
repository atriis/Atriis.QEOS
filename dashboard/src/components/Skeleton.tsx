/** Placeholder cards that hold a page's layout while its data loads, so nothing jumps when it arrives.
 *  The container is a polite status named `label`; the shapes are hidden from assistive tech. */
export function SkeletonCard({ height, className }: { height?: number; className?: string }) {
  return (
    <div className={`card skeleton-card${className ? ` ${className}` : ""}`} aria-hidden="true">
      <span className="skeleton skeleton-line" />
      <span className="skeleton skeleton-block" style={height ? { height } : undefined} />
    </div>
  );
}

export function SkeletonStatus({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-label={label} aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/** One figure loading inside a card (an Overview widget's number, or a widget's code arriving). */
export function SkeletonStat({ label }: { label: string }) {
  return (
    <SkeletonStatus label={label}>
      <span className="skeleton stat-skeleton" aria-hidden="true" />
    </SkeletonStatus>
  );
}
