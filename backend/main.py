"""TransOpt AI v0.3: demo order quotes, persistence and pickup/drop routing."""
import os
import sqlite3
import base64
import hmac
from datetime import datetime, timezone
from dataclasses import asdict
from contextlib import contextmanager
from math import hypot
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from planner import SHIPMENTS, VEHICLES, Shipment, plan, LB_PER_KG, PROJECT_MAX_WORK_MIN, PROJECT_MAX_DRIVE_MIN
from operations import render_plan, recovery_options
from historical import get_history
from historical_optimizer import compare_route, UnsupportedHistoricalRoute, OptimizerUnavailable
from locations import ZONES, DEPOT, LONG_HAUL, LEGACY_PRESETS
from fleet_state import fleet_states,planning_constraints,start_vehicle,release_backup

app=FastAPI(title='TransOpt AI Demo API',version='0.8.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],
    allow_methods=['GET','POST','DELETE'],
    allow_headers=['*'],
)



@app.middleware('http')
async def demo_team_access(request, call_next):
    """Require shared HTTP Basic access for deployed demo; leave local dev open."""
    if request.url.path == '/health':
        return await call_next(request)
    if os.getenv('TRANSOPT_REQUIRE_AUTH') != '1':
        return await call_next(request)
    secret = os.getenv('TRANSOPT_DEMO_PASSWORD', '')
    if not secret:
        return JSONResponse(status_code=503, content={'detail': 'Team access password has not been configured.'})
    encoded = request.headers.get('authorization', '')
    ok = False
    if encoded.startswith('Basic '):
        try:
            decoded = base64.b64decode(encoded[6:], validate=True).decode('utf-8')
            username, password = decoded.split(':', 1)
            ok = hmac.compare_digest(username.encode(), b'team') and hmac.compare_digest(password.encode(), secret.encode())
        except (UnicodeDecodeError, ValueError):
            pass
    if not ok:
        return JSONResponse(
            status_code=401,
            content={'detail': 'Team sign-in required.'},
            headers={'WWW-Authenticate': 'Basic realm="TransOpt Team Demo"', 'Cache-Control': 'no-store'},
        )
    return await call_next(request)


@app.get('/health')
def health():
    return {'status': 'ok'}


CARGO={
    'general':{'label':'General merchandise','equipment':'dry','handling':0},
    'ambient_food':{'label':'Non-refrigerated food','equipment':'dry','handling':12},
    'fragile':{'label':'Fragile / sensitive handling','equipment':'dry','handling':24},
    'temperature_sensitive':{'label':'Temperature controlled','equipment':'reefer','handling':50},
}

class OrderRequest(BaseModel):
    customer: str=Field(min_length=2,max_length=80)
    pickup_zone: str
    drop_zone: str
    weight_kg: Optional[float]=Field(default=None,gt=0,le=30000)
    length_cm: Optional[float]=Field(default=None,gt=0,le=2000)
    width_cm: Optional[float]=Field(default=None,gt=0,le=1000)
    height_cm: Optional[float]=Field(default=None,gt=0,le=1000)
    cargo_type: str='general'
    skids: Optional[int]=Field(default=None,ge=1,le=26)
    delivery_by: str='16:00'
    requested_vehicle: Optional[str]=None


def db_path():
    return Path(os.getenv('TRANSOPT_DB',str(Path(__file__).resolve().parent/'transopt_demo.db')))

