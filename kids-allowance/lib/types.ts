export type Role = "editor" | "viewer";

export type Member = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  child_id: string | null;
};

export type Child = {
  id: string;
  name: string;
  emoji: string;
  color: string;
  sort_order: number;
};

export type Transaction = {
  id: string;
  child_id: string;
  amount: number;
  category: string;
  purpose: string | null;
  occurred_on: string;
  created_by_email: string;
  created_by_name: string;
  created_at: string;
};

export const CATEGORY_OPTIONS = ["お小遣い", "お手伝い", "お年玉", "ご褒美", "その他"] as const;
export const RETURN_CATEGORY = "返却";
