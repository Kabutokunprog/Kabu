import { createClient } from "@/lib/supabase/server";
import type { Member } from "@/lib/types";

export async function getCurrentMember(): Promise<{
  email: string | null;
  member: Member | null;
}> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user?.email) {
    return { email: null, member: null };
  }

  const { data } = await supabase
    .from("allowance_members")
    .select("id, email, display_name, role, child_id")
    .eq("email", user.email)
    .maybeSingle();

  return { email: user.email, member: (data as Member) ?? null };
}
