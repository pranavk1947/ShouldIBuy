import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShouldIBuy — Is this a fair price?",
  description:
    "Paste a used-item listing URL and get a fast, buyer-side verdict: is the price fair, and how should you negotiate?",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">{children}</div>
      </body>
    </html>
  );
}
