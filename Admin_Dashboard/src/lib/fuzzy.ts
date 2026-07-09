function normalize(value: unknown): string {
  return String(value || "").toLowerCase();
}

function scoreOne(candidateValue: unknown, queryValue: string): number {
  const candidate = normalize(candidateValue);
  const query = normalize(queryValue).trim();
  if (!query) return 1;
  if (!candidate) return -1;

  const compactQuery = query.replace(/\s+/g, "");
  if (!compactQuery) return 1;

  if (candidate === query) return 10000;
  if (candidate.startsWith(query)) return 8000 - candidate.length;
  const directIndex = candidate.indexOf(query);
  if (directIndex >= 0) return 6500 - directIndex * 8 - candidate.length;

  let score = 0;
  let queryIndex = 0;
  let lastMatch = -1;
  for (let index = 0; index < candidate.length && queryIndex < compactQuery.length; index += 1) {
    if (candidate[index] !== compactQuery[queryIndex]) continue;

    score += 80;
    if (index === 0 || "/\\-_. ".includes(candidate[index - 1])) score += 35;
    if (lastMatch === index - 1) score += 45;
    score -= index * 0.5;
    lastMatch = index;
    queryIndex += 1;
  }

  if (queryIndex !== compactQuery.length) return -1;
  return score - candidate.length * 0.1;
}

export function fuzzyFilter<T>(items: T[], query: string, fields: Array<keyof T>): T[] {
  const trimmed = query.trim();
  if (!trimmed) return items;

  return items
    .map((item, index) => {
      const score = Math.max(...fields.map((field) => scoreOne(item[field], trimmed)));
      return { item, index, score };
    })
    .filter((entry) => entry.score >= 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}
