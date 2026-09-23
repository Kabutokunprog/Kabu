"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import type { Child } from "@/lib/types";
import { formatYen } from "@/lib/aggregate";

const QUICK_AMOUNTS = [100, 500, 1000, 10000];

function todayStr() {
  const d = new Date();
  const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return tz.toISOString().slice(0, 10);
}

export default function QuickAdd() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [kids, setKids] = useState<Child[]>([]);
  const [currentUserName, setCurrentUserName] = useState("");
  const [currentUserEmail, setCurrentUserEmail] = useState("");

  const [childId, setChildId] = useState("");
  const [type, setType] = useState<"give" | "return">("give");
  const [amountText, setAmountText] = useState("");
  const [purposeText, setPurposeText] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      const supabase = createClient();

      // ログイン直後はCookieの反映に一瞬のズレが出ることがあるため、
      // getUser()でサーバーに問い合わせて確実な認証状態を取得する
      const {
        data: { user },
      } = await supabase.auth.getUser();
      const email = user?.email;

      if (!email) {
        router.replace("/login");
        return;
      }

      // 同じ理由で、メンバー情報の取得も数回までリトライしてから
      // 「未登録」と判断する(ログイン直後の一回だけ空で返ってくることがある)
      let memberData: { display_name: string; role: string; child_id: string | null } | null = null;
      let childrenData: Child[] | null = null;
      for (let attempt = 0; attempt < 3 && active; attempt++) {
        const [memberRes, childrenRes] = await Promise.all([
          supabase.from("allowance_members").select("display_name, role, child_id").eq("email", email).maybeSingle(),
          supabase
            .from("allowance_children")
            .select("id, name, emoji, color, sort_order")
            .order("sort_order", { ascending: true }),
        ]);
        memberData = memberRes.data;
        childrenData = (childrenRes.data ?? []) as Child[];
        if (memberData) break;
        await new Promise((resolve) => setTimeout(resolve, 400));
      }

      if (!active) return;

      if (!memberData) {
        router.replace("/auth/no-access");
        return;
      }
      if (memberData.role !== "editor") {
        router.replace("/");
        return;
      }

      const list = childrenData ?? [];
      if (list.length === 0) {
        router.replace("/auth/no-access");
        return;
      }

      setKids(list);
      setChildId(
        memberData.child_id && list.some((c) => c.id === memberData.child_id) ? memberData.child_id : list[0].id
      );
      setCurrentUserName(memberData.display_name);
      setCurrentUserEmail(email);
      setLoading(false);
    }

    load();
    return () => {
      active = false;
    };
  }, [router]);

  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(null), 1600);
    return () => clearTimeout(timer);
  }, [flash]);

  const selectedChild = kids.find((c) => c.id === childId) ?? kids[0];
  const amountNumber = Number(amountText);
  const canSave = amountNumber > 0 && Number.isFinite(amountNumber);

  async function handleSave() {
    if (busy || !canSave) return;
    setBusy(true);
    setErrorMessage(null);
    const supabase = createClient();
    const { error } = await supabase.from("allowance_transactions").insert({
      child_id: childId,
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
  }

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center px-4 py-6">
        <p className="text-3xl">🐶</p>
        <p className="mt-2 text-sm text-ink/40">よみこみ中…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4 py-6">
      <h1 className="mb-5 text-center text-lg font-800">🐶 クイック記録</h1>

      {kids.length > 1 && (
        <div className="mb-4 flex gap-2">
          {kids.map((c) => (
            <button
              key={c.id}
              onClick={() => setChildId(c.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-xl2 border-2 py-4 text-lg font-bold transition active:scale-95 ${
                childId === c.id ? "border-transparent text-white shadow-md" : "border-ink/10 bg-white text-ink/50"
              }`}
              style={childId === c.id ? { backgroundColor: c.color } : undefined}
            >
              <span className="text-2xl">{c.emoji}</span>
              {c.name}
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

      <p className="mb-2 text-xs font-bold text-ink/40">金額（タップすると足されます）</p>
      <div className="grid grid-cols-4 gap-2">
        {QUICK_AMOUNTS.map((amount) => (
          <button
            key={amount}
            onClick={() => setAmountText(String((Number(amountText) || 0) + amount))}
            className="rounded-xl border-2 border-primary-soft bg-primary-soft py-4 text-sm font-800 text-primary transition active:scale-95"
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
          autoFocus
          value={amountText}
          onChange={(e) => setAmountText(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder="金額を入力（円）"
          className="w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-4 text-xl font-800 outline-none focus:border-primary"
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
        className="mt-2 w-full rounded-xl border-2 border-ink/10 bg-cream px-4 py-3 text-base outline-none focus:border-primary"
      />

      <button
        disabled={busy || !canSave}
        onClick={handleSave}
        className="mt-4 w-full rounded-xl bg-primary py-4 text-lg font-800 text-white shadow-md shadow-primary/30 transition active:scale-95 disabled:opacity-50"
      >
        {busy ? "保存中…" : "きろくする"}
      </button>

      <Link href="/" className="mt-6 text-center text-xs font-bold text-secondary underline underline-offset-2">
        ダッシュボードを見る →
      </Link>
    </main>
  );
}
