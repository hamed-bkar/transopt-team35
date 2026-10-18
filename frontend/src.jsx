import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const DEFAULT_ORDER = {
  customer:'', pickup_zone:'central', drop_zone:'burlington',cargo_type:'general', requested_vehicle:null,
  weight_kg:'',skids:'',length_cm:'',width_cm:'',height_cm:'',delivery_by:'16:00'
};
const DEFAULT_ZONES={central:'Trans Ontario depot • Scarborough',scarborough:'Scarborough, ON',toronto:'Toronto, ON',burlington:'Burlington, ON',niagara_falls:'Niagara Falls, ON',montreal:'Montréal, QC'};
const DEFAULT_CARGO={general:'General merchandise',ambient_food:'Non-refrigerated food',fragile:'Fragile / sensitive handling',temperature_sensitive:'Temperature controlled'};
const fmt = value => new Intl.NumberFormat('en-CA',{maximumFractionDigits:1}).format(Number(value||0));
const toLb = kg => Number(kg||0)*2.20462262185;
const cash = value => new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD'}).format(Number(value||0));
const time = mins => `${String(Math.floor(mins/60)).padStart(2,'0')}:${String(mins%60).padStart(2,'0')}`;

async function api(path, options={}){
  let response;
  try{response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}})}
  catch{throw new Error('Could not connect to FastAPI. Start the backend on port 8000.');}
  const body=await response.json().catch(()=>({}));
  if(!response.ok){
    let message=body.detail||body.error||`Request failed (${response.status})`;
    if(Array.isArray(message)) message=message.map(x=>`${x.loc?.at(-1)||'Field'}: ${x.msg}`).join('; ');
    throw new Error(message);
  }
  return body;
}

function Mark({type='box',size=18}){
 const paths={
  box:<><path d="M3 7 12 2l9 5v10l-9 5-9-5z"/><path d="m3 7 9 5 9-5M12 12v10"/></>,
  truck:<><path d="M2 6h12v12H2zM14 10h4l4 4v4h-8z"/><circle cx="7" cy="19" r="2"/><circle cx="18" cy="19" r="2"/></>,
  chart:<><path d="M3 3v18h18M7 16v-5M12 16V6M17 16v-8"/></>,
  plus:<path d="M12 4v16M4 12h16"/>,
  route:<><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h8a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h8"/></>,
  refresh:<><path d="M20 11a8 8 0 0 0-14-5L3 9M3 3v6h6M4 13a8 8 0 0 0 14 5l3-3M15 15h6v6"/></>,
  check:<path d="m4 12 5 5L20 6"/>,
  alert:<><path d="m12 2 10 19H2zM12 9v4M12 17h.01"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></>,
  chevron:<path d="m9 6 6 6-6 6"/>,
  delete:<><path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15M10 10v7M14 10v7"/></>,
  info:<><circle cx="12" cy="12" r="10"/><path d="M12 11v6M12 7h.01"/></>,
 };
 return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[type]||paths.box}</svg>;
}

function Notice({children,tone='info'}) {return <div className={'notice '+tone}><Mark type={tone==='error'?'alert':tone==='success'?'check':'info'}/><span>{children}</span></div>}
function Pill({children,tone='neutral'}) {return <span className={'pill '+tone}>{children}</span>}
function Metric({label,value,foot,icon}){return <div className="stat"><div className="stat-header"><span>{label}</span><span className="stat-icon"><Mark type={icon}/></span></div><strong>{value}</strong><div className="subdued">{foot}</div></div>}

function Overview({plan,orders,loading,onOptimize,onAbsent,onReset,absent,onStartRoute,onOpenMap}){
 const utilized=plan?.routes.filter(x=>x.shipments.length).length||0;
 const dynamicCount=orders.length;
 return <>
  <div className="page-head"><div><div className="eyebrow">DISPATCH CONTROL</div><h1>Command center</h1><p>Optimize shipment assignments and respond to new orders and driver disruptions.</p></div><div className="head-actions"><button onClick={onOptimize} disabled={loading}><Mark type="route"/>Optimize day</button><button className="outline" onClick={absent?onReset:onAbsent} disabled={loading}><Mark type="refresh"/>{absent?'Restore D01':'Simulate D01 absence'}</button></div></div>
  {absent&&<Notice tone="warn">Driver D01 is unavailable. Plans were recomputed without D01. This does not validate real substitute-driver qualifications.</Notice>}
  <div className="stats">
   <Metric label="Shipments assigned" value={plan?`${plan.assigned_count} / ${plan.total_shipments}`:'—'} foot="Under simplified demo constraints" icon="box"/>
   <Metric label="Delivering now" value={plan?.fleet_summary?.delivering??'—'} foot={`${plan?.fleet_summary?.available??0} dispatchable · ${plan?.fleet_summary?.standby??0} emergency standby`} icon="truck"/>
   <Metric label="Route distance" value={plan?plan.total_distance_units:'—'} foot="Fictional distance units, not km" icon="route"/>
   <Metric label="Unassigned" value={plan?.unassigned.length??'—'} foot={`${dynamicCount} new B2B order${dynamicCount===1?'':'s'} saved`} icon="alert"/>
  </div>
  <div className="dashboard-grid">
   <section className="panel"><div className="panel-head"><div><h2>Recommended dispatch plan</h2><p>Cheapest feasible insertion heuristic; not a globally optimal solution.</p></div>{plan&&<Pill tone="blue">{plan.routes.filter(r=>r.shipments.length).length} active routes</Pill>}</div>
    {plan?<div className="route-list">{plan.routes.map(r=><RouteCard key={r.vehicle} route={r} onStartRoute={onStartRoute} onOpenMap={onOpenMap} loading={loading}/>)}</div>:<div className="empty-state">Loading dispatch plan…</div>}
   </section>
   <aside className="right-stack"><section className="panel"><div className="panel-head"><h2>Planning insights</h2><Pill tone="blue">Explainable</Pill></div>
    <p className="insight-body">{absent?'D01 is absent. Remaining vehicles were evaluated for the affected shipment workload.':'Each new shipment is checked against available skid positions, reported weight limits, demo volume, driver hours and delivery deadlines at every stop.'}</p>
    <h3>Unassigned shipments</h3>{plan?.unassigned.length?<div className="issue-list">{plan.unassigned.map(issue=><div key={issue.shipment}><Pill tone="warn">{issue.shipment}</Pill><p>{issue.reason}</p></div>)}</div>:<p className="green-message"><Mark type="check"/> All shipments assigned under demo constraints.</p>}
    <h3>Operating assumptions</h3><ul className="assumptions">{(plan?.assumptions||[]).map(item=><li key={item}>{item}</li>)}</ul>
    </section><section className="panel micro"><h2>New order integration</h2><p>Orders submitted from the B2B portal join the planner as new pickups and deliveries.</p><div className="micro-row"><strong>{dynamicCount}</strong><span>orders saved to the demo database</span></div></section></aside>
  </div>
 </>;
}
function RouteCard({route,onStartRoute,onOpenMap,loading}){
 const [open,setOpen]=useState(false);
 return <div className="route-card"><div className="route-primary"><div className="truck-label"><span className="truck-avatar"><Mark type="truck"/></span><div><b>{route.vehicle}</b><small>Driver {route.driver}</small><DispatchStatus route={route}/></div></div><div className="route-content"><div className="route-chips">{route.stop_sequence.length?route.stop_sequence.map((stop,i)=><span className={'stop-chip '+(stop.startsWith('P:')?'pickup':'')} key={i}>{stop}</span>):<span className="subdued">Idle / backup capacity</span>}</div><div className="route-sub">Peak: {route.peak_skids}/{route.skid_limit} skids · {fmt(route.peak_weight_lb)} / {fmt(route.weight_limit_lb)} lb · {route.volume_m3} / {route.volume_limit_m3} m³ <br/>{route.truck_type} · {minuteDuration(route.driver_hours.scheduled_on_duty_min)} / 13h modeled duty</div></div><div className="route-end"><b>{route.distance_units}</b><small>demo units</small></div><div className="route-card-actions"><button type="button" className="mini-map-action" onClick={()=>onOpenMap(route.vehicle)}><Mark type="route"/> Map</button>{route.dispatch_status==='available'&&route.shipments.length>0&&<button type="button" className="mini-start-action" disabled={loading} onClick={()=>onStartRoute(route.vehicle)}><Mark type="check"/> Start route</button>}</div><button className="icon-button" onClick={()=>setOpen(!open)} aria-label={open?'Hide stop details':'Show stop details'}>{open?'−':'+'}</button></div>
 {open&&<div className="stop-details">{route.events.length?<div className="table-wrap"><table><thead><tr><th>Stop</th><th>Action</th><th>ETA</th><th>Skids on board</th><th>Weight on board</th><th>Volume on board</th></tr></thead><tbody>{route.events.map((e,i)=><tr key={i}><td>{e.shipment}</td><td>{e.type==='pickup'?<Pill tone="blue">Pickup</Pill>:<Pill tone="green">Drop-off</Pill>}</td><td>{time(e.eta_min)}</td><td>{e.onboard_skids}/{route.skid_limit}</td><td>{fmt(e.onboard_weight_lb)} lb</td><td>{e.onboard_volume_m3} m³</td></tr>)}</tbody></table></div>:<p>This truck is idle. It may be considered for backup assignments.</p>}<p className="subdued">Scheduled finish (including return to demo depot): {time(route.finish_min)}. Shift checks are simplified.</p></div>}
 </div>;
}