@contextmanager
def connection():
    conn=sqlite3.connect(db_path())
    conn.row_factory=sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer TEXT NOT NULL, pickup_zone TEXT NOT NULL, drop_zone TEXT NOT NULL,
        weight_kg REAL NOT NULL, volume_m3 REAL NOT NULL, cargo_type TEXT NOT NULL,
        due_min INTEGER NOT NULL, quoted_cad REAL NOT NULL, created_at TEXT NOT NULL,
        skids INTEGER NOT NULL DEFAULT 1, skids_assumed INTEGER NOT NULL DEFAULT 1,
        requested_vehicle TEXT DEFAULT NULL
    )''')
    existing={row[1] for row in conn.execute('PRAGMA table_info(orders)')}
    if 'skids' not in existing:
        conn.execute('ALTER TABLE orders ADD COLUMN skids INTEGER NOT NULL DEFAULT 1')
    if 'skids_assumed' not in existing:
        conn.execute('ALTER TABLE orders ADD COLUMN skids_assumed INTEGER NOT NULL DEFAULT 1')
    if 'requested_vehicle' not in existing:
        conn.execute('ALTER TABLE orders ADD COLUMN requested_vehicle TEXT DEFAULT NULL')
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_request(order):
    if order.pickup_zone not in ZONES or order.drop_zone not in ZONES:
        raise HTTPException(status_code=422,detail='Choose valid demo pickup and destination zones.')
    if order.pickup_zone==order.drop_zone:
        raise HTTPException(status_code=422,detail='Pickup and destination must be different.')
    if order.requested_vehicle is not None and order.requested_vehicle not in {v.id for v in VEHICLES}:
        raise HTTPException(status_code=422,detail='Choose an available fleet vehicle ID or Auto assignment.')
    if order.cargo_type not in CARGO:
        raise HTTPException(status_code=422,detail='Unsupported cargo category.')
    try:
        hours,minutes=map(int,order.delivery_by.split(':'))
        if not (0<=hours<=23 and 0<=minutes<=59) or len(order.delivery_by)!=5:
            raise ValueError()
    except (TypeError,ValueError):
        raise HTTPException(status_code=422,detail='Delivery time must be HH:MM, e.g. 15:30.')
    due=hours*60+minutes
    if due<600 or due>1080:
        raise HTTPException(status_code=422,detail='Demo delivery window must be between 10:00 and 18:00.')
    return due


def quote(order):
    due=validate_request(order)
    dims=[order.length_cm,order.width_cm,order.height_cm]
    has_dims=all(v is not None for v in dims)
    complete=order.weight_kg is not None and has_dims
    declared_skids=order.skids is not None
    weight=order.weight_kg if order.weight_kg is not None else 750.0
    volume=round(dims[0]*dims[1]*dims[2]/1_000_000,3) if has_dims else 5.0
    a,b=ZONES[order.pickup_zone],ZONES[order.drop_zone]
    distance_units=hypot(a['x']-b['x'],a['y']-b['y'])
    base=28
    transport=distance_units*4.75
    weight_fee=weight*.018
    volume_fee=volume*4.5
    handling=CARGO[order.cargo_type]['handling']
    urgency=25 if due<780 else 0
    subtotal=base+transport+weight_fee+volume_fee+handling+urgency
    # Incentivize early verified weight; greater incentive when dimensions are also supplied.
    discount_rate=.05 if complete else (.02 if order.weight_kg is not None else 0)
    discount=round(subtotal*discount_rate,2)
    estimated=round(subtotal-discount,2)
    assumptions=[]
    if order.weight_kg is None: assumptions.append('Weight unknown: assumed 750 kg for provisional pricing.')
    if not declared_skids: assumptions.append('Skid count not provided: required before dispatch; no skid capacity is assumed for planning.')
    if not has_dims: assumptions.append('One or more dimensions missing: assumed 5 m³ for provisional pricing.')
    if order.cargo_type=='temperature_sensitive':
        assumptions.append('Refrigerated equipment is required and the demo fleet has none.')
    if order.pickup_zone in LONG_HAUL or order.drop_zone in LONG_HAUL:
        assumptions.append('Cross-region route: same-day model is insufficient for long-haul commitments. Requires multi-day scheduling/partner-carrier review.')
    return {
        'estimated_cad':estimated, 'currency':'CAD','provisional':not (complete and declared_skids),
        'information_discount_cad':discount,'information_discount_rate':discount_rate,
        'weight_used_kg':round(weight,2),'weight_used_lb':round(weight*LB_PER_KG),
        'declared_skids':order.skids,'volume_used_m3':round(volume,3),
        'distance_units':round(distance_units,2), 'due_min':due,
        'eligible_for_submission':complete and declared_skids,
        'equipment_required':CARGO[order.cargo_type]['equipment'],
        'breakdown':{'base_cad':base,'distance_cad':round(transport,2),'weight_cad':round(weight_fee,2),'space_cad':round(volume_fee,2),'handling_cad':handling,'urgent_cad':urgency,'completeness_discount_cad':discount},
        'assumptions':assumptions,
        'disclaimer':'Approximate city coordinates and arbitrary demo pricing only. Not a carrier quote or verified delivery commitment.',
    }


def stored_orders():
    with connection() as db:
        rows=db.execute('SELECT * FROM orders ORDER BY id DESC').fetchall()
    return [dict(r) for r in rows]


def preferred_assignments():
    return {f"B{o['id']:03d}":o['requested_vehicle'] for o in stored_orders() if o.get('requested_vehicle')}


def dispatch_plan(shipments=None, locks=None):
    with connection() as db:
        states=fleet_states(db)
    fixed,blocked=planning_constraints(states)
    planned=plan(shipments=shipments if shipments is not None else all_shipments(),
                 preferred_assignments=locks if locks is not None else preferred_assignments(),
                 fixed_routes=fixed,blocked_vehicle_ids=blocked)
    for route in planned['routes']:
        state=states[route['vehicle']]
        route['dispatch_status']=state['status']
        route['started_at']=state['started_at']
        route['dispatch_locked']=state['status']=='delivering'
    planned['fleet_summary']={status:sum(v['status']==status for v in states.values()) for status in ('delivering','available','standby')}
    return planned


@app.get('/api/fleet')
def get_fleet():
    return {'vehicles':dispatch_plan()['routes'],'note':'Fleet statuses are saved simulated scenarios, NOT connected to live GPS or carrier telematics.'}


@app.post('/api/fleet/{vehicle_id}/start')
def start_route(vehicle_id:str):
    current=dispatch_plan()
    route=next((r for r in current['routes'] if r['vehicle']==vehicle_id),None)
    if route is None:raise HTTPException(status_code=404,detail='Unknown truck.')
    if route['dispatch_status']=='delivering':raise HTTPException(status_code=409,detail='Route already started.')
    if route['dispatch_status']=='standby':raise HTTPException(status_code=409,detail='Release this emergency reserve truck first.')
    if not route['shipments']:raise HTTPException(status_code=409,detail='Cannot start an empty truck. Assign cargo first.')
    if route['capacity_violation'] or route['late_shipments'] or route['shift_violation'] or route['ordering_violation']:
        raise HTTPException(status_code=409,detail='This dispatch plan fails one or more modeled feasibility checks.')
    with connection() as db:
        try:start_vehicle(db,vehicle_id,route['stop_sequence'])
        except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc))
    return {'vehicle':vehicle_id,'status':'delivering','manifest':route['stop_sequence'],
            'message':'Demo route started and manifest frozen. This is not a live dispatch event.'}


@app.post('/api/fleet/{vehicle_id}/release')
def release_truck(vehicle_id:str):
    with connection() as db:
        try:release_backup(db,vehicle_id)
        except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc))
    return {'vehicle':vehicle_id,'status':'available','message':'Emergency reserve released into the demo dispatchable pool.'}

def all_shipments():
    dynamic=[]
    for o in stored_orders():
        origin=ZONES[o['pickup_zone']]
        destination=ZONES[o['drop_zone']]
        dynamic.append(Shipment(
            id=f"B{o['id']:03d}",weight_kg=o['weight_kg'],volume_m3=o['volume_m3'],
            x=destination['x'],y=destination['y'],due_min=o['due_min'],
            equipment=CARGO[o['cargo_type']]['equipment'],
            pickup_x=origin['x'],pickup_y=origin['y'],
            pickup_at_depot=o['pickup_zone']=='central',cargo_type=o['cargo_type'],
            skids=o['skids'],skids_verified=not bool(o['skids_assumed']),
        ))
    return SHIPMENTS+dynamic

@app.get('/api/meta')
def meta():
    fleet_status={r['vehicle']:r['dispatch_status'] for r in dispatch_plan()['routes']}
    return {'zones':{key:value['label'] for key,value in ZONES.items() if key not in LEGACY_PRESETS},
            'cargo_types':{key:value['label'] for key,value in CARGO.items()},
            'version':'0.8.0','mode':'SYNTHETIC DEMONSTRATION',
            'locations':{k:{'label':v['label'],'lat':v['lat'],'lng':v['lng']} for k,v in ZONES.items() if k not in LEGACY_PRESETS},
            'depot':DEPOT,
            'vehicle_options': [{'id':v.id,'label':v.truck_type,'skids':v.skid_limit,'weight_lb':v.weight_limit_lb,'dispatch_status':fleet_status.get(v.id,'available')} for v in VEHICLES],
            'fleet_source':'Reported vehicle weight/skid limits, unverified payload ratings; volume simulated',
            'project_work_limit_hours':PROJECT_MAX_WORK_MIN/60,
            'project_driving_limit_hours':PROJECT_MAX_DRIVE_MIN/60}

@app.get('/api/data')
def data():
    return {'shipments':[asdict(s) for s in all_shipments()],
            'vehicles':[asdict(v) for v in VEHICLES],
            'source':'12 synthetic base shipments plus user-entered orders with approximate real-city map locations',
            'fleet_disclaimer':'Published 26-skid tri-axle configuration; truck-specific safe legal payload/axle loading unverified, volume caps are simulation assumptions.'}

@app.get('/api/plan')
def get_plan(absent_driver:Optional[str]=Query(None)):
    try: return render_plan(dispatch_plan() if absent_driver is None else plan(shipments=all_shipments(),absent_driver=absent_driver,preferred_assignments=preferred_assignments()))
    except ValueError as error:raise HTTPException(status_code=422,detail=str(error))

@app.get('/api/recovery')
def get_recovery(failure_type:str='driver'):
    try:
        return recovery_options(shipments=all_shipments(),unavailable='D01' if failure_type=='driver' else 'T01',failure_type=failure_type)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

@app.post('/api/quote')
def get_quote(order:OrderRequest):
    return quote(order)

@app.get('/api/orders')
def get_orders():
    return {'orders':stored_orders()}

def check_manual_assignment(order, exclude_id=None):
    """Validate locked vehicle selection against the whole simulated plan.
    Never tell a dispatcher an order was placed on a truck if feasibility failed.
    """
    if not order.requested_vehicle: return None
    estimate=quote(order)
    if not estimate['eligible_for_submission']:
        raise HTTPException(status_code=422,detail='Weight, skids and dimensions are required for truck assignment.')
    orig=all_shipments()
    locks=preferred_assignments()
    if exclude_id is not None:
        orig=[s for s in orig if s.id!=f'B{exclude_id:03d}']
        locks.pop(f'B{exclude_id:03d}',None)
    current=dispatch_plan(shipments=orig,locks=locks)
    baseline_rejected={x['shipment'] for x in current['unassigned']}
    origin=ZONES[order.pickup_zone]; dest=ZONES[order.drop_zone]
    incoming=Shipment(id='BPREVIEW',weight_kg=order.weight_kg,
                      volume_m3=estimate['volume_used_m3'],x=dest['x'],y=dest['y'],
                      due_min=estimate['due_min'],equipment=CARGO[order.cargo_type]['equipment'],
                      pickup_x=origin['x'],pickup_y=origin['y'],pickup_at_depot=order.pickup_zone=='central',
                      cargo_type=order.cargo_type,skids=order.skids)
    trial=dispatch_plan(shipments=orig+[incoming],locks={**locks,'BPREVIEW':order.requested_vehicle})
    assignment=next((r for r in trial['routes'] if 'BPREVIEW' in r['shipments']),None)
    newly_rejected=[r for r in trial['unassigned'] if r['shipment'] not in baseline_rejected and r['shipment']!='BPREVIEW']
    if not assignment or newly_rejected:
        issues=[r['reason'] for r in trial['unassigned'] if r['shipment']=='BPREVIEW']
        if newly_rejected: issues.append('Assignment would displace existing feasible shipments: '+', '.join(x['shipment'] for x in newly_rejected))
        raise HTTPException(status_code=409,detail='Cannot place this order on '+order.requested_vehicle+'. '+' '.join(issues or ['No feasible route found.']))
    return {'vehicle':assignment['vehicle'],'driver':assignment['driver'],
            'arrival':next((e['eta_min'] for e in assignment['events'] if e['shipment']=='BPREVIEW' and e['type']=='drop'),None),
            'peak_skids':assignment['peak_skids'],'limit_skids':assignment['skid_limit'],
            'peak_weight_lb':assignment['peak_weight_lb'],'limit_weight_lb':assignment['weight_limit_lb'],
            'estimated_finish':assignment['finish_min'],
            'note':'Conditional prototype feasibility, not verified road, load, driver or carrier commitment.'}

@app.post('/api/assignment-preview')
def assignment_preview(order:OrderRequest):
    if not order.requested_vehicle:
        return {'selection':'auto','message':'Auto assignment selects the cheapest feasible demonstration insertion.'}
    return check_manual_assignment(order)

@app.post('/api/orders/{order_id}/assign')
def assign_existing_order(order_id:int, request:dict):
    target=request.get('requested_vehicle')
    if target is not None and target not in {v.id for v in VEHICLES}:
        raise HTTPException(status_code=422,detail='Unknown truck ID.')
    with connection() as db:
        record=db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
    if not record: raise HTTPException(status_code=404,detail='Order not found.')
    if target or record['requested_vehicle']:
        with connection() as db:
            states=fleet_states(db)
        if any(f'B{order_id:03d}' in (code[2:] for code in state['manifest']) for state in states.values() if state['status']=='delivering'):
            raise HTTPException(status_code=409,detail='Cannot reassign an order in a started route manifest.')
    if target:
        o=dict(record)
        hh,mm=divmod(o['due_min'],60)
        fields={'customer':o['customer'],'pickup_zone':o['pickup_zone'],'drop_zone':o['drop_zone'],
                'weight_kg':o['weight_kg'],'skids':o['skids'],'cargo_type':o['cargo_type'],
                'delivery_by':f'{hh:02d}:{mm:02d}','requested_vehicle':target}
        # Original dimensions are not stored; reconstruct equivalent volume, not original footprint.
        edge_cm=max(1, (o['volume_m3'] ** (1/3))*100)
        fields.update({'length_cm':edge_cm,'width_cm':edge_cm,'height_cm':edge_cm})
        if o['skids_assumed']:
            raise HTTPException(status_code=422,detail='Legacy shipment needs a verified skid count before assignment.')
        check_manual_assignment(OrderRequest(**fields),exclude_id=order_id)
    with connection() as db:
        db.execute('UPDATE orders SET requested_vehicle=? WHERE id=?',(target,order_id))
    return {'id':order_id,'requested_vehicle':target,'message':'Assignment preference updated. Feasible only under demonstration assumptions.'}

@app.post('/api/orders',status_code=201)
def create_order(order:OrderRequest):
    estimate=quote(order)
    if not estimate['eligible_for_submission']:
        raise HTTPException(status_code=422,detail='Declared weight, all 3 dimensions, and number of skids are required for demo dispatch. Provisional quotes cannot be scheduled.')
    if order.requested_vehicle:
        check_manual_assignment(order)
    with connection() as db:
        cursor=db.execute('''INSERT INTO orders
            (customer,pickup_zone,drop_zone,weight_kg,volume_m3,cargo_type,due_min,quoted_cad,created_at,skids,skids_assumed,requested_vehicle)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(
                order.customer.strip(),order.pickup_zone,order.drop_zone,order.weight_kg,
                estimate['volume_used_m3'],order.cargo_type,estimate['due_min'],
                estimate['estimated_cad'],datetime.now(timezone.utc).isoformat(),order.skids,0,order.requested_vehicle))
        order_id=cursor.lastrowid
    # A created order is recorded, not guaranteed feasible or promised.
    new_plan=dispatch_plan()
    assigned=any(f'B{order_id:03d}' in r['shipments'] for r in new_plan['routes'])
    return {'id':order_id,'shipment_id':f'B{order_id:03d}',
            'message':'Order added to simulated planning queue. Dispatch is not confirmed.',
            'tentatively_assigned':assigned,'requested_vehicle':order.requested_vehicle,'quote':estimate}

