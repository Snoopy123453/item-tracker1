import "./globals.css";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
export const metadata = { title: "Product Hunter", description: "AI procurement workspace" };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body><Providers><Shell>{children}</Shell></Providers></body></html>;
}
