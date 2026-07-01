"use client";

interface RefreshIconButtonProps {
  refreshing: boolean;
  label: string;
  onRefresh: () => void;
}

export function RefreshIconButton({ refreshing, label, onRefresh }: RefreshIconButtonProps) {
  return (
    <button
      className={`icon-button refresh-icon-button ${refreshing ? "spinning" : ""}`}
      type="button"
      disabled={refreshing}
      onClick={onRefresh}
      title={label}
      aria-label={label}
    >
      <svg className="refresh-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M20 11a8.1 8.1 0 0 0-15.5-2M4 5v4h4" />
        <path d="M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4" />
      </svg>
    </button>
  );
}