@app.delete('/api/orders/{order_id}')
def delete_order(order_id:int):
    with connection() as db:
        states=fleet_states(db)
    code=f'B{order_id:03d}'
    if any(code in (stop[2:] for stop in state['manifest']) for state in states.values() if state['status']=='delivering'):
        raise HTTPException(status_code=409,detail='Cannot delete cargo already included in a started demo route.')
    with connection() as db:
        cursor=db.execute('DELETE FROM orders WHERE id=?',(order_id,))
    if cursor.rowcount==0:
        raise HTTPException(status_code=404,detail='Order not found.')
    return {'deleted':order_id}


# Historical analysis APIs are kept strictly separate from the fictional dispatch planner.
# They serve a redacted local cache of the two sponsor workbooks.
@app.get('/api/history/overview')
def historical_overview():
    report=get_history()
    if report is None:
        raise HTTPException(status_code=503,detail='Historical data cache missing. See README import instructions.')
    return {k:v for k,v in report.items() if k!='routes'}

@app.get('/api/history/routes')
def historical_routes(date:Optional[str]=Query(None),eligible_only:bool=False,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    report=get_history()
    if report is None:raise HTTPException(status_code=503,detail='Historical cache missing.')
    routes=report['routes']
    if date:routes=[r for r in routes if r['date']==date]
    if eligible_only:routes=[r for r in routes if eligible_for_geometry(r)]
    return {'total':len(routes),'offset':offset,'routes':[{k:v for k,v in r.items() if k!='points'}|{'geolocated_stops':len(r['points']),'geometry_eligible':eligible_for_geometry(r)} for r in routes[offset:offset+limit]]}

def eligible_for_geometry(r):
    p=r['points']
    return 4<=len(p)<=35 and r['final'] and not r['deleted'] and all(s['type'].strip().upper() in ('DROP-OFF','DROP','DELIVERY') for s in p[1:-1])

@app.get('/api/history/routes/{route_id}')
def historical_route(route_id:str):
    report=get_history()
    if report is None:raise HTTPException(status_code=503,detail='Historical cache missing.')
    route=next((r for r in report['routes'] if r['id']==route_id),None)
    if route is None:raise HTTPException(status_code=404,detail='Route not found.')
    return route|{'geometry_eligible':eligible_for_geometry(route)}

@app.post('/api/history/routes/{route_id}/what-if')
def historical_route_what_if(route_id:str):
    route=historical_route(route_id)
    try:return compare_route(route)
    except UnsupportedHistoricalRoute as exc:raise HTTPException(status_code=422,detail=str(exc))
    except OptimizerUnavailable as exc:raise HTTPException(status_code=503,detail=str(exc))


# Keep this mount LAST: all existing /api endpoints and /docs are registered above.
# In local development Vite still serves the frontend as before.
STATIC_DIR = Path(__file__).resolve().parent / 'static'
if STATIC_DIR.is_dir():
    app.mount('/', StaticFiles(directory=str(STATIC_DIR), html=True), name='frontend')
