"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("sending");
    setErrorMessage("");

    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setStatus("error");
      setErrorMessage("送信に失敗しました。もう一度お試しください。");
      return;
    }
    setStatus("sent");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm rounded-xl2 bg-white p-8 shadow-lg shadow-primary/10">
        <div className="mb-6 text-center">
          <div className="text-5xl">🐷</div>
          <h1 className="mt-2 text-2xl font-800">おこづかいちょう</h1>
          <p className="mt-1 text-sm text-ink/60">かぞくの おこづかい きろく</p>
        </div>

        {status === "sent" ? (
          <div className="rounded-xl2 bg-mint-soft p-5 text-center text-sm leading-relaxed text-ink">
            <p className="text-2xl">📩</p>
            <p className="mt-2 font-bold">メールを送りました！</p>
            <p className="mt-1 text-ink/70">
              {email} 宛にログイン用のリンクを送りました。メールを開いてリンクをタップしてください。
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-bold text-ink/70">
                メールアドレス
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="example@gmail.com"
                className="w-full rounded-xl border-2 border-primary-soft bg-cream px-4 py-3 text-base outline-none focus:border-primary"
              />
            </div>

            {status === "error" && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{errorMessage}</p>
            )}

            <button
              type="submit"
              disabled={status === "sending"}
              className="w-full rounded-xl bg-primary px-4 py-3 text-base font-bold text-white shadow-md shadow-primary/30 transition active:scale-95 disabled:opacity-60"
            >
              {status === "sending" ? "送信中…" : "ログインリンクを送る"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
