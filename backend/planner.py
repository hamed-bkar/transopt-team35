"""Transparent prototype dispatcher: synthetic positions, heuristic pickup/drop insertion.

Fleet weight and skid capacities are USER-REPORTED and require independent verification.
Configured 13-hour *total work* limit is a conservative PROJECT policy, not a
complete representation of Canadian hours-of-service legislation.
"""
from dataclasses import dataclass
from math import hypot

LB_PER_KG = 2.20462262185
WORKDAY_START_MIN = 8 * 60
PROJECT_MAX_WORK_MIN = 13 * 60
PROJECT_MAX_DRIVE_MIN = 13 * 60


@dataclass(frozen=True)
class Shipment:
    id: str
    weight_kg: float
    volume_m3: float
    x: float
    y: float
    due_min: int = 1020
    service_min: int = 15
    equipment: str = 'dry'
    pickup_x: float = 0.0
    pickup_y: float = 0.0
    pickup_at_depot: bool = True
    cargo_type: str = 'general'
    skids: int = 1
    skids_verified: bool = True


@dataclass(frozen=True)
class Vehicle:
    id: str
    driver: str
    max_weight_kg: float
    max_volume_m3: float
    equipment: str = 'dry'
    shift_end_min: int = WORKDAY_START_MIN + PROJECT_MAX_WORK_MIN
    skid_limit: int = 26
    truck_type: str = 'unspecified'
    weight_limit_lb: int = 0
    skid_capacity_estimated: bool = False
    volume_capacity_estimated: bool = True


SHIPMENTS = [
    Shipment('S01',900,5,3,5,780,skids=2), Shipment('S02',1500,9,6,8,900,skids=2),
    Shipment('S03',700,4,4,7,840), Shipment('S04',1800,11,12,4,960,skids=3),
    Shipment('S05',1200,8,11,7,930,skids=2), Shipment('S06',950,6,8,3,990,skids=2),
    Shipment('S07',1300,8,2,12,900,skids=2), Shipment('S08',600,4,8,12,990),
    Shipment('S09',800,5,13,10,1020), Shipment('S10',1100,7,15,5,1020,skids=2),
    Shipment('S11',900,6,5,13,1020,skids=2), Shipment('S12',1400,9,14,13,1020,skids=2),
]


def vehicle(id, driver, kind, weight_lb, skids, volume, estimated_skids=False):
    return Vehicle(
        id=id, driver=driver, max_weight_kg=weight_lb / LB_PER_KG,
        max_volume_m3=volume, skid_limit=skids, truck_type=kind,
        weight_limit_lb=weight_lb, skid_capacity_estimated=estimated_skids,
    )


VEHICLES = [
    vehicle('T01','D01','Single-axle straight truck',15000,12,36),
    vehicle('T02','D02','53-ft tandem-axle trailer',44000,26,75),
    vehicle('T03','D03','53-ft tri-axle trailer',64000,26,95,estimated_skids=False),
    vehicle('T04','D04','Single-axle straight truck',15000,12,36),
    vehicle('T05','D05','53-ft tandem-axle trailer',44000,26,75),
    vehicle('T06','D06','Single-axle straight truck',15000,12,36),
    vehicle('T07','D07','53-ft tri-axle trailer',64000,26,95),
    vehicle('T08','D08','Single-axle straight truck (emergency reserve)',15000,12,36),
    vehicle('T09','D09','53-ft tandem-axle trailer (emergency reserve)',44000,26,75),
    vehicle('T10','D10','53-ft tandem-axle trailer',44000,26,75),
]


def distance(a, b):
    return hypot(a[0]-b[0],a[1]-b[1])


