export default async function ConfirmPage({
  searchParams,
}: {
  searchParams: Promise<{ confirmation_url?: string }>;
}) {
  const { confirmation_url } = await searchParams;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm rounded-xl2 bg-white p-8 text-center shadow-lg shadow-primary/10">
        <div className="text-5xl">🐷</div>
        {confirmation_url ? (
          <>
            <h1 className="mt-3 text-lg font-800">もう少しです！</h1>
            <p className="mt-2 text-sm leading-relaxed text-ink/60">
              下のボタンを押して、ログインを完了してください。
            </p>
            <a
              href={confirmation_url}
              className="mt-6 inline-block w-full rounded-xl bg-primary px-4 py-3 text-base font-bold text-white shadow-md shadow-primary/30 transition active:scale-95"
            >
              ログインする
            </a>
          </>
        ) : (
          <>
            <h1 className="mt-3 text-lg font-800">リンクが正しくありません</h1>
            <p className="mt-2 text-sm leading-relaxed text-ink/60">
              お手数ですが、もう一度ログインをやり直してください。
            </p>
            <a
              href="/login"
              className="mt-6 inline-block w-full rounded-xl border-2 border-ink/10 px-4 py-3 text-base font-bold text-ink/60"
            >
              ログイン画面へ
            </a>
          </>
        )}
      </div>
    </main>
  );
}
