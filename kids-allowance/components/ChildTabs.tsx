import Link from "next/link";
import type { Child } from "@/lib/types";

export default function ChildTabs({
  children,
  selectedChildId,
}: {
  children: Child[];
  selectedChildId: string;
}) {
  return (
    <div className="flex gap-2">
      {children.map((child) => {
        const active = child.id === selectedChildId;
        return (
          <Link
            key={child.id}
            href={`/?child=${child.id}`}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl2 border-2 py-3 text-base font-bold transition ${
              active
                ? "border-transparent text-white shadow-md"
                : "border-ink/10 bg-white text-ink/50"
            }`}
            style={active ? { backgroundColor: child.color } : undefined}
          >
            <span className="text-xl">{child.emoji}</span>
            {child.name}
          </Link>
        );
      })}
    </div>
  );
}