function NumberInput({label,name,value,onChange,placeholder,required}){return <label className="form-field"><span>{label} {required&&<em>*</em>}</span><input type="number" min="0.01" step="any" name={name} placeholder={placeholder} value={value} onChange={e=>onChange(name,e.target.value)}/></label>}
function NewOrder({onCreated,meta}){
 const [order,setOrder]=useState({...DEFAULT_ORDER});
 const [quote,setQuote]=useState(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [success,setSuccess]=useState(null);
 const [preview,setPreview]=useState(null);
 const zones=meta?.zones||DEFAULT_ZONES,cargo=meta?.cargo_types||DEFAULT_CARGO;
 const setField=(key,value)=>{setOrder(prev=>({...prev,[key]:value}));setQuote(null);setPreview(null);setError('');setSuccess(null)};
 const payload=()=>Object.fromEntries(Object.entries(order).map(([key,val])=>[key,["weight_kg","skids","length_cm","width_cm","height_cm"].includes(key)?(val===''?null:Number(val)):val]));
 const requestQuote=async e=>{e?.preventDefault();setBusy(true);setError('');try{const q=await api('/quote',{method:'POST',body:JSON.stringify(payload())});setQuote(q);if(q.eligible_for_submission&&order.requested_vehicle){try{setPreview(await api('/assignment-preview',{method:'POST',body:JSON.stringify(payload())}))}catch(ex){setError(ex.message)}}}catch(e){setError(e.message)}finally{setBusy(false)}};
 const submitOrder=async()=>{setBusy(true);setError('');try{const result=await api('/orders',{method:'POST',body:JSON.stringify(payload())});setSuccess(result);setQuote(null);await onCreated();}catch(e){setError(e.message)}finally{setBusy(false)}};
 return <>
  <div className="page-head"><div><div className="eyebrow">B2B CUSTOMER PORTAL</div><h1>Place a freight order</h1><p>Enter your shipment details to generate an illustrative quote and request a simulated dispatch assignment.</p></div><Pill tone="blue">Demo quote engine</Pill></div>
  <div className="order-grid"><form onSubmit={requestQuote} className="panel order-form">
    <div className="panel-head"><div><h2>Shipment information</h2><p>Enter pickup, destination and cargo information.</p></div><span className="section-number">01</span></div>
    <div className="form-grid"><label className="form-field full"><span>Business / customer name <em>*</em></span><input value={order.customer} onChange={e=>setField('customer',e.target.value)} maxLength="80" placeholder="e.g. Westside Manufacturing" required/></label>
    <label className="form-field"><span>Pickup location <em>*</em></span><select value={order.pickup_zone} onChange={e=>setField('pickup_zone',e.target.value)}>{Object.entries(zones).map(([key,val])=><option value={key} key={key}>{val}</option>)}</select></label>
    <label className="form-field"><span>Drop-off location <em>*</em></span><select value={order.drop_zone} onChange={e=>setField('drop_zone',e.target.value)}>{Object.entries(zones).map(([key,val])=><option value={key} key={key}>{val}</option>)}</select></label>
    <label className="form-field"><span>Material / handling type</span><select value={order.cargo_type} onChange={e=>setField('cargo_type',e.target.value)}>{Object.entries(cargo).map(([key,val])=><option value={key} key={key}>{val}</option>)}</select></label>
    <label className="form-field"><span>Deliver by (demo day)</span><input type="time" min="10:00" max="18:00" value={order.delivery_by} onChange={e=>setField('delivery_by',e.target.value)}/></label></div>
    <div className="truck-choice"><div className="truck-choice-heading"><Mark type="truck"/><div><b>Assign order to a truck</b><span>Manual assignment is checked against existing cargo, stop order, delivery deadlines and modeled driver time.</span></div></div><label className="form-field"><span>Dispatch option</span><select value={order.requested_vehicle||''} onChange={e=>setField('requested_vehicle',e.target.value||null)}><option value="">Auto-assign best feasible truck</option>{(meta?.vehicle_options||[]).map(t=><option key={t.id} value={t.id} disabled={t.dispatch_status!=='available'}>{t.id} · {t.label} · {t.skids} skids · {fmt(t.weight_lb)} lb</option>)}</select></label>{order.requested_vehicle&&<p className="muted small">Selected truck is locked for this order. Generate estimate to validate placement before saving.</p>}</div>
    <div className="divider"/><div className="panel-head"><div><h2>Weight & dimensions</h2><p>Declared weight earns a simulated 2% discount; complete dimensions increase it to 5%.</p></div><span className="section-number">02</span></div>
    <div className="form-grid"><NumberInput label="Weight (kg)" name="weight_kg" value={order.weight_kg} onChange={setField} placeholder="e.g. 400" required/><label className="form-field"><span>Number of skids / pallets <em>*</em></span><input type="number" min="1" max="26" step="1" value={order.skids} placeholder="e.g. 2" onChange={e=>setField('skids',e.target.value)}/></label><div className="field-hint">Please supply an exact skid count to request dispatch. Missing weight is estimated for provisional pricing only.</div><NumberInput label="Length (cm)" name="length_cm" value={order.length_cm} onChange={setField} placeholder="e.g. 120" required/><NumberInput label="Width (cm)" name="width_cm" value={order.width_cm} onChange={setField} placeholder="e.g. 100" required/><NumberInput label="Height (cm)" name="height_cm" value={order.height_cm} onChange={setField} placeholder="e.g. 100" required/></div>
    <div className="form-footer"><button type="submit" disabled={busy}><Mark type="chart"/> {busy?'Calculating…':'Generate estimate'}</button><button type="button" className="text-button" onClick={()=>{setOrder({...DEFAULT_ORDER});setQuote(null);setError('');setSuccess(null)}}>Clear form</button></div>
    {error&&<Notice tone="error">{error}</Notice>}
    {preview&&<Notice tone="success">Truck {preview.vehicle} can accept this order under simulated capacity and time rules. Estimated delivery {time(preview.arrival)}; peak {preview.peak_skids}/{preview.limit_skids} skids and {fmt(preview.peak_weight_lb)}/{fmt(preview.limit_weight_lb)} lb.</Notice>}
    {success&&<Notice tone={success.tentatively_assigned?'success':'warn'}>Order {success.shipment_id} saved. {success.tentatively_assigned?'It fits the current demo planning constraints.':'Not currently assignable under demo constraints.'} This is not a confirmed delivery.</Notice>}
   </form>
   <div className="right-stack"><section className="panel quote-card"><div className="panel-head"><div><h2>Estimated quote</h2><p>Illustrative CAD pricing</p></div><Pill tone={quote?(quote.provisional?'warn':'green'):'neutral'}>{!quote?'Awaiting details':quote.provisional?'Provisional':'Complete'}</Pill></div>
   {quote?<><div className="quote-price">{cash(quote.estimated_cad)}</div><p className="muted small">Estimated cost · approximate city coordinates and simulated rate model</p><div className="quote-lines">{Object.entries(quote.breakdown).map(([key,val])=><div key={key}><span>{({base_cad:'Base service',distance_cad:'Demo travel',weight_cad:'Weight',space_cad:'Volume',handling_cad:'Special handling',urgent_cad:'Urgency',completeness_discount_cad:'Information discount'})[key]||key}</span><b className={key==='completeness_discount_cad'?'discount':''}>{key==='completeness_discount_cad'?'-':''}{cash(val)}</b></div>)}</div>
   <div className="quote-note">Weight used: {quote.weight_used_kg} kg ({fmt(quote.weight_used_lb)} lb) · Skids: {quote.declared_skids??'not supplied'} · Volume used: {quote.volume_used_m3} m³ · {quote.distance_units} demo units</div>
   {quote.assumptions.map(x=><Notice key={x} tone="warn">{x}</Notice>)}
   <button className="full-button" disabled={busy||!quote.eligible_for_submission} onClick={submitOrder}><Mark type="plus"/> Add to dispatch queue</button>
   {quote.provisional&&<p className="small subdued">Enter weight, skids, and all three dimensions, then generate a new estimate before submission.</p>}
   </>:<div className="quote-placeholder"><div className="quote-placeholder-icon"><Mark type="chart" size={27}/></div><h3>Your estimate appears here</h3><p>Fill in the form and click Generate estimate. You can request provisional pricing without providing weight or dimensions.</p></div>}
   </section><section className="panel micro"><div className="panel-head"><h2>Transparency first</h2><Mark type="info"/></div><p>These are not Trans Ontario commercial prices. Demo coordinates, cost rates, travel estimates and driver rules are invented for prototype testing.</p><p className="muted small">A submitted order joins the planning queue. The optimizer must still find a feasible route.</p></section></div>
  </div>
 </>;
}
function Orders({orders,meta,onDelete,onAssign,busy,plan}){
 const zones=meta?.zones||DEFAULT_ZONES;
 const assigned = new Set(plan?.routes.flatMap(r=>r.shipments)||[]);
 const rejected = new Set(plan?.unassigned.map(r=>r.shipment)||[]);
 return <><div className="page-head"><div><div className="eyebrow">CUSTOMER ORDERS</div><h1>Order management</h1><p>Submitted demo orders are stored locally in the backend SQLite database and included in future plans.</p></div><Pill tone="blue">{orders.length} orders</Pill></div>
 <section className="panel"><div className="panel-head"><div><h2>New B2B shipments</h2><p>Each new pickup and delivery is evaluated for available driver time and onboard capacity.</p></div></div>
 {orders.length?<div className="table-wrap"><table><thead><tr><th>Shipment</th><th>Customer</th><th>Pickup → Destination</th><th>Cargo</th><th>Skids / Weight / Volume</th><th>Due</th><th>Demo quote</th><th>Plan</th><th>Truck assignment</th><th></th></tr></thead><tbody>{orders.map(o=>{const key='B'+String(o.id).padStart(3,'0');return <tr key={o.id}><td><strong>{key}</strong></td><td>{o.customer}</td><td>{zones[o.pickup_zone]} <span className="muted">→</span> {zones[o.drop_zone]}</td><td>{o.cargo_type.replaceAll('_',' ')}</td><td>{o.skids_assumed?<Pill tone="warn">Skids unverified</Pill>:null} {o.skids} skid(s) · {fmt(toLb(o.weight_kg))} lb / {o.volume_m3} m³</td><td>{time(o.due_min)}</td><td>{cash(o.quoted_cad)}</td><td>{assigned.has(key)?<Pill tone="green">Feasible</Pill>:rejected.has(key)?<Pill tone="warn">Unassigned</Pill>:<Pill>Pending</Pill>}</td><td><select className="order-truck-select" aria-label={'Assign '+key+' to a truck'} disabled={busy||Boolean(o.skids_assumed)} value={o.requested_vehicle||''} onChange={e=>onAssign(o.id,e.target.value||null)}><option value="">Automatic</option>{(meta?.vehicle_options||[]).map(v=><option value={v.id} key={v.id} disabled={v.dispatch_status!=='available'}>{v.id} · {v.skids} skids</option>)}</select><small className="muted">{o.requested_vehicle?'Pinned assignment':'Optimizer selected'}</small></td><td><button className="icon-button danger" title="Delete demo order" aria-label={'Delete '+key} disabled={busy} onClick={()=>onDelete(o.id)}><Mark type="delete"/></button></td></tr>})}</tbody></table></div>:<div className="empty-state"><div className="empty-icon"><Mark type="box" size={32}/></div><h3>No new orders yet</h3><p>Create an order in the B2B order portal to test dynamic routing and capacity.</p></div>}
 </section></>;
}
function CapacityBar({label,used,max,unit,note}){
 const ratio=Math.max(0,Math.min(100,max?100*used/max:0));
 return <div className="loadline"><div><span>{label}</span><b>{fmt(used)} / {fmt(max)} {unit}</b></div><div className="progress"><div className={ratio>90?'nearly-full':''} style={{width:`${ratio}%`}}/></div>{note&&<small className="subdued">{note}</small>}</div>;
}
function DispatchStatus({route}){
 const status=route?.dispatch_status||'available';
 const label=status==='delivering'?'Delivering now':status==='standby'?'Emergency standby':route?.shipments?.length?'Loaded · Ready':'Available to load';
 return <span className={'dispatch-status '+status}><span className="status-led"/>{label}</span>;
}
// v0.9 — operational dispatch board. All values reflect the local simulated plan, never live telematics.
function dispatchBucket(route){
 if(route.dispatch_status==='delivering') return 'delivering';
 if(route.dispatch_status==='standby') return 'standby';
 return route.shipments.length?'ready':'empty';
}
function downloadDispatchCsv(plan){
 if(!plan?.routes?.length)return;
 const fields=['Truck','Driver','Status','Truck type','Shipments','Stops','Peak skids','Skid limit','Peak cargo lb','Reported capacity lb','On-duty minutes (demo)','Shift remaining minutes (demo)','Route sequence'];
 const esc=value=>'"'+String(value??'').replaceAll('"','""')+'"';
 const rows=plan.routes.map(r=>[r.vehicle,r.driver,dispatchBucket(r),r.truck_type,r.shipments.length,r.stop_sequence.length,r.peak_skids,r.skid_limit,r.peak_weight_lb,r.weight_limit_lb,r.driver_hours.scheduled_on_duty_min,r.driver_hours.remaining_shift_min,r.stop_sequence.join(' > ')]);
 const csv=[fields,...rows].map(row=>row.map(esc).join(',')).join('\r\n');
 const blob=new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'});
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download='transopt-demo-dispatch-board.csv';document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
}
function DispatchBoard({plan,onRefresh,onStartRoute,onRelease,onOpenMap,onNewOrder,busy}){
 const [filter,setFilter]=useState('all');
 const [query,setQuery]=useState('');
 const [selected,setSelected]=useState('');
 const routes=plan?.routes||[];
 const counts={all:routes.length,delivering:0,ready:0,empty:0,standby:0};
 routes.forEach(route=>{counts[dispatchBucket(route)]++});
 const active=routes.find(r=>r.vehicle===selected)||routes[0];
 const visible=routes.filter(route=>{
  if(filter!=='all'&&dispatchBucket(route)!==filter)return false;
  const term=query.trim().toLowerCase();
  return !term||[route.vehicle,route.driver,route.truck_type,...route.shipments].join(' ').toLowerCase().includes(term);
 });
 const nearCapacity=routes.filter(r=>r.dispatch_status!=='standby'&&r.shipments.length&& (r.peak_skids/r.skid_limit>=.9||r.peak_weight_lb/r.weight_limit_lb>=.9));
 const lowHours=routes.filter(r=>r.dispatch_status!=='standby'&&r.shipments.length&&r.driver_hours.remaining_shift_min<=60);
 const unassigned=plan?.unassigned||[];
 const cards=[{key:'all',title:'Total fleet',value:counts.all,help:'Simulated vehicles',icon:'truck'},
 {key:'delivering',title:'Delivering',value:counts.delivering,help:'Routes locked in demo',icon:'route'},
 {key:'ready',title:'Loaded & ready',value:counts.ready,help:'Can start route',icon:'check'},
 {key:'empty',title:'Available to load',value:counts.empty,help:'No assigned cargo',icon:'plus'},
 {key:'standby',title:'Emergency reserve',value:counts.standby,help:'Release before assignment',icon:'refresh'}];
 return <>
  <div className="page-head board-title"><div><div className="eyebrow">FLEET CONTROL · SIMULATED OPERATIONS</div><h1>Dispatch board</h1><p>Load trucks, review shift time, launch routes and keep emergency capacity ready.</p></div><div className="head-actions"><button type="button" className="outline" onClick={onRefresh} disabled={busy}><Mark type="refresh"/>Refresh plan</button><button type="button" className="outline" disabled={!plan} onClick={()=>downloadDispatchCsv(plan)}><Mark type="chart"/>Export CSV</button><button type="button" onClick={onNewOrder}><Mark type="plus"/>New shipment</button></div></div>
  <div className="board-metrics" role="group" aria-label="Filter by vehicle status">{cards.map(card=><button key={card.key} type="button" className={'board-metric '+(filter===card.key?'selected':'')} onClick={()=>setFilter(card.key)} aria-pressed={filter===card.key}><span className="board-metric-head">{card.title}<Mark type={card.icon}/></span><strong>{card.value}</strong><small>{card.help}</small></button>)}</div>
  <div className="board-body">
   <section className="panel board-list-panel"><div className="panel-head"><div><h2>Fleet availability</h2><p>Choose a truck to view its manifest and dispatch actions.</p></div><Pill tone="blue">{visible.length} shown</Pill></div>
    <div className="board-filterbar"><label className="board-search"><span className="sr-only">Search trucks or drivers</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search truck, driver or shipment…"/></label><select aria-label="Filter truck status" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All statuses</option><option value="delivering">Delivering</option><option value="ready">Loaded & ready</option><option value="empty">Available to load</option><option value="standby">Emergency reserve</option></select></div>
    <div className="board-truck-list">{visible.map(r=>{
     const status=dispatchBucket(r);
     const peak=r.skid_limit?Math.round(100*r.peak_skids/r.skid_limit):0;
     return <button type="button" key={r.vehicle} className={'board-truck '+(active?.vehicle===r.vehicle?'active':'')} onClick={()=>setSelected(r.vehicle)} aria-pressed={active?.vehicle===r.vehicle}>
      <div className="board-truck-icon"><Mark type="truck" size={22}/></div>
      <div className="board-truck-details"><div className="board-truck-top"><strong>{r.vehicle}<span> · Driver {r.driver}</span></strong><span className={'board-status '+status}>{status==='delivering'?'Delivering':status==='ready'?'Ready':status==='standby'?'Standby':'Available'}</span></div><small>{r.truck_type}</small><div className="board-truck-bottom"><span>{r.shipments.length} shipment{r.shipments.length===1?'':'s'}</span><span>{r.peak_skids} / {r.skid_limit} skids</span><span>{minuteDuration(r.driver_hours.remaining_shift_min)} left</span></div><div className="board-inline-track"><i style={{width:Math.min(100,peak)+'%'}}/></div></div><Mark type="chevron" size={18}/>
     </button>
    })}{!visible.length&&<div className="board-no-results">No trucks match this filter. Try another status or search.</div>}</div>
   </section>
   <div className="board-right-stack">
    <section className="panel board-detail">{active?<><div className="board-detail-head"><div><div className="eyebrow">SELECTED VEHICLE</div><h2>{active.vehicle} <span>· {active.driver}</span></h2><p>{active.truck_type}</p></div><DispatchStatus route={active}/></div>
     <div className="board-detail-metrics"><div><span>Assigned cargo</span><strong>{active.shipments.length}</strong><small>shipments</small></div><div><span>Route stops</span><strong>{active.stop_sequence.length}</strong><small>pickup / drop</small></div><div><span>Shift remaining</span><strong>{minuteDuration(active.driver_hours.remaining_shift_min)}</strong><small>13-hour demo work cap</small></div></div>
     <CapacityBar label="Skid positions (peak)" used={active.peak_skids} max={active.skid_limit} unit="skids"/>
     <CapacityBar label="Cargo weight (peak)" used={active.peak_weight_lb} max={active.weight_limit_lb} unit="lb"/>
     <CapacityBar label="Estimated on-duty time" used={active.driver_hours.scheduled_on_duty_min} max={active.driver_hours.max_work_min} unit="min"/>
     <div className="board-actions"><button type="button" className="outline" onClick={()=>onOpenMap(active.vehicle)}><Mark type="route"/>View route map</button>
      {active.dispatch_status==='standby'?<button type="button" onClick={()=>onRelease(active.vehicle)} disabled={busy}><Mark type="check"/>Release reserve</button>:active.dispatch_status==='available'&&active.shipments.length>0?<button type="button" disabled={busy} onClick={()=>onStartRoute(active.vehicle)}><Mark type="check"/>Start route</button>:active.dispatch_status==='available'?<button type="button" onClick={onNewOrder}><Mark type="plus"/>Load new order</button>:<Pill tone="green">Route started</Pill>}
     </div>
     <div className="board-manifest-head"><h3>Planned stops</h3><small>Estimated local demo time</small></div>
     {active.events.length?<ol className="board-manifest">{active.events.map((event,i)=><li key={`${event.shipment}-${event.type}-${i}`}><span className={'board-stop-number '+event.type}>{i+1}</span><div><b>{event.shipment}</b><small>{event.type==='pickup'?'Collect freight':'Deliver freight'} · {event.onboard_skids} skids onboard</small></div><strong>{time(event.eta_min)}</strong></li>)}</ol>:<div className="board-empty-route"><Mark type="box"/><span>{active.dispatch_status==='standby'?'This truck is reserved for breakdown recovery.':'No cargo assigned. Add an order to prepare this truck.'}</span></div>}
    </>:<div className="empty-state">Loading fleet…</div>}</section>
    <section className="panel board-alerts"><div className="panel-head"><div><h2>Dispatch attention</h2><p>Warnings generated from the currently modeled plan.</p></div><Mark type="alert"/></div>
      {unassigned.length>0&&<div className="board-alert urgent"><Mark type="alert"/><div><b>{unassigned.length} unassigned shipment{unassigned.length===1?'':'s'}</b><p>{unassigned.slice(0,2).map(x=>x.shipment).join(', ')} · Review feasibility and commitments.</p></div></div>}
      {nearCapacity.length>0&&<div className="board-alert"><Mark type="box"/><div><b>Near capacity: {nearCapacity.map(x=>x.vehicle).join(', ')}</b><p>At least 90% of skid or reported weight capacity at peak load.</p></div></div>}
      {lowHours.length>0&&<div className="board-alert"><Mark type="clock"/><div><b>Low modeled shift time: {lowHours.map(x=>x.vehicle).join(', ')}</b><p>One hour or less remains under the 13-hour project rule.</p></div></div>}
      {counts.ready>0&&<div className="board-alert positive"><Mark type="check"/><div><b>{counts.ready} loaded truck{counts.ready===1?' is':'s are'} ready</b><p>Review the manifest and press Start route when ready to dispatch.</p></div></div>}
      {counts.standby>0&&<div className="board-alert"><Mark type="refresh"/><div><b>{counts.standby} emergency backup truck{counts.standby===1?'':'s'}</b><p>Standby vehicles stay out of normal assignments until released.</p></div></div>}
      {unassigned.length===0&&nearCapacity.length===0&&lowHours.length===0&&counts.ready===0&&counts.standby===0&&<p className="green-message"><Mark type="check"/>No modeled exceptions at this time.</p>}
    </section>
   </div>
  </div>
  <p className="board-disclaimer">Demo operations only · Route starts and fleet states are stored locally, not sent to drivers. Times, cargo, ETAs and truck readiness are simulated; legal hours-of-service, truck access and physical loading are not verified.</p>
 </>;
}

function Fleet({plan,onStartRoute,onRelease,onOpenMap,busy}){return <>
 <div className="page-head"><div><div className="eyebrow">FLEET OPERATIONS · VERSION 0.8</div><h1>Vehicles & driver shifts</h1><p>Reported skid and pound ratings plus an enforced 13-hour demo workday, with driving tracked separately.</p></div><Pill tone="blue">{plan?.routes.length||0} demo trucks</Pill></div>
 <div className="fleet-grid">{(plan?.routes||[]).map(r=><div className="panel fleet-card" key={r.vehicle}>
  <div className="fleet-top"><span className="truck-avatar"><Mark type="truck" size={21}/></span><DispatchStatus route={r}/></div>
  <h2>{r.vehicle}</h2><p className="muted">{r.truck_type} · Driver {r.driver}</p><div className="fleet-load-count"><b>{r.shipments.length}</b> assigned shipments · <b>{r.stop_sequence.length}</b> route stops</div>
  <CapacityBar label="Peak skid positions" used={r.peak_skids} max={r.skid_limit} unit="skids" note={r.skid_capacity_estimated?'Skid count pending verification':'Vehicle-specific loading still unverified'}/>
  <CapacityBar label="Peak cargo weight" used={r.peak_weight_lb} max={r.weight_limit_lb} unit="lb" note="User-reported rating; verify payload allowance"/>
  <CapacityBar label="Peak cubic volume" used={r.peak_volume_m3} max={r.volume_limit_m3} unit="m³" note="Demo estimate; not measured trailer volume"/>
  <CapacityBar label="Estimated working time" used={r.driver_hours.scheduled_on_duty_min} max={r.driver_hours.max_work_min} unit="min" note={`Remaining: ${minuteDuration(r.driver_hours.remaining_shift_min)}`}/>
  <div className="fleet-bottom"><Mark type="clock"/> {minuteDuration(r.driver_hours.estimated_drive_min)} driving · Ends {time(r.finish_min)} (simulated)</div>
  <div className="fleet-action-bar"><button type="button" className="outline" onClick={()=>onOpenMap(r.vehicle)}><Mark type="route"/> Route map</button>
   {r.dispatch_status==='available'?<button type="button" disabled={busy||!r.shipments.length} title={!r.shipments.length?'Assign cargo before starting the route':''} onClick={()=>onStartRoute(r.vehicle)}><Mark type="check"/> Start route</button>:
   r.dispatch_status==='standby'?<button type="button" disabled={busy} onClick={()=>onRelease(r.vehicle)}><Mark type="plus"/> Release backup</button>:
   <span className="route-running-label"><span className="status-led"/> Route in progress</span>}
  </div>
 </div>)}</div>
 <Notice tone="warn">13 hours is enforced as a project workday policy for this prototype. Actual regulatory driving/on-duty/rest rules, vehicle weight ratings, skid loading, permits, and driver qualifications must be checked separately. No compliance certification.</Notice>
 </>}


// v0.5: Connected operational workflow. Coordinates, prices and hours are illustrative.
const minuteDuration = value => `${Math.floor(Math.max(0,value||0)/60)}h ${Math.round(Math.max(0,value||0)%60)}m`;
const DEMO_TRUCK_COLORS=['#1F4AEE','#5F85F2','#0C807B','#CF7C32'];
function RouteSketch({route,baseline}){
 if(!route?.points?.length || route.points.length<2)return <div className="empty-state"><Mark type="truck" size={30}/><h3>Idle truck</h3><p>No route is scheduled for this vehicle.</p></div>;
 const xy=p=>[48+(p.x/16)*600, 315-(p.y/14)*280];
 const poly=r=>r?.points?.length>1?r.points.map(p=>xy(p).join(',')).join(' '):'';
 return <div className="planner-map"><svg viewBox="0 0 700 363" className="planner-svg" role="img" aria-label={`Planned route for ${route.vehicle} showing ${route.events.length} stops in travel order`}>
  <defs><pattern id="plan-grid" width="45" height="45" patternUnits="userSpaceOnUse"><path d="M45 0H0V45" fill="none" stroke="#e2e9f5" strokeWidth="1"/></pattern></defs>
  <rect width="700" height="363" fill="#f7faff"/><rect width="700" height="363" fill="url(#plan-grid)"/>
  {baseline && baseline.vehicle===route.vehicle && baseline!==route && baseline.points?.length>1 && <polyline points={poly(baseline)} fill="none" stroke="#98a6ba" strokeDasharray="7 7" strokeWidth="3" strokeLinecap="round"/>}
  <polyline points={poly(route)} fill="none" stroke="#1F4AEE" strokeWidth="4.5" strokeLinejoin="round" strokeLinecap="round"/>
  {route.points.slice(1).map((p,i)=>{const [x,y]=xy(p),[px,py]=xy(route.points[i]);const midx=(x+px)/2,midy=(y+py)/2;const theta=Math.atan2(y-py,x-px);return <g key={'arrow'+i} transform={`translate(${midx},${midy}) rotate(${theta*180/Math.PI})`}><path d="M-6 -5 L3 0 L-6 5" fill="none" stroke="#1F4AEE" strokeWidth="2.5" strokeLinecap="round"/></g>})}
  {route.points.slice(0,-1).map((p,i)=>{const [x,y]=xy(p),isDepot=i===0;return <g key={i}><circle cx={x} cy={y} r={isDepot?17:14} fill={isDepot?'#16254e':p.type==='pickup'?'#1F4AEE':'#138a77'} stroke="white" strokeWidth="3"/><text x={x} y={y+4} textAnchor="middle" fill="white" fontSize="11" fontWeight="800">{isDepot?'D':i}</text><text x={x+13} y={y-19} fill="#40516f" fontSize="11" fontWeight="800">{isDepot?'DEPOT':p.shipment}</text><title>{isDepot?'Depot 08:00':`${i}. ${p.type}: ${p.shipment} / ETA ${time(p.eta_min)}`}</title></g>})}
  </svg><div className="geo-legend"><span><i style={{background:'#16254e'}}/> Depot</span><span><i style={{background:'#1F4AEE'}}/> Pickup</span><span><i style={{background:'#138a77'}}/> Drop-off</span><span><i style={{background:'#98a6ba'}}/> Old route (if changed)</span><span>Diagram coordinates, not roads or GPS</span></div></div>
}
function CargoProjection({route,selectedStop,shipments}){
 const [selected,setSelected]=useState(null);
 const entries=route?.events||[];
 const initialIds=route?.shipments?.filter(id=>shipments[id]?.pickup_at_depot && !(route?.events||[]).some(e=>e.shipment===id&&e.type==='pickup')) || [];
 const onboard=selectedStop<0?initialIds:(entries[selectedStop]?.onboard_shipments||[]);
 const ordered=onboard.map(id=>({id,shipment:shipments[id],drop:entries.findIndex(e=>e.type==='drop'&&e.shipment===id)})).sort((a,b)=>b.drop-a.drop);
 const colors=['#1f4aee','#4f79ec','#7899f6','#9bb5fb','#176e91','#1b9a90'];
 return <div>
   <div className="trailer-graphic"><div className="trailer-caption"><span>FRONT / CAB</span><span>SIDE ACCESS (concept)</span><span>REAR DOORS</span></div>
   <div className="trailer-shell"><div className="trailer-front"/><div className="trailer-bed"><div className="side-door" title="Illustrative side-door location">SIDE DOOR</div><div className="cargo-slots">{ordered.map((item,i)=><button type="button" title={`${item.id} · ${item.shipment?.weight_kg??'?'} kg · ${item.shipment?.volume_m3??'?'} m³`} className={'cargo-slot '+(selected===item.id?'selected':'')} style={{background:colors[i%colors.length],flex:Math.max(.65,Math.min(5,item.shipment?.volume_m3||1))}} key={item.id} onClick={()=>setSelected(item.id)}>{item.id}<small>Stop {item.drop+1}</small></button>)}{!ordered.length&&<span className="cargo-empty">Trailer empty at this step</span>}</div></div><div className="rear-door">REAR</div></div></div>
  <div className="subdued trailer-legend">At {selectedStop<0?'departure from depot':`${entries[selectedStop]?.type} ${entries[selectedStop]?.shipment} (${time(entries[selectedStop]?.eta_min)})`} • {onboard.reduce((total,id)=>total+(shipments[id]?.skids||0),0)} skid positions across {onboard.length} cargo items. Blocks are illustrative, not dimensioned packing.</div>
  {selected&&onboard.includes(selected)&&<div className="quote-note">Selected {selected}: {fmt(toLb(shipments[selected]?.weight_kg))} lb, {shipments[selected]?.skids??'?'} skid(s), {shipments[selected]?.volume_m3??'?'} m³. Door clearance, axle load, securement and physical placement remain unverified.</div>}
 </div>;
}
// Live OpenStreetMap route display with optional OSRM public road geometry.
// We do not substitute these distances for the dispatch feasibility engine.
function RoadRouteMap({route,baseline,selectedStop,onSelectStop}){
 const mount=useRef(null), leafmap=useRef(null), layers=useRef(null);
 const [roadState,setRoadState]=useState('loading');
 const [roadDistance,setRoadDistance]=useState(null);
 const stopId=route?.vehicle+'|'+(route?.points||[]).map(p=>[p.lat,p.lng,p.type,p.shipment].join(':')).join('|');
 useEffect(()=>{
  const L=window.L;
  if(!mount.current||!L){setRoadState('unavailable');return;}
  if(!leafmap.current){
    leafmap.current=L.map(mount.current,{zoomControl:true,scrollWheelZoom:false}).setView([43.8158,-79.2361],10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
      attribution:'&copy; OpenStreetMap contributors',maxZoom:18
    }).addTo(leafmap.current);
    layers.current=L.layerGroup().addTo(leafmap.current);
  }
  const map=leafmap.current;
  setTimeout(()=>map.invalidateSize(),40);
  return()=>{};
 },[]);
 useEffect(()=>{
  const L=window.L,map=leafmap.current;
  if(!map||!L||!layers.current)return;
  layers.current.clearLayers();
  const points=(route?.points||[]).filter(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lng));
  setRoadDistance(null);
  if(!points.length){setRoadState('idle');map.setView([43.8158,-79.2361],10);return;}
  const latlng=points.map(p=>[p.lat,p.lng]);
  const fit=L.latLngBounds(latlng); map.fitBounds(fit.pad(.17),{maxZoom:12});
  // Stroke is always drawn: a dashed fallback is explicitly labeled as such.
  let currentLine=L.polyline(latlng,{color:'#1F4AEE',weight:4,opacity:.76,dashArray:'9 7'}).addTo(layers.current);
  points.forEach((p,i)=>{
    const type=p.type==='depot'||p.type==='return'?'depot':p.type==='pickup'?'pickup':'drop';
    const color=type==='pickup'?'#028a7f':type==='drop'?'#1F4AEE':'#030718';
    const mark=L.divIcon({className:'route-pin-shell',html:`<span class="route-number-pin" style="background:${color}">${p.type==='depot'?'H':p.type==='return'?'↩':i}</span>`,iconSize:[30,30],iconAnchor:[15,15]});
    const el=L.marker([p.lat,p.lng],{icon:mark}).addTo(layers.current);
    const stopLabel=p.location||'Example stop';
    const escaped=String(stopLabel).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    el.bindPopup(`<b>${p.type.toUpperCase()} ${p.shipment||''}</b><br/>${escaped}<br/><small>Planning stop · coordinates approximate</small>`);
    if(i>0 && i<points.length-1)el.on('click',()=>onSelectStop?.(i-1));
  });
  let cancelled=false;
  setRoadState('fallback');
  if(points.length<2 || points.length>22)return()=>{cancelled=true};
  const ctrl=new AbortController();
  const timer=setTimeout(()=>ctrl.abort(),8500);
  const pairs=points.map(p=>`${p.lng},${p.lat}`).join(';');
  fetch(`https://router.project-osrm.org/route/v1/driving/${pairs}?overview=full&geometries=geojson&steps=false`,{signal:ctrl.signal})
    .then(res=>{if(!res.ok)throw Error('Routing service unavailable');return res.json()})
    .then(body=>{
      if(cancelled||body.code!=='Ok'||!body.routes?.[0])return;
      currentLine.remove();
      const road=body.routes[0];
      L.geoJSON(road.geometry,{style:{color:'#1F4AEE',weight:5,opacity:.85}}).addTo(layers.current);
      setRoadDistance(Math.round(road.distance/1000));setRoadState('roads');
    }).catch(()=>{if(!cancelled)setRoadState('fallback')}).finally(()=>clearTimeout(timer));
  return()=>{cancelled=true;clearTimeout(timer);ctrl.abort()};
 },[stopId]);
 useEffect(()=>{
  if(selectedStop>=0){const point=route?.points?.[selectedStop+1];if(point && leafmap.current)leafmap.current.panTo([point.lat,point.lng]);}
 },[selectedStop,stopId]);
 useEffect(()=>{
  return()=>{if(leafmap.current){leafmap.current.remove();leafmap.current=null;layers.current=null}}
 },[]);
 return <div className="road-map-wrapper"><div className="road-map-container" ref={mount} role="region" aria-label={`Map of route for ${route?.vehicle||'selected truck'}`}/><div className="road-status-bar"><span className="road-status-dot"/>{roadState==='roads'?`Public road geometry · ${roadDistance} km (map estimate only)`:roadState==='fallback'?'Straight-line fallback · road routing unavailable or loading':roadState==='idle'?'No stops for this truck':roadState==='unavailable'?'Map library needs internet connection':'Loading map…'}<span>Points approximate · not truck-safe navigation</span></div></div>;
}

