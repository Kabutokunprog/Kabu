import Link from "next/link";
import type { Transaction } from "@/lib/types";
import { formatMonthLabel, formatYen, groupByMonth } from "@/lib/aggregate";

export default function MonthlyTable({
  transactions,
  childId,
}: {
  transactions: Transaction[];
  childId: string;
}) {
  const months = groupByMonth(transactions).slice(0, 12);

  if (months.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl2 bg-white p-4 shadow-sm">
      <p className="mb-3 text-xs font-bold text-ink/40">月ごとのまとめ</p>
      <div className="space-y-2">
        {months.map(({ key, totals }) => (
          <Link
            key={key}
            href={`/month/${key}?child=${childId}`}
            className="flex items-center justify-between border-b border-ink/5 pb-2 transition last:border-0 last:pb-0 active:opacity-60"
          >
            <span className="text-sm font-bold text-ink/70">{formatMonthLabel(key)}</span>
            <div className="flex items-center gap-3 text-xs text-ink/50">
              <span className="text-mint">+{formatYen(totals.given)}</span>
              {totals.returned > 0 && <span className="text-amber">-{formatYen(totals.returned)}</span>}
              <span className="font-bold text-ink">{formatYen(totals.net)}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
