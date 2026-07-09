export function formatDate(value?: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function formatBytes(bytes?: number | null): string {
  const value = bytes || 0;
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function compactStatus(value: string): string {
  return value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

export function statusTone(value: string): "success" | "danger" | "warning" | "info" | "neutral" {
  if (value.includes("FAILED")) return "danger";
  if (value.includes("CANCELLED")) return "warning";
  if (value.includes("REJECTED")) return "warning";
  if (value.includes("INDEXED") || value.includes("COMPLETE")) return "success";
  if (value.includes("RUNNING") || value.includes("PENDING") || value.includes("SUBMITTED")) return "info";
  return "neutral";
}
