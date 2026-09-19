"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { Child, Role, Transaction } from "@/lib/types";
import { formatYen } from "@/lib/aggregate";
import QuickAddSheet, { type QuickAddPayload } from "@/components/QuickAddSheet";

export default function TransactionBoard({
  initialTransactions,
  child,
  children,
  role,
  currentUserName,
  currentUserEmail,
}: {
  initialTransactions: Transaction[];
  child: Child;
  children: Child[];
  role: Role;
  currentUserName: string;
  currentUserEmail: string;
}) {
  const router = useRouter();
  const [transactions, setTransactions] = useState(initialTransactions);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const isEditor = role === "editor";

  useEffect(() => {
    setTransactions(initialTransactions);
  }, [initialTransactions]);

  async function handleSubmit(payload: QuickAddPayload) {
    setSubmitting(true);
    const supabase = createClient();

    if (editing) {
      await supabase
        .from("allowance_transactions")
        .update({
          child_id: payload.childId,
          amount: payload.amount,
          category: payload.category,
          purpose: payload.purpose,
          occurred_on: payload.occurredOn,
        })
        .eq("id", editing.id);
    } else {
      await supabase.from("allowance_transactions").insert({
        child_id: payload.childId,
        amount: payload.amount,
        category: payload.category,
        purpose: payload.purpose,
        occurred_on: payload.occurredOn,
        created_by_email: currentUserEmail,
        created_by_name: currentUserName,
      });
    }

    setSubmitting(false);
    setSheetOpen(false);
    setEditing(null);
    router.refresh();
  }

  async function handleDelete(id: string) {
    if (!confirm("このきろくを削除しますか？")) return;
    const supabase = createClient();
    await supabase.from("allowance_transactions").delete().eq("id", id);
    router.refresh();
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-bold text-ink/40">さいきんのきろく</p>
      </div>

      {transactions.length === 0 ? (
        <div className="rounded-xl2 bg-white p-8 text-center text-sm text-ink/40">
          まだきろくがありません
        </div>
      ) : (
        <ul className="space-y-2">
          {transactions.map((t) => {
            const isReturn = t.amount < 0;
            return (
              <li
                key={t.id}
                onClick={() => {
                  if (!isEditor) return;
                  setEditing(t);
                  setSheetOpen(true);
                }}
                className={`flex items-center justify-between rounded-xl2 bg-white p-4 shadow-sm ${
                  isEditor ? "cursor-pointer active:scale-[0.99]" : ""
                }`}
              >
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
                <div className="flex items-center gap-2 pl-3">
                  <span className={`text-lg font-800 ${isReturn ? "text-amber" : "text-mint"}`}>
                    {isReturn ? "-" : "+"}
                    {formatYen(Math.abs(t.amount))}
                  </span>
                  {isEditor && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(t.id);
                      }}
                      className="rounded-lg px-2 py-1 text-ink/20 transition hover:bg-red-50 hover:text-red-400"
                      aria-label="削除"
                    >
                      🗑
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {isEditor && (
        <button
          onClick={() => {
            setEditing(null);
            setSheetOpen(true);
          }}
          className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full bg-primary px-8 py-4 text-base font-800 text-white shadow-xl shadow-primary/40 transition active:scale-95"
        >
          ＋ きろくする
        </button>
      )}

      <QuickAddSheet
        open={sheetOpen}
        onClose={() => {
          setSheetOpen(false);
          setEditing(null);
        }}
        onSubmit={handleSubmit}
        submitting={submitting}
        child={child}
        children={children}
        editingTransaction={editing}
      />
    </div>
  );
}

function formatDate(dateStr: string) {
  const [, m, d] = dateStr.split("-");
  return `${Number(m)}/${Number(d)}`;
}
