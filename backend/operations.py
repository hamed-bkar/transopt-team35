"""Operational simulation helpers. Route geometry, driver time, recovery alternatives.

Synthetic scenarios only. These functions cannot authorize real dispatch.
"""
from dataclasses import replace
from planner import VEHICLES, SHIPMENTS, insertions, plan, route_metrics, serialize_route, feasible
from locations import DEPOT, to_latlng, ZONES


def route_points(route):
    """Draw the actual model's planned stop order, not the historical chart."""
    return [{'type':'depot','shipment':None,'x':0,'y':0,'lat':DEPOT['lat'],'lng':DEPOT['lng'],'location':DEPOT['label'],'eta_min':480}]+[
        {'type':e['type'],'shipment':e['shipment'],'x':e['x'],'y':e['y'],
         'lat':to_latlng(e['x'],e['y'])[0], 'lng':to_latlng(e['x'],e['y'])[1],
         'location':next((z['label'] for z in ZONES.values() if abs(z['x']-e['x'])<1e-5 and abs(z['y']-e['y'])<1e-5),
                          'Synthetic example stop'), 'eta_min':e['eta_min'],
         'due_min':e.get('due_min'),'onboard_shipments':e['onboard_shipments']}
        for e in route['events']
    ]+([{'type':'return','shipment':None,'x':0,'y':0,'lat':DEPOT['lat'],'lng':DEPOT['lng'],'location':DEPOT['label'],'eta_min':route['finish_min']}] if route['events'] else [])


def render_plan(plan_result):
    return {**plan_result, 'routes':[{**r,'points':route_points(r)} for r in plan_result['routes']]}


def _from_baseline(r, shipment_index):
    return [(('pickup' if key.startswith('P:') else 'drop'),shipment_index[key[2:]]) for key in r['stop_sequence']]



def incremental_recovery(shipments, baseline, disabled_vehicle):
    """Keep unaffected drivers' stop ordering, insert just displaced shipments."""
    lookup={s.id:s for s in shipments}
    candidates=[v for v in VEHICLES if v.id!=disabled_vehicle]
    initial={r['vehicle']:r for r in baseline['routes']}
    assignments={v.id:_from_baseline(initial[v.id], lookup) for v in candidates}
    displaced=[lookup[code] for code in initial[disabled_vehicle]['shipments']]
    rejected=[]
    for shipment in sorted(displaced, key=lambda s:(s.due_min,-s.weight_kg,s.id)):
        best=None
        for vehicle in candidates:
            if vehicle.equipment!=shipment.equipment:continue
            original=assignments[vehicle.id]
            previous=route_metrics(original,vehicle)['distance_units']
            for insertion in insertions(original,shipment):
                metric=route_metrics(insertion,vehicle)
                if not feasible(metric):
                    continue
                score=(round(metric['distance_units']-previous,6),metric['finish_min'],vehicle.id)
                if best is None or score<best[0]:best=(score,vehicle.id,insertion)
        if best: assignments[best[1]]=best[2]
        else: rejected.append({'shipment':shipment.id,'reason':'Cannot insert without breaking a demo capacity, time-window or shift constraint.'})
    routes=[serialize_route(v, assignments[v.id]) for v in candidates]
    return {'mode':'SYNTHETIC DEMONSTRATION','algorithm':'preserve unaffected routes, insert displaced freight',
            'routes':routes,'unassigned':rejected,
            'total_shipments':len(shipments),'assigned_count':sum(len(r['shipments']) for r in routes),
            'total_distance_units':round(sum(r['distance_units'] for r in routes),2),
            'assumptions':baseline['assumptions']}



