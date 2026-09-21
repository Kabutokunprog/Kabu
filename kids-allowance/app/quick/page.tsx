import type { Metadata } from "next";
import QuickAdd from "@/components/QuickAdd";

export const metadata: Metadata = {
  title: "クイック記録",
  appleWebApp: {
    capable: true,
    title: "クイック記録",
    statusBarStyle: "default",
  },
};

export default function QuickPage() {
  return <QuickAdd />;
}
