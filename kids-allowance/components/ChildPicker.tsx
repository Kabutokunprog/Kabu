import Link from "next/link";
import type { Child } from "@/lib/types";
import LogoutButton from "@/components/LogoutButton";

export default function ChildPicker({
  children,
  displayName,
}: {
  children: Child[];
  displayName: string;
}) {
  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center px-6 py-12">
      <div className="mb-8 text-center">
        <div className="text-5xl">🐷</div>
        <h1 className="mt-2 text-2xl font-800">だれのきろく？</h1>
        <p className="mt-1 text-sm text-ink/50">{displayName} さん、選んでください</p>
      </div>

      <div className="grid w-full grid-cols-2 gap-4">
        {children.map((child) => (
          <Link
            key={child.id}
            href={`/?child=${child.id}`}
            className="flex flex-col items-center gap-3 rounded-xl2 bg-white py-10 shadow-lg shadow-primary/10 transition active:scale-95"
          >
            <span
              className="flex h-20 w-20 items-center justify-center rounded-full text-4xl"
              style={{ backgroundColor: `${child.color}33` }}
            >
              {child.emoji}
            </span>
            <span className="text-lg font-800">{child.name}</span>
          </Link>
        ))}
      </div>

      <div className="mt-10">
        <LogoutButton />
      </div>
    </main>
  );
}
