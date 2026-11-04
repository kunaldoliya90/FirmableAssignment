// Root layout: page metadata and the app shell
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/features/shell/AppShell";

import "./globals.css";

export const metadata: Metadata = {
  title: "OrgGraph",
  description: "Infer, explore and evaluate org charts from messy employee records.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
