"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, FileSearch, FolderKanban, Gauge, Landmark, Search, Settings } from "lucide-react";

const nav = [
  ["/", "Dashboard", Gauge],
  ["/research", "Research", Search],
  ["/products", "Products", Boxes],
  ["/projects", "Projects", FolderKanban],
  ["/rfq", "RFQ & Quotes", Landmark],
  ["/system", "System", Settings],
] as const;

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return <div className="app-shell">
    <aside className="rail">
      <div className="brand"><div className="mark"><FileSearch size={20}/></div><div><b>Product Hunter</b><span>Enterprise Preview</span></div></div>
      <nav>{nav.map(([href,label,Icon]) => <Link key={href} href={href} className={path===href?"active":""}><Icon size={18}/><span>{label}</span></Link>)}</nav>
      <div className="rail-footer"><span className="status-dot"/> Phase 2 connected</div>
    </aside>
    <main className="main"><header className="topbar"><div><strong>Procurement Intelligence</strong><span>React + FastAPI foundation</span></div><button className="ghost">Command palette&nbsp; <kbd>Ctrl K</kbd></button></header>{children}</main>
  </div>
}
