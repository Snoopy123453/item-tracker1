"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Metric } from "@/components/metric";

type Dashboard={metrics:{verifiedProducts:number;researchRuns:number;cachedQueries:number;needsReview:number};recentRuns:Record<string,unknown>[];recentProducts:Record<string,unknown>[]}
export default function DashboardPage(){
 const q=useQuery({queryKey:["dashboard"],queryFn:()=>api<Dashboard>("/api/dashboard")});
 const m=q.data?.metrics;
 return <section className="page"><div className="page-head"><div><h1>Executive dashboard</h1><p>Live operational view of research, evidence, and product approvals.</p></div><button className="button">New research</button></div>
 <div className="grid4"><Metric label="Verified products" value={m?.verifiedProducts??"—"}/><Metric label="Research runs" value={m?.researchRuns??"—"}/><Metric label="Cached queries" value={m?.cachedQueries??"—"}/><Metric label="Needs review" value={m?.needsReview??"—"}/></div>
 <div className="panel"><h2>Phase 2 architecture</h2><p>The React workspace now talks to a standalone FastAPI service. The existing Streamlit application remains available as the legacy admin console during migration.</p></div>
 </section>
}