def route_metrics(stops, vehicle):
    """Evaluate loads and deadlines after EVERY stop, including skid turnover.

    Depot cargo is loaded at departure. Nondepot pickups add freight when visited.
    Clock uses demo travel-time scalar. Real road / HOS / access is NOT verified.
    """
    current = (0.0,0.0)
    clock = WORKDAY_START_MIN
    total_distance = 0.0
    drive_minutes = 0
    service_minutes = 0
    late = []
    prior_pickups, seen_drops = set(), set()
    depot_shipments = {s.id:s for action,s in stops if action=='drop' and s.pickup_at_depot}
    onboard = set(depot_shipments)
    load_w = sum(s.weight_kg for s in depot_shipments.values())
    load_v = sum(s.volume_m3 for s in depot_shipments.values())
    load_skids = sum(s.skids for s in depot_shipments.values())
    peak_w,peak_v,peak_skids = load_w,load_v,load_skids
    capacity_violation = (load_w > vehicle.max_weight_kg + 1e-8 or
                          load_v > vehicle.max_volume_m3 + 1e-8 or
                          load_skids > vehicle.skid_limit)
    ordering_violation = False
    events = []
    for action,s in stops:
        coords = (s.pickup_x,s.pickup_y) if action=='pickup' else (s.x,s.y)
        delta = distance(current, coords)
        total_distance += delta
        leg_min = round(delta*5)
        drive_minutes += leg_min
        clock += leg_min
        eta = clock
        if action=='pickup':
            if s.id in prior_pickups or s.id in depot_shipments:
                ordering_violation = True
            prior_pickups.add(s.id)
            onboard.add(s.id)
            load_w += s.weight_kg
            load_v += s.volume_m3
            load_skids += s.skids
        elif action=='drop':
            if s.id in seen_drops or (not s.pickup_at_depot and s.id not in prior_pickups):
                ordering_violation = True
            seen_drops.add(s.id)
            onboard.discard(s.id)
            if clock > s.due_min:
                late.append(s.id)
            load_w -= s.weight_kg
            load_v -= s.volume_m3
            load_skids -= s.skids
        else:
            ordering_violation = True
        peak_w,peak_v,peak_skids = max(peak_w,load_w),max(peak_v,load_v),max(peak_skids,load_skids)
        if (load_w > vehicle.max_weight_kg + 1e-8 or load_v > vehicle.max_volume_m3 + 1e-8
                or load_skids > vehicle.skid_limit or load_w < -1e-8 or load_v < -1e-8
                or load_skids < 0):
            capacity_violation = True
        events.append({
            'type':action,'shipment':s.id,'eta_min':eta,
            'due_min':s.due_min if action=='drop' else None,
            'late':action=='drop' and eta>s.due_min,
            'x':coords[0],'y':coords[1],'leg_minutes':leg_min,
            'onboard_shipments':sorted(onboard),
            'onboard_weight_kg':round(load_w,2),
            'onboard_weight_lb':round(load_w*LB_PER_KG),
            'onboard_volume_m3':round(load_v,2),
            'onboard_skids':load_skids,
            'skid_space_left':vehicle.skid_limit-load_skids,
        })
        clock += s.service_min
        service_minutes += s.service_min
        current = coords
    home = distance(current,(0,0)) if stops else 0.0
    total_distance += home
    home_min = round(home*5)
    clock += home_min
    drive_minutes += home_min
    if stops and (abs(load_w)>1e-8 or abs(load_v)>1e-8 or load_skids != 0):
        ordering_violation = True
    duty = clock - WORKDAY_START_MIN
    work_cap = min(PROJECT_MAX_WORK_MIN,vehicle.shift_end_min-WORKDAY_START_MIN)
    work_violation = duty>work_cap
    drive_violation = drive_minutes>PROJECT_MAX_DRIVE_MIN
    return {
        'distance_units':round(total_distance,2),'finish_min':clock,
        'late_shipments':late,
        'shift_violation':work_violation or drive_violation,
        'work_violation':work_violation,'drive_violation':drive_violation,
        'capacity_violation':capacity_violation,'ordering_violation':ordering_violation,
        'peak_weight_kg':round(peak_w,2),
        'peak_weight_lb':round(peak_w*LB_PER_KG),
        'peak_volume_m3':round(peak_v,2),'peak_skids':peak_skids,
        'events':events,
        'driver_hours':{
            'shift_start_min':WORKDAY_START_MIN,
            'shift_end_min':min(WORKDAY_START_MIN+PROJECT_MAX_WORK_MIN,vehicle.shift_end_min),
            'max_work_min':work_cap,'max_drive_min':PROJECT_MAX_DRIVE_MIN,
            'scheduled_on_duty_min':duty,'estimated_drive_min':drive_minutes,
            'estimated_service_min':service_minutes,
            'remaining_shift_min':max(0,work_cap-duty),
            'remaining_drive_min':max(0,PROJECT_MAX_DRIVE_MIN-drive_minutes),
            'work_violation':work_violation,'drive_violation':drive_violation,
            'actual_hos_verified':False,
        },
    }


