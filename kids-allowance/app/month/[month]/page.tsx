import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentMember } from "@/lib/member";
import type { Child, Transaction } from "@/lib/types";
import { formatMonthLabel, formatYen, shiftMonth, sumTransactions } from "@/lib/aggregate";

export const dynamic = "force-dynamic";

function formatDate(dateStr: string) {
  const [, m, d] = dateStr.split("-");
  return `${Number(m)}/${Number(d)}`;
}

export default async function MonthPage({
  params,
  searchParams,
}: {
  params: Promise<{ month: string }>;
  searchParams: Promise<{ child?: string }>;
}) {
  const { member } = await getCurrentMember();

  if (!member) {
    redirect("/auth/no-access");
  }

  const { month } = await params;
  const { child: childParam } = await searchParams;

  const supabase = await createClient();

  const { data: childrenData } = await supabase
    .from("allowance_children")
    .select("id, name, emoji, color, sort_order")
    .order("sort_order", { ascending: true });

  const children = (childrenData ?? []) as Child[];

  if (children.length === 0) {
    redirect("/auth/no-access");
  }

  const childId =
    childParam && children.some((c) => c.id === childParam)
      ? childParam
      : member.child_id && children.some((c) => c.id === member.child_id)
        ? member.child_id
        : children[0].id;

  const selectedChild = children.find((c) => c.id === childId)!;

  const nextMonthStart = `${shiftMonth(month, 1)}-01`;

  const { data: transactionsData } = await supabase
    .from("allowance_transactions")
    .select("id, child_id, amount, category, purpose, occurred_on, created_by_email, created_by_name, created_at")
    .eq("child_id", childId)
    .gte("occurred_on", `${month}-01`)
    .lt("occurred_on", nextMonthStart)
    .order("occurred_on", { ascending: false })
    .order("created_at", { ascending: false });

  const transactions = (transactionsData ?? []) as Transaction[];
  const totals = sumTransactions(transactions);

  const prevMonth = shiftMonth(month, -1);
  const nextMonth = shiftMonth(month, 1);

  return (
    <main className="mx-auto max-w-lg px-4 pb-16 pt-6">
      <Link href="/" className="text-sm font-bold text-secondary underline underline-offset-2">
        ← もどる
      </Link>

      <div className="mt-4 flex gap-2">
        {children.map((c) => {
          const active = c.id === childId;
          return (
            <Link
              key={c.id}
              href={`/month/${month}?child=${c.id}`}
              className={`flex flex-1 items-center justify-center gap-2 rounded-xl2 border-2 py-3 text-base font-bold transition active:scale-95 ${
                active ? "border-transparent text-white shadow-md" : "border-ink/10 bg-white text-ink/50"
              }`}
              style={active ? { backgroundColor: c.color } : undefined}
            >
              <span className="text-xl">{c.emoji}</span>
              {c.name}
            </Link>
          );
        })}
      </div>

      <div className="mt-5 flex items-center justify-between">
        <Link
          href={`/month/${prevMonth}?child=${childId}`}
          className="rounded-xl border-2 border-ink/10 bg-white px-4 py-2 text-lg font-bold text-ink/60 transition active:scale-95"
          aria-label="前の月"
        >
          ←
        </Link>
        <p className="text-lg font-800">{formatMonthLabel(month)}</p>
        <Link
          href={`/month/${nextMonth}?child=${childId}`}
          className="rounded-xl border-2 border-ink/10 bg-white px-4 py-2 text-lg font-bold text-ink/60 transition active:scale-95"
          aria-label="翌月"
        >
          →
        </Link>
      </div>

      <div className="mt-5 rounded-xl2 bg-white p-4 shadow-sm">
        <p className="text-xs font-bold text-ink/40">{selectedChild.name}の{formatMonthLabel(month)}</p>
        <p className="mt-1 text-2xl font-800 text-primary">{formatYen(totals.net)}</p>
        <p className="mt-2 text-[11px] text-ink/50">
          あげた {formatYen(totals.given)} ／ 戻り {formatYen(totals.returned)}
        </p>
      </div>

      <div className="mt-6">
        <p className="mb-3 text-xs font-bold text-ink/40">きろく</p>

        {transactions.length === 0 ? (
          <div className="rounded-xl2 bg-white p-8 text-center text-sm text-ink/40">この月のきろくはありません</div>
        ) : (
          <ul className="space-y-2">
            {transactions.map((t) => {
              const isReturn = t.amount < 0;
              return (
                <li key={t.id} className="flex items-center justify-between rounded-xl2 bg-white p-4 shadow-sm">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          isReturn ? "bg-amber-soft text-amber" : "bg-secondary-soft text-secondary"
                        }`}
                      >
                        {t.category}
                      </span>
                      <span className="text-[11px] text-ink/40">{formatDate(t.occurred_on)}</span>
                    </div>
                    {t.purpose && <p className="mt-1 truncate text-sm text-ink/60">{t.purpose}</p>}
                    <p className="mt-0.5 text-[11px] text-ink/30">{t.created_by_name} が記録</p>
                  </div>
                  <span className={`text-lg font-800 ${isReturn ? "text-amber" : "text-mint"}`}>
                    {isReturn ? "-" : "+"}
                    {formatYen(Math.abs(t.amount))}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </main>
  );
}
