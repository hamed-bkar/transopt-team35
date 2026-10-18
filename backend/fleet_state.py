"""Persistent simulated fleet dispatch states, separate from actual live vehicle tracking.

The prototype never assumes a button press proves a driver left the depot.
Snapshots freeze the shipment sequence of demo routes that have been started.
"""
import json
from datetime import datetime, timezone
from planner import SHIPMENTS, VEHICLES, plan

DEFAULT_STATUS = {**{f'T{i:02d}':'available' for i in range(1,11)}, 'T01':'delivering','T03':'delivering','T08':'standby','T09':'standby'}


def ensure_fleet(db):
    db.execute('''CREATE TABLE IF NOT EXISTS fleet_dispatch (
        vehicle_id TEXT PRIMARY KEY, status TEXT NOT NULL,
        started_at TEXT, manifest_json TEXT
    )''')
    current={row[0] for row in db.execute('SELECT vehicle_id FROM fleet_dispatch')}
    if len(current)==len(VEHICLES):
        return
    # Four-truck v0.7 baseline gives visible delivery loads to both T01 and T03.
    baseline=plan(shipments=SHIPMENTS,vehicles=VEHICLES[:4],preferred_assignments={
        'S07':'T01','S01':'T01','S11':'T03','S12':'T03','S04':'T02','S05':'T02'
    })
    manifests={r['vehicle']:r['stop_sequence'] for r in baseline['routes']}
    for truck in VEHICLES:
        if truck.id in current:continue
        state=DEFAULT_STATUS.get(truck.id,'available')
        db.execute('INSERT INTO fleet_dispatch(vehicle_id,status,started_at,manifest_json) VALUES (?,?,?,?)',
                   (truck.id,state,'SIMULATED INITIAL ROUTE' if state=='delivering' else None,
                    json.dumps(manifests[truck.id]) if state=='delivering' else None))
    db.commit()


def fleet_states(db):
    ensure_fleet(db)
    return {r['vehicle_id']:{'status':r['status'],'started_at':r['started_at'],
                             'manifest':json.loads(r['manifest_json']) if r['manifest_json'] else []}
            for r in db.execute('SELECT * FROM fleet_dispatch')}


def planning_constraints(states):
    fixed={key:row['manifest'] for key,row in states.items() if row['status']=='delivering'}
    blocked=[key for key,row in states.items() if row['status'] in ('delivering','standby')]
    return fixed,blocked


def start_vehicle(db, vehicle_id, stop_sequence):
    if not stop_sequence:raise ValueError('Load this vehicle with at least one shipment before starting a route.')
    row=fleet_states(db).get(vehicle_id)
    if row is None:raise ValueError('Unknown fleet vehicle.')
    if row['status']=='standby':raise ValueError('This vehicle is reserved for emergencies. Release it to Available first.')
    if row['status']=='delivering':raise ValueError('This vehicle is already shown as delivering.')
    db.execute('UPDATE fleet_dispatch SET status=?,started_at=?,manifest_json=? WHERE vehicle_id=?',
               ('delivering',datetime.now(timezone.utc).isoformat(),json.dumps(stop_sequence),vehicle_id))
    db.commit()


def release_backup(db, vehicle_id):
    row=fleet_states(db).get(vehicle_id)
    if row is None:raise ValueError('Unknown fleet vehicle.')
    if row['status']!='standby':raise ValueError('Only standby trucks may be released.')
    db.execute("UPDATE fleet_dispatch SET status='available' WHERE vehicle_id=?",(vehicle_id,))
    db.commit()