def wait_for_finished_driver(shipments, baseline, disabled_vehicle):
    """Use an EXISTING route's driver only after that driver returns to the depot.

    Cargo transfer/presence at depot is hypothetical and clearly conditional.
    The runner can only pick up displaced freight after finishing their current jobs.
    """
    lookup={s.id:s for s in shipments}
    by_id={v.id:v for v in VEHICLES if v.id!=disabled_vehicle}
    original={r['vehicle']:r for r in baseline['routes']}
    displaced=[lookup[code] for code in original[disabled_vehicle]['shipments']]
    assignments={vid:_from_baseline(original[vid],lookup) for vid in by_id}
    # Waiting drivers are ranked by when the current run finishes, then closest
    # to the transfer point (depot is their known *simulated final* location).
    ranking=sorted((vid for vid in by_id if original[vid]['shipments']),
                   key=lambda vid:(original[vid]['finish_min'],0,vid))
    chosen_driver=None
    rejected=[]
    for s in sorted(displaced,key=lambda s:(s.due_min,s.id)):
        selection=None
        for vid in ranking:
            truck=by_id[vid]
            if truck.equipment!=s.equipment:continue
            existing=assignments[vid]
            # The extra freight is NOT on board during existing stops.
            # Convert it to a physical pickup at the transfer depot.
            transfer=replace(s,pickup_at_depot=False,pickup_x=0.0,pickup_y=0.0)
            # If earlier displaced freight was inserted, it is already part of
            # this sequence. All additional pickups are placed AFTER existing
            # baseline route events; each must precede its own delivery.
            baseline_length=len(_from_baseline(original[vid],lookup))
            for i in range(baseline_length,len(existing)+1):
                for j in range(i+1,len(existing)+2):
                    with_pickup=existing[:i]+[('pickup',transfer)]+existing[i:]
                    trial=with_pickup[:j]+[('drop',transfer)]+with_pickup[j:]
                    result=route_metrics(trial,truck)
                    if not feasible(result):continue
                    # Rank early availability, earliest ETA for this shipment,
                    # then minimal added distance.
                    delivered=next(e for e in result['events'] if e['shipment']==s.id and e['type']=='drop')
                    score=(original[vid]['finish_min'],delivered['eta_min'],result['distance_units'],vid)
                    if selection is None or score<selection[0]:selection=(score,vid,trial)
        if selection is None:
            rejected.append({'shipment':s.id,'reason':'No post-route depot pickup can reach deadline within remaining 13-hour simulated duty/drive time and capacities.'})
        else:
            assignments[selection[1]]=selection[2]
            chosen_driver=selection[1]
    routes=[serialize_route(v,assignments[vid]) for vid,v in by_id.items()]
    return {'mode':'SYNTHETIC DEMONSTRATION','algorithm':'post-route depot-transfer recovery after driver finishes',
            'routes':routes,'unassigned':rejected,'total_shipments':len(shipments),
            'assigned_count':sum(len(r['shipments']) for r in routes),
            'total_distance_units':round(sum(r['distance_units'] for r in routes),2),
            'selected_returning_truck':chosen_driver,
            'assumptions':baseline['assumptions']}


