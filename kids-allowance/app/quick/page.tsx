import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentMember } from "@/lib/member";
import type { Child } from "@/lib/types";
import QuickAdd from "@/components/QuickAdd";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "クイック記録",
  manifest: null,
  appleWebApp: {
    capable: true,
    title: "クイック記録",
    statusBarStyle: "default",
  },
};

export default async function QuickPage() {
  const { member } = await getCurrentMember();

  if (!member) {
    redirect("/auth/no-access");
  }

  if (member.role !== "editor") {
    redirect("/");
  }

  const supabase = await createClient();

  const { data: childrenData } = await supabase
    .from("allowance_children")
    .select("id, name, emoji, color, sort_order")
    .order("sort_order", { ascending: true });

  const children = (childrenData ?? []) as Child[];

  if (children.length === 0) {
    redirect("/auth/no-access");
  }

  const defaultChildId =
    member.child_id && children.some((c) => c.id === member.child_id) ? member.child_id : children[0].id;

  return (
    <QuickAdd
      children={children}
      defaultChildId={defaultChildId}
      currentUserName={member.display_name}
      currentUserEmail={member.email}
    />
  );
}
