import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentMember } from "@/lib/member";
import type { Child, Transaction } from "@/lib/types";
import Dashboard from "@/components/Dashboard";
import LogoutButton from "@/components/LogoutButton";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
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

  const { data: transactionsData } = await supabase
    .from("allowance_transactions")
    .select("id, child_id, amount, category, purpose, occurred_on, created_by_email, created_by_name, created_at")
    .order("occurred_on", { ascending: false })
    .order("created_at", { ascending: false });

  const transactions = (transactionsData ?? []) as Transaction[];

  const defaultChildId =
    member.child_id && children.some((c) => c.id === member.child_id) ? member.child_id : children[0].id;

  return (
    <main className="mx-auto max-w-lg px-4 pb-16 pt-6">
      <header className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-800">🐷 おこづかいちょう</h1>
          <p className="text-xs text-ink/50">
            {member.display_name} さん（{member.role === "editor" ? "記録できます" : "見るだけ"}）としてログイン中
          </p>
        </div>
        <LogoutButton />
      </header>

      <Dashboard
        children={children}
        initialTransactions={transactions}
        role={member.role}
        currentUserName={member.display_name}
        currentUserEmail={member.email}
        defaultChildId={defaultChildId}
      />
    </main>
  );
}
