import Link from "next/link";
import type { Transaction } from "@/lib/types";
import { formatYen, monthKey, sumTransactions } from "@/lib/aggregate";

export default function SummaryCards({
  transactions,
  childId,
}: {
  transactions: Transaction[];
  childId: string;
}) {
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

  const thisMonth = transactions.filter((t) => monthKey(t.occurred_on) === currentMonth);
  const monthTotals = sumTransactions(thisMonth);
  const allTotals = sumTransactions(transactions);

  return (
    <div className="grid grid-cols-2 gap-3">
      <Link
        href={`/month/${currentMonth}?child=${childId}`}
        className="rounded-xl2 bg-white p-4 shadow-sm transition active:scale-[0.98]"
      >
        <p className="text-xs font-bold text-ink/40">今月の差し引き</p>
        <p className="mt-1 text-2xl font-800 text-primary">{formatYen(monthTotals.net)}</p>
        <p className="mt-2 text-[11px] text-ink/50">
          あげた {formatYen(monthTotals.given)} ／ 戻り {formatYen(monthTotals.returned)}
        </p>
      </Link>
      <div className="rounded-xl2 bg-white p-4 shadow-sm">
        <p className="text-xs font-bold text-ink/40">これまでの累計</p>
        <p className="mt-1 text-2xl font-800 text-secondary">{formatYen(allTotals.net)}</p>
        <p className="mt-2 text-[11px] text-ink/50">
          あげた {formatYen(allTotals.given)} ／ 戻り {formatYen(allTotals.returned)}
        </p>
      </div>
    </div>
  );
}
