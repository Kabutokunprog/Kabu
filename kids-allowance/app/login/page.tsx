"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleGoogleLogin() {
    setLoading(true);
    setErrorMessage("");

    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setLoading(false);
      setErrorMessage("ログインに失敗しました。もう一度お試しください。");
    }
    // 成功時はGoogleのログイン画面へ遷移するため、ここでは何もしない
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm rounded-xl2 bg-white p-8 shadow-lg shadow-primary/10">
        <div className="mb-8 text-center">
          <div className="text-5xl">🐶</div>
          <h1 className="mt-2 text-2xl font-800">おこづかいちょう</h1>
          <p className="mt-1 text-sm text-ink/60">かぞくの おこづかい きろく</p>
        </div>

        {errorMessage && (
          <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{errorMessage}</p>
        )}

        <button
          onClick={handleGoogleLogin}
          disabled={loading}
          className="flex w-full items-center justify-center gap-3 rounded-xl border-2 border-ink/10 bg-white px-4 py-3 text-base font-bold text-ink shadow-sm transition active:scale-95 disabled:opacity-60"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="#4285F4"
              d="M23.49 12.27c0-.79-.07-1.54-.2-2.27H12v4.3h6.47a5.54 5.54 0 0 1-2.4 3.63v3h3.88c2.27-2.09 3.58-5.17 3.58-8.66z"
            />
            <path
              fill="#34A853"
              d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3c-1.08.72-2.45 1.15-4.05 1.15-3.11 0-5.75-2.1-6.69-4.93H1.3v3.09A12 12 0 0 0 12 24z"
            />
            <path
              fill="#FBBC05"
              d="M5.31 14.31A7.2 7.2 0 0 1 4.93 12c0-.8.14-1.58.38-2.31V6.6H1.3A12 12 0 0 0 0 12c0 1.94.46 3.78 1.3 5.4z"
            />
            <path
              fill="#EA4335"
              d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.44-3.44C17.94 1.19 15.24 0 12 0 7.31 0 3.25 2.69 1.3 6.6l4.01 3.09C6.25 6.85 8.89 4.75 12 4.75z"
            />
          </svg>
          {loading ? "ログイン中…" : "Googleでログイン"}
        </button>

        <p className="mt-4 text-center text-xs text-ink/40">
          登録されたご家族のGoogleアカウントだけがご利用いただけます
        </p>
      </div>
    </main>
  );
}