def insertions(existing,s):
    """Enumerate all pickup/drop insertion placements, pickup strictly before drop."""
    if s.pickup_at_depot:
        for i in range(len(existing)+1):
            yield existing[:i]+[('drop',s)]+existing[i:]
    else:
        for pickup_index in range(len(existing)+1):
            with_pickup=existing[:pickup_index]+[('pickup',s)]+existing[pickup_index:]
            for drop_index in range(pickup_index+1,len(with_pickup)+1):
                yield with_pickup[:drop_index]+[('drop',s)]+with_pickup[drop_index:]


def serialize_route(vehicle,stops):
    metrics=route_metrics(stops,vehicle)
    return {
        'vehicle':vehicle.id,'driver':vehicle.driver,
        'truck_type':vehicle.truck_type,
        'skid_limit':vehicle.skid_limit,
        'skid_capacity_estimated':vehicle.skid_capacity_estimated,
        'volume_capacity_estimated':vehicle.volume_capacity_estimated,
        'weight_limit_lb':vehicle.weight_limit_lb,
        'weight_limit_kg':round(vehicle.max_weight_kg,2),
        'fleet_weight_rating_unverified':True,
        'shipments':[s.id for action,s in stops if action=='drop'],
        'stop_sequence':[('P:' if action=='pickup' else 'D:')+s.id for action,s in stops],
        'weight_kg':metrics['peak_weight_kg'],
        'volume_m3':metrics['peak_volume_m3'],
        'skids':metrics['peak_skids'],
        'volume_limit_m3':vehicle.max_volume_m3,
        **metrics,
    }


def feasible(metric):
    return not (metric['late_shipments'] or metric['shift_violation']
                or metric['capacity_violation'] or metric['ordering_violation'])


