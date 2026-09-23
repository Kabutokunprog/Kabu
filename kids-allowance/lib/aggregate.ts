import type { Transaction } from "@/lib/types";

export function monthKey(dateStr: string) {
  return dateStr.slice(0, 7); // YYYY-MM
}

export function formatMonthLabel(key: string) {
  const [y, m] = key.split("-");
  return `${y}年${Number(m)}月`;
}

export type Totals = {
  given: number;
  returned: number;
  net: number;
};

export function sumTransactions(transactions: Transaction[]): Totals {
  let given = 0;
  let returned = 0;
  for (const t of transactions) {
    if (t.amount > 0) given += t.amount;
    else returned += Math.abs(t.amount);
  }
  return { given, returned, net: given - returned };
}

export function groupByMonth(transactions: Transaction[]): { key: string; totals: Totals }[] {
  const map = new Map<string, Transaction[]>();
  for (const t of transactions) {
    const key = monthKey(t.occurred_on);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(t);
  }
  return Array.from(map.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([key, txns]) => ({ key, totals: sumTransactions(txns) }));
}

export function formatYen(amount: number) {
  return `¥${amount.toLocaleString("ja-JP")}`;
}

export function shiftMonth(key: string, delta: number) {
  const [y, m] = key.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
