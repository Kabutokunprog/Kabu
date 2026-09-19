"use client";

import { useEffect, useState } from "react";
import type { Child, Transaction } from "@/lib/types";

const QUICK_AMOUNTS = [100, 500, 1000, 10000];
const GIVE_CATEGORIES = ["お小遣い", "お手伝い", "お年玉", "ご褒美", "Visaカード", "その他"];
const RETURN_CATEGORIES = ["返却", "お小遣い", "その他"];

export type QuickAddPayload = {
  childId: string;
  amount: number; // signed
  category: string;
  purpose: string | null;
  occurredOn: string;
};

function todayStr() {
  const d = new Date();
  const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return tz.toISOString().slice(0, 10);
}

function monthStr() {
  return todayStr().slice(0, 7);
}

export default function QuickAddSheet({
  open,
  onClose,
  onSubmit,
  submitting,
  child,
  children,
  editingTransaction,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: QuickAddPayload) => void;
  submitting: boolean;
  child: Child;
  children: Child[];
  editingTransaction: Transaction | null;
}) {
  const [childId, setChildId] = useState(child.id);
  const [type, setType] = useState<"give" | "return">("give");
  const [amountText, setAmountText] = useState("");
  const [category, setCategory] = useState<string>("お小遣い");
  const [purpose, setPurpose] = useState("");
  const [occurredOn, setOccurredOn] = useState(todayStr());
  const [showDate, setShowDate] = useState(false);
  const [monthValue, setMonthValue] = useState(monthStr());

  useEffect(() => {
    if (!open) return;
    if (editingTransaction) {
      setChildId(editingTransaction.child_id);
      setType(editingTransaction.amount < 0 ? "return" : "give");
      setAmountText(String(Math.abs(editingTransaction.amount)));
      setCategory(editingTransaction.category);
      setPurpose(editingTransaction.purpose ?? "");
      setOccurredOn(editingTransaction.occurred_on);
      setMonthValue(editingTransaction.occurred_on.slice(0, 7));
      setShowDate(true);
    } else {
      setChildId(child.id);
      setType("give");
      setAmountText("");
      setCategory("お小遣い");
      setPurpose("");
      setOccurredOn(todayStr());
      setMonthValue(monthStr());
      setShowDate(false);
    }
  }, [open, editingTransaction, child.id]);

  if (!open) return null;

  const categories = type === "give" ? GIVE_CATEGORIES : RETURN_CATEGORIES;
  const isCardMode = category === "Visaカード";
  const amountNumber = Number(amountText);
  const canSubmit = amountNumber > 0 && Number.isFinite(amountNumber) && (!isCardMode || monthValue !== "");

  function handleSubmit() {
    if (!canSubmit) return;
    onSubmit({
      childId,
      amount: type === "give" ? amountNumber : -amountNumber,
      category,
      purpose: purpose.trim() || null,
      occurredOn: isCardMode ? `${monthValue}-01` : occurredOn,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 sm:items-center" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-xl2 bg-white p-5 shadow-2xl sm:rounded-xl2"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-800">{editingTransaction ? "きろくを直す" : "きろくする"}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-ink/40">
            ×
          </button>
        </div>

        {children.length > 1 && (
          <div className="mb-4 flex gap-2">
            {children.map((c) => (
              <button
                key={c.id}
                onClick={() => setChildId(c.id)}
                className={`flex-1 rounded-xl border-2 py-2 text-sm font-bold transition ${
                  childId === c.id ? "border-transparent text-white" : "border-ink/10 text-ink/50"
                }`}
                style={childId === c.id ? { backgroundColor: c.color } : undefined}
              >
                {c.emoji} {c.name}
              </button>
            ))}
          </div>
        )}

        <div className="mb-4 flex gap-2">
          <button
            onClick={() => setType("give")}
            className={`flex-1 rounded-xl py-3 text-base font-bold transition ${
              type === "give" ? "bg-mint text-white shadow-md" : "bg-mint-soft text-mint"
            }`}
          >
            あげた
          </button>
          <button
            onClick={() => setType("return")}
            className={`flex-1 rounded-xl py-3 text-base font-bold transition ${
              type === "return" ? "bg-amber text-white shadow-md" : "bg-amber-soft text-amber"
            }`}
          >
            戻ってきた
          </button>
        </div>

        <p className="mb-2 text-xs font-bold text-ink/40">金額（タップすると足されます）</p>
        <div className="mb-2 grid grid-cols-4 gap-2">
          {QUICK_AMOUNTS.map((amount) => (
            <button
              key={amount}
              onClick={() =>
                setAmountText(String((Number(amountText) || 0) + amount))
              }
              className="rounded-xl border-2 border-primary-soft bg-primary-soft py-2 text-sm font-800 text-primary transition active:scale-95"
            >
              +{amount.toLocaleString("ja-JP")}
            </button>
          ))}
        </div>
        <div className="mb-4 flex items-center gap-2">
          <input
            type="number"
            inputMode="numeric"
            min="1"
            step="1"
            value={amountText}
            onChange={(e) => setAmountText(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder={type === "return" ? "金額を入力（1円単位でOK）" : "金額を入力（円）"}
            className="w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-3 text-base outline-none focus:border-primary"
          />
          {amountText !== "" && (
            <button
              onClick={() => setAmountText("")}
              className="shrink-0 rounded-xl border-2 border-ink/10 px-3 py-3 text-xs font-bold text-ink/50"
            >
              クリア
            </button>
          )}
        </div>

        <p className="mb-2 text-xs font-bold text-ink/40">項目</p>
        <div className="mb-4 flex flex-wrap gap-2">
          {categories.map((c) => {
            const isVisa = c === "Visaカード";
            return (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`rounded-full border-2 px-3 py-1.5 text-sm font-bold transition ${
                  category === c
                    ? isVisa
                      ? "border-[#1A1F71] bg-[#1A1F71] text-white"
                      : "border-secondary bg-secondary-soft text-secondary"
                    : isVisa
                      ? "border-[#1A1F71]/40 text-[#1A1F71]"
                      : "border-ink/10 text-ink/50"
                }`}
              >
                {isVisa ? "💳 Visa" : c}
              </button>
            );
          })}
        </div>

        <p className="mb-2 text-xs font-bold text-ink/40">目的・メモ（任意）</p>
        <input
          type="text"
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="例：友だちの誕生日プレゼント"
          className="mb-4 w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-3 text-base outline-none focus:border-primary"
        />

        {isCardMode ? (
          <div className="mb-4 rounded-xl2 bg-secondary-soft p-4">
            <p className="mb-2 text-xs font-bold text-secondary">💳 何月分の明細？</p>
            <input
              type="month"
              value={monthValue}
              onChange={(e) => setMonthValue(e.target.value)}
              className="w-full rounded-xl border-2 border-ink/10 bg-white px-4 py-3 text-base outline-none focus:border-secondary"
            />
            <p className="mt-2 text-[11px] text-ink/50">
              カード明細をまとめて、その月の記録として登録します。日付は自動でその月の1日になります。
            </p>
          </div>
        ) : showDate ? (
          <div className="mb-4">
            <p className="mb-2 text-xs font-bold text-ink/40">日付</p>
            <input
              type="date"
              value={occurredOn}
              onChange={(e) => setOccurredOn(e.target.value)}
              className="w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-3 text-base outline-none focus:border-primary"
            />
          </div>
        ) : (
          <button
            onClick={() => setShowDate(true)}
            className="mb-4 text-xs font-bold text-secondary underline underline-offset-2"
          >
            日付を変更する（今日以外）
          </button>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit || submitting}
          className="w-full rounded-xl bg-primary py-3 text-base font-bold text-white shadow-md shadow-primary/30 transition active:scale-95 disabled:opacity-50"
        >
          {submitting ? "保存中…" : "保存する"}
        </button>
      </div>
    </div>
  );
}