function FleetWideMap({plan,initialTruck,onNewOrder,onStartRoute,busy}){
 const routes=plan?.routes||[];
 const [selected,setSelected]=useState(initialTruck||'T01');
 useEffect(()=>{if(initialTruck)setSelected(initialTruck)},[initialTruck]);
 const route=routes.find(r=>r.vehicle===selected)||routes.find(r=>r.shipments.length)||routes[0];
 const [selectedStop,setSelectedStop]=useState(-1);
 useEffect(()=>setSelectedStop(-1),[selected]);
 return <><div className="page-head"><div><div className="eyebrow">GEO DISPATCH • SCARBOROUGH DEPOT</div><h1>Truck route map</h1><p>Explore each truck's pickup and delivery sequence across Ontario and beyond.</p></div><button onClick={onNewOrder}><Mark type="plus"/>Add new freight order</button></div>
 <Notice tone="info">Depot: 2215 Markham Road, Scarborough. City markers are approximate, while demo S01–S12 stop locations are synthetic. A road-shaped route is not a truck-approved or live traffic route.</Notice>
 <div className="map-truck-picker">{routes.map(r=><button key={r.vehicle} className={'map-truck-button '+(route?.vehicle===r.vehicle?'active':'')} onClick={()=>setSelected(r.vehicle)}><Mark type="truck" size={18}/><span><b>{r.vehicle}</b><small>{r.truck_type}</small></span><span className="map-truck-count">{r.shipments.length} loads · {r.dispatch_status==='delivering'?'En route':r.dispatch_status==='standby'?'Reserve':'Ready'}</span></button>)}</div>
 <section className="panel fleet-map-panel"><div className="panel-head"><div><h2>{route?.vehicle} · {route?.driver} route</h2><p>{route?.events.length||0} planned stops · {route?.peak_skids||0}/{route?.skid_limit||0} peak skids · {route?.driver_hours?minuteDuration(route.driver_hours.remaining_shift_min)+' modeled shift left':''}</p></div><div className="map-head-actions"><DispatchStatus route={route}/>{route?.dispatch_status==='available'&&<button type="button" onClick={()=>onStartRoute(route.vehicle)} disabled={busy||!route?.shipments.length}><Mark type="check"/> Start route with {route.shipments.length} shipment{route.shipments.length!==1?'s':''}</button>}</div></div>
 <RoadRouteMap route={route} selectedStop={selectedStop} onSelectStop={setSelectedStop}/>
 <div className="map-stops-list">{(route?.events||[]).map((e,i)=><button key={i} className={'map-stop-card '+(selectedStop===i?'active':'')} onClick={()=>setSelectedStop(i)}><span className={'map-stop-index '+(e.type==='pickup'?'pickup':'')}>{i+1}</span><span><b>{e.shipment} · {e.type==='pickup'?'Pickup':'Delivery'}</b><small>Model ETA {time(e.eta_min)} · {e.onboard_skids} skids remaining</small></span></button>)}{!route?.events?.length&&<div className="empty-state"><h3>Truck idle</h3><p>Choose another truck or add an order.</p></div>}</div>
 </section></>;
}

