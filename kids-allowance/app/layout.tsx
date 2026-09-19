import type { Metadata, Viewport } from "next";
import { M_PLUS_Rounded_1c } from "next/font/google";
import "./globals.css";

const rounded = M_PLUS_Rounded_1c({
  subsets: ["latin"],
  weight: ["400", "700", "800"],
  variable: "--font-rounded",
  display: "swap",
});

export const metadata: Metadata = {
  title: "おこづかいちょう",
  description: "咲太朗と芽依のおこづかい記録帳",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className={`${rounded.variable} font-rounded min-h-screen bg-cream text-ink`}>
        {children}
      </body>
    </html>
  );
}
