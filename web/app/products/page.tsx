"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
type Product={product_key:string;manufacturer:string;model:string;title:string;status:string;updated_at:number}
export default function ProductsPage(){const q=useQuery({queryKey:["products"],queryFn:()=>api<Product[]>("/api/products")});return <section className="page"><div className="page-head"><div><h1>Product intelligence</h1><p>Reviewed products and reusable organizational evidence.</p></div></div><div className="panel">{q.data?.length?<div className="table-wrap"><table><thead><tr><th>Manufacturer</th><th>Model</th><th>Product</th><th>Status</th></tr></thead><tbody>{q.data.map(p=><tr key={p.product_key}><td>{p.manufacturer}</td><td>{p.model}</td><td>{p.title}</td><td><span className="badge">{p.status}</span></td></tr>)}</tbody></table></div>:<div className="empty">No reviewed products yet.</div>}</div></section>}