def plan(shipments=None,vehicles=None,absent_driver=None,preferred_assignments=None,fixed_routes=None,blocked_vehicle_ids=None):
    if shipments is None: shipments=SHIPMENTS
    if vehicles is None: vehicles=VEHICLES
    if absent_driver is not None and absent_driver not in {v.driver for v in vehicles}:
        raise ValueError('Unknown driver')
    available=[v for v in vehicles if v.driver!=absent_driver]
    assignments={v.id:[] for v in available}
    fixed_routes=fixed_routes or {}
    blocked_vehicle_ids=set(blocked_vehicle_ids or ())
    by_shipment={s.id:s for s in shipments}
    fixed_shipment_ids=set()
    for truck_id,stop_codes in fixed_routes.items():
        if truck_id not in assignments:
            continue
        events=[]
        for code in stop_codes:
            if not isinstance(code,str) or len(code)<3 or code[:2] not in ('P:','D:'):
                raise ValueError('Corrupt saved dispatch manifest')
            shipment=by_shipment.get(code[2:])
            if shipment is None:
                raise ValueError('Dispatched order is missing; restore the order before planning')
            events.append(('pickup' if code.startswith('P:') else 'drop',shipment))
            fixed_shipment_ids.add(shipment.id)
        assignments[truck_id]=events
    rejected=[]
    preferred_assignments=preferred_assignments or {}
    # Locked shipments are placed first. Missing pinned vehicles must not silently fall back.
    ordered=sorted((s for s in shipments if s.id not in fixed_shipment_ids),key=lambda item:(item.id not in preferred_assignments,item.due_min,-item.weight_kg,item.id))
    for s in ordered:
        if not s.skids_verified:
            rejected.append({'shipment':s.id,'reason':'Legacy order has no declared skid count; verify or recreate order before planning.'})
            continue
        locked_vehicle=preferred_assignments.get(s.id)
        if locked_vehicle and locked_vehicle not in {v.id for v in available}:
            rejected.append({'shipment':s.id,'reason':f'Pinned truck {locked_vehicle} is unavailable. Dispatcher must approve reassignment.'})
            continue
        choices=[]
        for v in available:
            if v.id in blocked_vehicle_ids or v.id in fixed_routes:continue
            if locked_vehicle and v.id!=locked_vehicle:continue
            if v.equipment!=s.equipment:continue
            current=assignments[v.id]
            before=route_metrics(current,v)['distance_units']
            for candidate in insertions(current,s):
                metrics=route_metrics(candidate,v)
                if not feasible(metrics):continue
                choices.append((round(metrics['distance_units']-before,7),metrics['distance_units'],v.id,candidate))
        if not choices:
            if locked_vehicle and locked_vehicle in (blocked_vehicle_ids | set(fixed_routes)):
                reason=f'Truck {locked_vehicle} is already en route or held for emergency backup; select a dispatchable vehicle.'
            elif locked_vehicle:
                reason=f'Pinned assignment to {locked_vehicle} fails equipment, capacity, pickup/drop order, ETA or modeled driver hours.'
            elif not any(v.equipment==s.equipment for v in available):
                reason=f'No available truck has required {s.equipment} equipment.'
            elif all(v.skid_limit<s.skids or v.max_weight_kg<s.weight_kg or v.max_volume_m3<s.volume_m3 for v in available if v.equipment==s.equipment):
                reason='Shipment exceeds individual compatible truck skid, weight or estimated volume capacity.'
            else:
                reason='No feasible insertion: capacity (skids, weight, volume), delivery deadline or 13-hour work/driving rule.'
            rejected.append({'shipment':s.id,'reason':reason})
        else:
            best=min(choices,key=lambda x:(x[0],x[1],x[2]))
            assignments[best[2]]=best[3]
    routes=[serialize_route(v,assignments[v.id]) for v in available]
    return {
        'mode':'SYNTHETIC DEMONSTRATION',
        'algorithm':'manual truck locks followed by cheapest feasible pickup/drop insertion (not globally optimal)',
        'absent_driver':absent_driver,'routes':routes,'unassigned':rejected,
        'assigned_count':sum(len(r['shipments']) for r in routes),
        'total_shipments':len(shipments),
        'total_distance_units':round(sum(r['distance_units'] for r in routes),2),
        'assumptions':[
            'Fleet weight ratings (15,000 / 44,000 / 64,000 lb) and 12 / 26 skids are user-reported and have not been confirmed as legal payloads.',
            'Manufacturer-style 53-ft tri-axle 26-skid listing is published by Trans Ontario; still confirm the individual trailer configuration and legal payload.',
            'Demo shipment coordinates and travel times are modeled; order city coordinates are approximate and do not replace a street-level pickup/drop address.',
            'Project policy limits the modeled work shift to 13 hours from 08:00; driving is also capped at 13 hours. Legal on-duty, rest, cycle, qualifications and actual log compliance are NOT fully checked.',
            'Weight, skid count and estimated volume are checked after every pickup and delivery; physical loading, doors, axle loads and securement are NOT verified.',
            'Orders and quotes are demonstrations, not actual carrier prices or delivery commitments.',
            'Do not use this demonstration for live dispatch.',
        ],
    }


if __name__=='__main__':
    import json
    print(json.dumps(plan(),indent=2))
