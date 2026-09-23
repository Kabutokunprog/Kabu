import LogoutButton from "@/components/LogoutButton";

export default function NoAccessPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm rounded-xl2 bg-white p-8 text-center shadow-lg shadow-primary/10">
        <div className="text-5xl">🔒</div>
        <h1 className="mt-3 text-lg font-800">このアカウントは登録されていません</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink/60">
          このおこづかいちょうは、登録されたご家族のメールアドレスだけが使えます。
          <br />
          心当たりがない場合は管理者（パパ・ママ）にご確認ください。
        </p>
        <div className="mt-6">
          <LogoutButton />
        </div>
      </div>
    </main>
  );
}