def recovery_options(shipments=None, unavailable='D01', failure_type='driver'):
    """Rank defensible conditional scenarios. Does not assert a physical transfer is feasible."""
    shipments=SHIPMENTS if shipments is None else shipments
    if failure_type not in ('driver','truck'):
        raise ValueError('failure_type must be driver or truck')
    if unavailable not in ('D01','T01'):
        raise ValueError('This demo models D01 absence or T01 breakdown.')
    disabled='T01'
    normal=render_plan(plan(shipments=shipments))
    original=next(r for r in normal['routes'] if r['vehicle']==disabled)
    alternate=render_plan(plan(shipments=shipments,absent_driver='D01'))
    preserved=render_plan(incremental_recovery(shipments,normal,disabled))
    waited=render_plan(wait_for_finished_driver(shipments,normal,disabled))
    idle=next((r for r in normal['routes'] if not r['shipments'] and r['vehicle']!=disabled),None)
    all_options=[]
    if idle:
        spare_vehicle=next(v for v in VEHICLES if v.id==idle['vehicle'])
        down_vehicle=next(v for v in VEHICLES if v.id==disabled)
        if failure_type=='driver':
            # Swap D04 to T01; T04 becomes idle. Original route still needs qualification verification.
            available=[replace(v,driver=spare_vehicle.driver) if v.id==disabled else v for v in VEHICLES if v.id!=idle['vehicle']]
            option_plan=render_plan(plan(shipments=shipments,vehicles=available))
            label=f'Standby driver {spare_vehicle.driver} → truck {disabled}'
            explanation='An idle driver could take the existing truck if licensed, rested, available and approved.'
        else:
            # Original D01 uses idle backup truck. Existing T04 driver no longer operates this shift.
            available=[replace(v,driver=down_vehicle.driver) if v.id==spare_vehicle.id else v for v in VEHICLES if v.id!=disabled]
            option_plan=render_plan(plan(shipments=shipments,vehicles=available))
            label=f'Backup truck {spare_vehicle.id} + driver D01'
            explanation='Backup equipment may replace the broken truck if compatible and freight can be transferred safely.'
        all_options.append({'id':'standby','label':label,'priority':1,'approach':'Immediate alternative driver/truck',
            'explanation':explanation,'plan':option_plan,'verification':['Driver qualifications and current hours-of-service','Truck equipment and cargo transfer feasibility'],
            'status':'conditional'})
    all_options.append({'id':'preserve','label':'Keep active routes, insert displaced stops','priority':2,
        'approach':'Available space on other trucks','explanation':'Preserve unaffected sequences, then insert disrupted shipments only where demo capacity, ETA and shift limits permit.',
        'plan':preserved,'verification':['Cargo access at transfer location','Traffic and actual driver duty records'],
        'status':'conditional'})
    all_options.append({'id':'wait','label':'Wait for an eligible driver to finish','priority':3,
        'approach':'Return to depot, then pick up displaced freight',
        'explanation':'A driver finishes their existing stops and returns to the demo depot BEFORE collecting displaced freight. Unreachable deadlines are rejected, not hidden.',
        'plan':waited,'verification':['Physical freight transfer to the depot','Driver location, actual available duty hours, rest and remaining deadlines'],
        'status':'conditional'})
    all_options.append({'id':'reopt','label':'Reoptimize remaining available fleet','priority':4,'approach':'Recalculate all eligible routes',
        'explanation':'Rebuild routes using remaining trucks. Existing driver stops may change and must be approved.',
        'plan':alternate,'verification':['Dispatcher approval and customer notifications','Actual loading feasibility and regulatory hours'],
        'status':'conditional'})
    # Drivers who finish earliest first; latest end-of-shift and current location are simulated.
    waiting=sorted(({'driver':r['driver'],'truck':r['vehicle'],'free_at_min':r['finish_min'],
                     'remaining_shift_min':r['driver_hours']['remaining_shift_min'],
                     'remaining_drive_min':r['driver_hours']['remaining_drive_min'],
                     'at_depot':True,'estimated_distance_to_demo_depot':0,
                     'post_route_position_is_demo_depot':True,
                     'live_distance_to_transfer_unknown':True,
                     'can_start_new_run':r['driver_hours']['remaining_shift_min']>0}
                    for r in normal['routes'] if r['vehicle']!=disabled and r['shipments']),
                   key=lambda x:(x['free_at_min'],x['estimated_distance_to_demo_depot']))
    # Do not claim that a finished driver can meet deadlines: requires live location, rest and pickup location.
    return {'scenario':{'failure_type':failure_type,'unavailable':unavailable,
                        'disabled_vehicle':disabled,'displaced_shipments':original['shipments']},
            'baseline':normal,
            'options':all_options,
            'waiting_drivers':waiting,
            'decision_rule':'Compare standby, existing spare capacity, waiting for an eligible returning driver, and full replanning. Never select options with impossible modeled constraints.',
            'notice':'All options are conditional simulations, not approved dispatch. Drivers are assumed to end their planned run at the demo depot; actual nearest driver cannot be ranked without live GPS, qualifications and cargo-transfer availability. Legal HOS is not verified.'}
