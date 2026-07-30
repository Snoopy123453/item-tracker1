"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Job={id:string;status:string;query:string;progress:number;stage:string;results:Record<string,unknown>[];warnings:string[];error?:string|null}
export default function ResearchPage(){
 const [query,setQuery]=useState(""); const [jobId,setJobId]=useState<string|null>(null);
 const create=useMutation({mutationFn:()=>api<Job>("/api/research",{method:"POST",body:JSON.stringify({query,depth:"Standard",max_results:30})}),onSuccess:j=>setJobId(j.id)});
 const job=useQuery({queryKey:["job",jobId],queryFn:()=>api<Job>(`/api/research/${jobId}`),enabled:!!jobId,refetchInterval:q=>["completed","failed"].includes(q.state.data?.status??"")?false:1200});
 useEffect(()=>{if(job.data?.status==="failed") console.error(job.data.error)},[job.data]);
 return <section className="page"><div className="page-head"><div><h1>AI product research</h1><p>Launch background research and keep working while the API orchestrates providers.</p></div></div>
 <div className="panel"><div className="form-row"><input className="input" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Manufacturer, model, description, or product requirement"/><select className="select"><option>Standard</option><option>Deep</option></select><button className="button" disabled={query.trim().length<2||create.isPending} onClick={()=>create.mutate()}>Research</button></div>
 {job.data&&<><div style={{display:"flex",justifyContent:"space-between",marginTop:18}}><span>{job.data.stage}</span><span>{job.data.progress}%</span></div><div className="progress"><i style={{width:`${job.data.progress}%`}}/></div></>}
 {job.data?.warnings?.map((w,i)=><div className="alert" key={i}>{w}</div>)}</div>
 <div className="panel"><h2>Evidence results</h2>{job.data?.results?.length?<div className="table-wrap"><table><thead><tr><th>Title</th><th>Source</th><th>Type</th><th>Score</th></tr></thead><tbody>{job.data.results.map((r,i)=><tr key={i}><td>{String(r.title??"")}</td><td>{String(r.source_name??"")}</td><td><span className="badge">{String(r.source_type??"")}</span></td><td>{String(r.overall_score??"")}</td></tr>)}</tbody></table></div>:<div className="empty">Run research to build an evidence set.</div>}</div>
 </section>
}
