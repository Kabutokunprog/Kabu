"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { Child, Role, Transaction } from "@/lib/types";
import { formatYen } from "@/lib/aggregate";
import SummaryCards from "@/components/SummaryCards";
import MonthlyTable from "@/components/MonthlyTable";
import QuickAddSheet, { type QuickAddPayload } from "@/components/QuickAddSheet";

const QUICK_AMOUNTS = [100, 500, 1000, 10000];

function todayStr() {
  const d = new Date();
  const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return tz.toISOString().slice(0, 10);
}

function formatDate(dateStr: string) {
  const [, m, d] = dateStr.split("-");
  return `${Number(m)}/${Number(d)}`;
}

export default function Dashboard({
  children,
  initialTransactions,
  role,
  currentUserName,
  currentUserEmail,
  defaultChildId,
}: {
  children: Child[];
  initialTransactions: Transaction[];
  role: Role;
  currentUserName: string;
  currentUserEmail: string;
  defaultChildId: string;
}) {
  const router = useRouter();
  const isEditor = role === "editor";

  const [selectedChildId, setSelectedChildId] = useState(defaultChildId);
  const [transactions, setTransactions] = useState(initialTransactions);
  const [type, setType] = useState<"give" | "return">("give");
  const [amountText, setAmountText] = useState("");
  const [purposeText, setPurposeText] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);

  useEffect(() => {
    setTransactions(initialTransactions);
  }, [initialTransactions]);

  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(null), 1800);
    return () => clearTimeout(timer);
  }, [flash]);

  // 他の人がスマホ・PCで記録を追加/削除/修正したら、こちらの画面も自動で最新にする
  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("allowance_transactions_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "allowance_transactions" },
        () => router.refresh()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedChild = children.find((c) => c.id === selectedChildId) ?? children[0];
  const childTransactions = transactions.filter((t) => t.child_id === selectedChildId);

  const amountNumber = Number(amountText);
  const canQuickSave = amountNumber > 0 && Number.isFinite(amountNumber);

  async function confirmSave() {
    if (busy || !canQuickSave) return;
    setBusy(true);
    setErrorMessage(null);
    const supabase = createClient();
    const { error } = await supabase.from("allowance_transactions").insert({
      child_id: selectedChildId,
      amount: type === "give" ? amountNumber : -amountNumber,
      category: type === "give" ? "お小遣い" : "返却",
      purpose: purposeText.trim() || null,
      occurred_on: todayStr(),
      created_by_email: currentUserEmail,
      created_by_name: currentUserName,
    });
    setBusy(false);
    if (error) {
      setErrorMessage("保存に失敗しました。もう一度お試しください。");
      return;
    }
    setFlash(`${selectedChild.name}に ${type === "give" ? "+" : "-"}${formatYen(amountNumber)} きろくしました`);
    setAmountText("");
    setPurposeText("");
    router.refresh();
  }

  async function handleSheetSubmit(payload: QuickAddPayload) {
    setBusy(true);
    setErrorMessage(null);
    const supabase = createClient();

    const { error } = editing
      ? await supabase
          .from("allowance_transactions")
          .update({
            child_id: payload.childId,
            amount: payload.amount,
            category: payload.category,
            purpose: payload.purpose,
            occurred_on: payload.occurredOn,
          })
          .eq("id", editing.id)
      : await supabase.from("allowance_transactions").insert({
          child_id: payload.childId,
          amount: payload.amount,
          category: payload.category,
          purpose: payload.purpose,
          occurred_on: payload.occurredOn,
          created_by_email: currentUserEmail,
          created_by_name: currentUserName,
        });

    setBusy(false);
    if (error) {
      setErrorMessage("保存に失敗しました。もう一度お試しください。");
      return;
    }
    setSheetOpen(false);
    setEditing(null);
    router.refresh();
  }

  async function handleDelete(id: string) {
    if (!confirm("このきろくを削除しますか？")) return;
    const supabase = createClient();
    const { error } = await supabase.from("allowance_transactions").delete().eq("id", id);
    if (error) {
      setErrorMessage("削除に失敗しました。もう一度お試しください。");
      return;
    }
    router.refresh();
  }

  return (
    <div>
      <div className="flex gap-2">
        {children.map((c) => {
          const active = c.id === selectedChildId;
          return (
            <button
              key={c.id}
              onClick={() => setSelectedChildId(c.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-xl2 border-2 py-3 text-base font-bold transition active:scale-95 ${
                active ? "border-transparent text-white shadow-md" : "border-ink/10 bg-white text-ink/50"
              }`}
              style={active ? { backgroundColor: c.color } : undefined}
            >
              <span className="text-xl">{c.emoji}</span>
              {c.name}
            </button>
          );
        })}
      </div>

      <div className="mt-5">
        <SummaryCards transactions={childTransactions} />
      </div>

      <div className="mt-6">
        <MonthlyTable transactions={childTransactions} />
      </div>

      {isEditor && (
        <div className="mt-6 rounded-xl2 bg-white p-4 shadow-sm">
          {flash && (
            <div className="mb-3 rounded-lg bg-mint-soft px-3 py-2 text-center text-sm font-bold text-mint">
              ✓ {flash}
            </div>
          )}
          {errorMessage && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-center text-sm font-bold text-red-600">
              {errorMessage}
            </div>
          )}

          <div className="mb-3 flex gap-2">
            <button
              onClick={() => setType("give")}
              className={`flex-1 rounded-xl py-2 text-sm font-bold transition ${
                type === "give" ? "bg-mint text-white shadow-md" : "bg-mint-soft text-mint"
              }`}
            >
              あげた
            </button>
            <button
              onClick={() => setType("return")}
              className={`flex-1 rounded-xl py-2 text-sm font-bold transition ${
                type === "return" ? "bg-amber text-white shadow-md" : "bg-amber-soft text-amber"
              }`}
            >
              戻ってきた
            </button>
          </div>

          <p className="mb-2 text-xs font-bold text-ink/40">金額（タップすると足されます）</p>
          <div className="grid grid-cols-4 gap-2">
            {QUICK_AMOUNTS.map((amount) => (
              <button
                key={amount}
                onClick={() => setAmountText(String((Number(amountText) || 0) + amount))}
                className="rounded-xl border-2 border-primary-soft bg-primary-soft py-3 text-sm font-800 text-primary transition active:scale-95"
              >
                +{amount.toLocaleString("ja-JP")}
              </button>
            ))}
          </div>

          <div className="mt-2 flex gap-2">
            <input
              type="number"
              inputMode="numeric"
              min="1"
              step="1"
              value={amountText}
              onChange={(e) => setAmountText(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="金額を入力（1円単位でOK）"
              className="w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-2 text-base outline-none focus:border-primary"
            />
            {amountText !== "" && (
              <button
                onClick={() => setAmountText("")}
                className="shrink-0 rounded-xl border-2 border-ink/10 px-3 py-2 text-xs font-bold text-ink/50"
              >
                クリア
              </button>
            )}
          </div>

          <input
            type="text"
            value={purposeText}
            onChange={(e) => setPurposeText(e.target.value)}
            placeholder="目的・メモ（任意）例：おこづかい"
            className="mt-2 w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-2 text-base outline-none focus:border-primary"
          />

          <button
            disabled={busy || !canQuickSave}
            onClick={confirmSave}
            className="mt-3 w-full rounded-xl bg-primary py-3 text-base font-bold text-white shadow-md shadow-primary/30 transition active:scale-95 disabled:opacity-50"
          >
            {busy ? "保存中…" : "きろくする"}
          </button>

          <button
            onClick={() => {
              setEditing(null);
              setSheetOpen(true);
            }}
            className="mt-3 text-xs font-bold text-secondary underline underline-offset-2"
          >
            くわしく記録する（項目・メモ・Visaカードなど）
          </button>
        </div>
      )}

      <div className="mt-6">
        <p className="mb-3 text-xs font-bold text-ink/40">さいきんのきろく</p>

        {childTransactions.length === 0 ? (
          <div className="rounded-xl2 bg-white p-8 text-center text-sm text-ink/40">まだきろくがありません</div>
        ) : (
          <ul className="space-y-2">
            {childTransactions.map((t) => {
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
      </div>

      {isEditor && (
        <QuickAddSheet
          open={sheetOpen}
          onClose={() => {
            setSheetOpen(false);
            setEditing(null);
          }}
          onSubmit={handleSheetSubmit}
          submitting={busy}
          child={selectedChild}
          children={children}
          editingTransaction={editing}
        />
      )}
    </div>
  );
}