function Operations({plan,onAddOrder}){
 const [scenario,setScenario]=useState('none');
 const [recovery,setRecovery]=useState(null);
 const [choice,setChoice]=useState('standby');
 const [selectedTruck,setSelectedTruck]=useState('T01');
 const [selectedStop,setSelectedStop]=useState(-1);
 const [shipments,setShipments]=useState({});
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 useEffect(()=>{let live=true;api('/data').then(res=>{if(live)setShipments(Object.fromEntries(res.shipments.map(s=>[s.id,s])))}).catch(()=>{});return()=>{live=false}},[plan?.total_shipments]);
 async function selectScenario(type){setScenario(type);setChoice('standby');setSelectedStop(-1);setError('');setRecovery(null);if(type==='none')return;setLoading(true);try{setRecovery(await api('/recovery?failure_type='+type))}catch(e){setError(e.message)}finally{setLoading(false)}}
 const selectedOption=recovery?.options.find(x=>x.id===choice)||recovery?.options[0];
 const activePlan=scenario==='none'?plan:selectedOption?.plan;
 const routes=activePlan?.routes||[];
 const truck=routes.find(x=>x.vehicle===selectedTruck)||routes.find(x=>x.shipments.length)||routes[0];
 const baselineRoute=plan?.routes.find(x=>x.vehicle===truck?.vehicle);
 const totalShift=truck?.driver_hours?.max_work_min||780;
 useEffect(()=>{setSelectedStop(-1)},[selectedTruck,choice,scenario]);
 return <>
 <div className="page-head"><div><div className="eyebrow">CONNECTED DISPATCH PLANNING</div><h1>Route & recovery studio</h1><p>Build a route, add B2B pickups, inspect cargo and driver hours, then redraw after disruption.</p></div><button type="button" onClick={onAddOrder}><Mark type="plus"/>Add pickup / new order</button></div>
 <div className="ops-workflow"><span>1 · Order + skids</span><Mark type="chevron"/><span>2 · Weight, skids & ETA check</span><Mark type="chevron"/><span>3 · Draw route</span><Mark type="chevron"/><span>4 · Recover & redraw</span></div>
 <section className="panel ops-scenario"><div className="panel-head"><div><h2>What changed?</h2><p>Select a disruption. The route and cargo projection update with the chosen recovery option.</p></div><Pill tone="blue">4 recovery strategies</Pill></div>
 <div className="ops-toggle"><button type="button" className={scenario==='none'?'chosen':''} onClick={()=>selectScenario('none')}>Normal dispatch</button><button type="button" className={scenario==='driver'?'chosen':''} onClick={()=>selectScenario('driver')}>D01 absent</button><button type="button" className={scenario==='truck'?'chosen':''} onClick={()=>selectScenario('truck')}>T01 breakdown</button></div>
 {error&&<Notice tone="error">{error}</Notice>}
 {loading&&<p className="muted">Evaluating recovery options…</p>}
 {recovery&&scenario!=='none'&&<><div className="recovery-options">{recovery.options.map(x=><button type="button" className={'recovery-option '+(choice===x.id?'selected':'')} key={x.id} onClick={()=>{setChoice(x.id);setSelectedStop(-1)}}><span className="recovery-priority">Option {x.priority}</span><b>{x.label}</b><small>{x.approach}</small><span className="recovery-metric">{x.plan.assigned_count}/{x.plan.total_shipments} shipments · {x.plan.unassigned.length} at risk · {x.plan.total_distance_units} demo units</span></button>)}</div>
 <Notice tone="warn">{selectedOption?.explanation} {selectedOption?.verification.join('; ')} must still be verified. These are conditional simulations, not approved real-life dispatch.</Notice>
 </>}
 </section>
 {activePlan&&<><div className="stats ops-stats"><Metric label="Assigned shipments" value={`${activePlan.assigned_count}/${activePlan.total_shipments}`} foot="Skids, weight, volume and 13h modeled shift" icon="box"/><Metric label="Available trucks" value={`${routes.filter(r=>r.shipments.length).length}`} foot="Active planned routes" icon="truck"/><Metric label="Travel units" value={activePlan.total_distance_units} foot={plan&&activePlan!==plan?`Baseline ${plan.total_distance_units} units`:'Simulated coordinates, not km'} icon="route"/><Metric label="At-risk / unassigned" value={activePlan.unassigned.length} foot="Unassigned under demo rules" icon="alert"/></div>
 <div className="ops-two-columns"><section className="panel"><div className="panel-head"><div><h2>Live road route map</h2><p>OpenStreetMap tiles, road geometry when available, and numbered pickup/drop-off stops.</p></div><label className="form-field ops-truck-select"><span>Display truck</span><select value={truck?.vehicle||''} onChange={e=>setSelectedTruck(e.target.value)}>{routes.map(r=><option key={r.vehicle} value={r.vehicle}>{r.vehicle} — {r.driver} ({r.shipments.length} shipments)</option>)}</select></label></div>
 <RoadRouteMap route={truck} baseline={baselineRoute} selectedStop={selectedStop} onSelectStop={setSelectedStop}/>
 <div className="ops-timeline"><div className="panel-head"><h2>Stop order & delivery commitments</h2><Pill tone="blue">{truck?.events.length||0} stops</Pill></div>
 <div className="table-wrap"><table><thead><tr><th>Stop</th><th>Action</th><th>ETA</th><th>Delivery deadline</th><th>Load after stop</th><th></th></tr></thead><tbody>{(truck?.events||[]).map((e,i)=><tr className={selectedStop===i?'ops-highlight':''} key={i}><td><b>{i+1}. {e.shipment}</b></td><td>{e.type==='pickup'?<Pill tone="blue">Pickup</Pill>:<Pill tone="green">Drop</Pill>}</td><td>{time(e.eta_min)}</td><td>{e.due_min!=null?<span style={{color:e.late?'#bd3529':'#178047'}}>{time(e.due_min)} {e.late?'LATE':'On time*'}</span>:'—'}</td><td>{e.onboard_skids}/{truck.skid_limit} skids · {fmt(e.onboard_weight_lb)} lb</td><td><button type="button" className="ops-mini-button" onClick={()=>setSelectedStop(i)}>Inspect cargo</button></td></tr>)}{!truck?.events?.length&&<tr><td colSpan="6">Truck idle; available as backup within demo constraints.</td></tr>}</tbody></table></div>
 </div></section>
 <aside className="ops-side"><section className="panel"><div className="panel-head"><div><h2>Trailer & side-door projection</h2><p>Illustrates the onboard load at each delivery or pickup.</p></div><Pill tone="warn">Schematic</Pill></div><div className="ops-toggle small-toggle"><button type="button" onClick={()=>setSelectedStop(-1)} className={selectedStop<0?'chosen':''}>At depot</button>{(truck?.events||[]).slice(0,5).map((e,i)=><button type="button" key={i} className={selectedStop===i?'chosen':''} onClick={()=>setSelectedStop(i)}>#{i+1}</button>)}</div><CargoProjection route={truck} selectedStop={selectedStop} shipments={shipments}/><Notice tone="warn">Side doors are illustrated only. Cargo dimensions, door opening and physical load configuration are not verified.</Notice></section>
 <section className="panel"><div className="panel-head"><h2>Driver shift & availability</h2><Pill tone="warn">Not legal HOS</Pill></div>{truck&&<><p className="ops-driver-name">{truck.driver} on {truck.vehicle} · {truck.truck_type}</p><div className="shift-track"><span style={{width:`${Math.min(100,100*(truck.driver_hours.scheduled_on_duty_min/Math.max(1,totalShift)))}%`}}/></div><div className="hours-grid"><div><small>On duty (estimate)</small><b>{minuteDuration(truck.driver_hours.scheduled_on_duty_min)}</b></div><div><small>Driving (13h cap)</small><b>{minuteDuration(truck.driver_hours.estimated_drive_min)}</b></div><div><small>Work remaining (13h cap)</small><b>{minuteDuration(truck.driver_hours.remaining_shift_min)}</b></div><div><small>Return time</small><b>{time(truck.finish_min)}</b></div></div></>}
 <div className="ops-divider"/><h3>All drivers</h3>{routes.map(r=><div className="mini-driver" key={r.driver}><span><b>{r.driver}</b> · {r.vehicle}</span><span>{time(r.finish_min)} finish · {minuteDuration(r.driver_hours.remaining_shift_min)} duty left · {minuteDuration(r.driver_hours.remaining_drive_min)} driving left</span></div>)}
 </section></aside></div>
 {recovery&&scenario!=='none'&&<section className="panel wait-panel"><div className="panel-head"><div><h2>Wait for the next driver to finish</h2><p>Candidates ordered by completion time; all modeled trucks return to the depot, so actual nearest driver cannot be determined without GPS. Selecting Wait tests pickup only AFTER the existing run.</p></div><Pill tone="warn">Needs confirmation</Pill></div><div className="wait-grid">{recovery.waiting_drivers.map(d=><div className="wait-driver" key={d.driver}><b>{d.driver} · {d.truck}</b><strong>{time(d.free_at_min)}</strong><span>Estimated available time</span><small>{minuteDuration(d.remaining_shift_min)} duty left · {minuteDuration(d.remaining_drive_min)} driving left</small></div>)}</div></section>}
 </>}
 <Notice tone="warn">Map uses approximate city centers and synthetic demo stops. Road geometry comes from a public routing service when available; it does NOT drive assignment ETAs or validate truck access. Capacity checks reported skid and pound limits plus demo volume at every stop; a 13-hour project workday is modeled. Physical loading and legal HOS are not verified. Do not use for real transportation decisions.</Notice>
 </>;
}

function App(){
 const [page,setPage]=useState('overview');
 const [plan,setPlan]=useState(null);
 const [orders,setOrders]=useState([]);
 const [meta,setMeta]=useState(null);
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const [absent,setAbsent]=useState(false);
 const [notice,setNotice]=useState('');
 const [mapTruck,setMapTruck]=useState('T01');
 const openMap=vehicle=>{setMapTruck(vehicle);setPage('map');};
 const onStartRoute=async(vehicle)=>{
  if(!window.confirm(`Start ${vehicle}'s demo route with its currently assigned cargo? The manifest will be locked.`))return;
  setBusy(true);setError('');setNotice('');
  try{const result=await api('/fleet/'+vehicle+'/start',{method:'POST'});await refresh(null);setAbsent(false);setMapTruck(vehicle);setPage('map');setNotice(result.message+' · '+vehicle+' is now Delivering.');}
  catch(e){setError(e.message)}finally{setBusy(false)}
 };
 const onRelease=async(vehicle)=>{
  setBusy(true);setError('');setNotice('');
  try{await api('/fleet/'+vehicle+'/release',{method:'POST'});await refresh(null);setAbsent(false);setNotice(`${vehicle} released from emergency reserve. It can now be loaded.`)}
  catch(e){setError(e.message)}finally{setBusy(false)}
 };
 async function refresh(driver=absent?'D01':null){
  const [p,o,m]=await Promise.all([api('/plan'+(driver?'?absent_driver='+encodeURIComponent(driver):'')),api('/orders'),api('/meta')]);
  setPlan(p);setOrders(o.orders);setMeta(m);return p;
 }
 async function run(driver=absent?'D01':null){setBusy(true);setError('');setNotice('');try{await refresh(driver);setAbsent(!!driver)}catch(e){setError(e.message)}finally{setBusy(false)}}
 useEffect(()=>{run(null)},[]);
 const onCreated=async(result)=>{const p=await refresh(absent?'D01':null);const actual=p.routes.find(r=>r.shipments.includes(result?.shipment_id));setMapTruck(actual?.vehicle||result?.requested_vehicle||'T01');setNotice('Order saved. Check the selected truck route on the geographic map.');};
 const onAssign=async(id,vehicle)=>{setBusy(true);setError('');try{await api('/orders/'+id+'/assign',{method:'POST',body:JSON.stringify({requested_vehicle:vehicle})});await refresh(absent?'D01':null);setNotice(vehicle?`Order pinned to ${vehicle} under demo constraints. Route updated.`:'Automatic truck assignment restored.');}catch(e){setError(e.message)}finally{setBusy(false)}};
 const onDelete=async(id)=>{if(!window.confirm(`Delete demo order B${String(id).padStart(3,'0')}?`))return;setBusy(true);setError('');try{await api('/orders/'+id,{method:'DELETE'});await refresh(absent?'D01':null);setNotice('Order removed from the demo planning queue.')}catch(e){setError(e.message)}finally{setBusy(false)}};
 const navigation=[['overview','Command center','chart'],['board','Dispatch board','truck'],['new','New B2B order','plus'],['orders','Orders','box'],['fleet','Fleet & drivers','truck'],['map','Truck route map','route'],['studio','Recovery & trailer studio','refresh']];
 return <><header className="app-header"><div className="header-inner"><button className="brand brand-company" onClick={()=>setPage('overview')}><img src="/trans-ontario-logo.png" alt="Trans Ontario Express" className="company-logo"/><span className="brand-product"><b>TRANSOPT AI</b><small>DISPATCH INTELLIGENCE · TEAM #35</small></span></button><div className="header-right"><span className="top-tagline">Smarter Freight, Smarter Routes</span><span className="top-avatar">35</span></div></div></header>
 <div className="nav-shell"><nav className="nav-tabs" aria-label="Main navigation">{navigation.map(([id,label,icon])=><button key={id} className={page===id?'active':''} onClick={()=>setPage(id)}><Mark type={icon}/>{label}</button>)}</nav></div>
 <main className="content">
 {error&&<Notice tone="error">{error} <button className="text-button" onClick={()=>run(absent?'D01':null)}>Retry</button></Notice>}
 {notice&&<Notice tone="success">{notice}</Notice>}
 {page==='overview'&&<Overview plan={plan} orders={orders} loading={busy} absent={absent} onOptimize={()=>run(absent?'D01':null)} onAbsent={()=>run('D01')} onReset={()=>run(null)} onStartRoute={onStartRoute} onOpenMap={openMap}/>}
 {page==='new'&&<NewOrder meta={meta} onCreated={async(result)=>{await onCreated(result);setPage('map')}}/>}
 {page==='orders'&&<Orders orders={orders} meta={meta} plan={plan} onDelete={onDelete} onAssign={onAssign} busy={busy}/>}
 {page==='fleet'&&<Fleet plan={plan} onStartRoute={onStartRoute} onRelease={onRelease} onOpenMap={openMap} busy={busy}/>}
 {page==='map'&&<FleetWideMap plan={plan} initialTruck={mapTruck} onNewOrder={()=>setPage('new')} onStartRoute={onStartRoute} busy={busy}/>}
 {page==='studio'&&<Operations plan={plan} onAddOrder={()=>setPage('new')}/>}
 {page==='board'&&<DispatchBoard plan={plan} onRefresh={()=>run(absent?'D01':null)} onStartRoute={onStartRoute} onRelease={onRelease} onOpenMap={openMap} onNewOrder={()=>setPage('new')} busy={busy}/>}
 <footer><span>Trans Ontario Express · TransOpt AI · Team #35 · Prototype v0.9</span><span>SIMULATED FLEET · Not connected to live vehicles, GPS, traffic or legal HOS compliance</span></footer></main>
 </>;
}
createRoot(document.getElementById('root')).render(<App/>);
