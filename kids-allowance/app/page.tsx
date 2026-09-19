import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentMember } from "@/lib/member";
import type { Child, Transaction } from "@/lib/types";
import Link from "next/link";
import ChildTabs from "@/components/ChildTabs";
import ChildPicker from "@/components/ChildPicker";
import SummaryCards from "@/components/SummaryCards";
import MonthlyTable from "@/components/MonthlyTable";
import TransactionBoard from "@/components/TransactionBoard";
import LogoutButton from "@/components/LogoutButton";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ child?: string }>;
}) {
  const resolvedSearchParams = await searchParams;
  const { member } = await getCurrentMember();

  if (!member) {
    redirect("/auth/no-access");
  }

  const supabase = await createClient();

  const { data: childrenData } = await supabase
    .from("allowance_children")
    .select("id, name, emoji, color, sort_order")
    .order("sort_order", { ascending: true });

  const children = (childrenData ?? []) as Child[];

  if (children.length === 0) {
    redirect("/auth/no-access");
  }

  const requestedChildId =
    resolvedSearchParams.child && children.some((c) => c.id === resolvedSearchParams.child)
      ? resolvedSearchParams.child
      : null;

  if (!requestedChildId) {
    return <ChildPicker children={children} displayName={member.display_name} />;
  }

  const selectedChildId = requestedChildId;

  const selectedChild = children.find((c) => c.id === selectedChildId)!;

  const { data: transactionsData } = await supabase
    .from("allowance_transactions")
    .select("id, child_id, amount, category, purpose, occurred_on, created_by_email, created_by_name, created_at")
    .eq("child_id", selectedChildId)
    .order("occurred_on", { ascending: false })
    .order("created_at", { ascending: false });

  const transactions = (transactionsData ?? []) as Transaction[];

  return (
    <main className="mx-auto max-w-lg px-4 pb-32 pt-6">
      <header className="mb-5 flex items-center justify-between">
        <div>
          <Link href="/" className="text-xl font-800">
            🐷 おこづかいちょう
          </Link>
          <p className="text-xs text-ink/50">
            {member.display_name} さん（{member.role === "editor" ? "記録できます" : "見るだけ"}）としてログイン中
          </p>
        </div>
        <LogoutButton />
      </header>

      <ChildTabs children={children} selectedChildId={selectedChildId} />

      <div className="mt-5">
        <SummaryCards transactions={transactions} />
      </div>

      <div className="mt-6">
        <MonthlyTable transactions={transactions} />
      </div>

      <div className="mt-6">
        <TransactionBoard
          initialTransactions={transactions}
          child={selectedChild}
          children={children}
          role={member.role}
          currentUserName={member.display_name}
          currentUserEmail={member.email}
        />
      </div>
    </main>
  );
}
