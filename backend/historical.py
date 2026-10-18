"""Read Trans Ontario historical XLSX files and publish a redacted, read-only dataset.

No spreadsheet dependency: streaming Office Open XML decoding via Python stdlib.
Historical observations are NOT truck-capacity, HOS-compliance, or routing permissions.
Never include names, street addresses, phone numbers, order IDs or customer IDs in cache.
"""
from __future__ import annotations
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

DATA_DIR=Path(__file__).resolve().parent/'data'
CACHE=DATA_DIR/'history.json'
TAG='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
CELL=re.compile(r'^([A-Z]+)\d+$')


def _col_letters_to_int(letters):
    index=0
    for ch in letters:
        index=index*26+ord(ch)-64
    return index-1


def _strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():return []
    result=[]
    with z.open('xl/sharedStrings.xml') as stream:
        for _ev,elem in ET.iterparse(stream,events=('end',)):
            if elem.tag==TAG+'si':
                result.append(''.join(t.text or '' for t in elem.iter(TAG+'t')))
                elem.clear()
    return result


def read_sheet(file, sheet, fields):
    """Yield selected columns from a spreadsheet worksheet; ignore all other fields."""
    with zipfile.ZipFile(file) as z:
        shared=_strings(z)
        with z.open(f'xl/worksheets/sheet{sheet}.xml') as stream:
            header={}
            for _event,row in ET.iterparse(stream,events=('end',)):
                if row.tag!=TAG+'row':continue
                values={}
                for cell in row.findall(TAG+'c'):
                    ref=cell.get('r','');match=CELL.match(ref)
                    if not match:continue
                    col=_col_letters_to_int(match.group(1))
                    if header and col not in header:continue
                    val=cell.find(TAG+'v')
                    if val is not None and val.text is not None:
                        text=val.text
                        if cell.get('t')=='s':text=shared[int(text)]
                        elif cell.get('t') in ('n',None):
                            try:
                                numeric=float(text)
                                text=int(numeric) if numeric.is_integer() else numeric
                            except ValueError:pass
                    else:
                        inline=cell.find(TAG+'is')
                        text=''.join(t.text or '' for t in inline.iter(TAG+'t')) if inline is not None else None
                    if text is not None:values[col]=text
                if not header:
                    header={col:str(value) for col,value in values.items() if str(value) in fields}
                    missing=set(fields)-set(header.values())
                    if missing:raise ValueError(f'{file.name}, sheet {sheet}: missing expected fields {sorted(missing)}')
                else:
                    yield {name:values.get(idx) for idx,name in header.items()}
                row.clear()


def number(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None


def present(value):return value is not None and str(value).strip()!=''


def data_quality(routes,stops,legs,days,summary_days):
    def ratio(count,total):return {'count':count,'total':total,'pct':round(count*100/total,1) if total else 0}
    weight=sum(1 for s in stops if (number(s.get('weight_lb')) or 0)>0)
    latlong=sum(1 for s in stops if valid_coordinate(s.get('lat'),s.get('lng')))
    appointments=sum(1 for s in stops if present(s.get('appt_utc')) or present(s.get('appt_local')))
    actual_arr=sum(1 for s in stops if present(s.get('actual_arr_utc')))
    actual_km=sum(1 for r in routes if (number(r.get('actual_dist_km')) or 0)>0)
    duration=sum(1 for r in routes if (number(r.get('duration_min')) or 0)>0)
    hos=sum(1 for d in days if (number(d.get('hos_drive_min')) or 0)>0)
    load=sum(1 for s in stops if present(s.get('skid_spots')) or present(s.get('linear_feet')))
    return [
        {'field':'Stop GPS coordinates','coverage':ratio(latlong,len(stops)),'source':'routing / stops','supports':'Historical geographic plot; direct-line approximate geometry','limit':'No road-network distances, traffic, restrictions or live location'},
        {'field':'Actual stop arrival','coverage':ratio(actual_arr,len(stops)),'source':'routing / stops','supports':'Compare recorded stop times','limit':'Past arrivals are not future ETA commitments'},
        {'field':'Shipment/stop weight (lb)','coverage':ratio(weight,len(stops)),'source':'routing / stops','supports':'Historical reported weight where populated','limit':'Not verified onboard load; missing values cannot be treated as 0'},
        {'field':'Appointment timestamp','coverage':ratio(appointments,len(stops)),'source':'routing / stops','supports':'Historical appointment review for populated stops','limit':'Cannot treat missing appointment as flexible commitment'},
        {'field':'Route actual distance','coverage':ratio(actual_km,len(routes)),'source':'routing / routes','supports':'Observed route distance benchmarks','limit':'Not interchangeable with direct-line distance'},
        {'field':'Route duration','coverage':ratio(duration,len(routes)),'source':'routing / routes','supports':'Observed duration review','limit':'Includes recorded operating conditions'},
        {'field':'HOS driving log (nonzero)','coverage':ratio(hos,len(days)),'source':'routing / driver_days','supports':'Investigate logged hours where available','limit':'Zero or blank can indicate unavailable data, not legal remaining hours'},
        {'field':'Loading-space hints','coverage':ratio(load,len(stops)),'source':'routing / stops','supports':'Potential skid/linear-foot requirements','limit':'No complete dimensions, trailer dimensions, packing or door geometry'},
    ]


def valid_coordinate(lat,lng):
    a,b=number(lat),number(lng)
    return a is not None and b is not None and -90<=a<=90 and -180<=b<=180 and (a!=0 or b!=0)


def create_history(routing_file,driver_summary_file,output=CACHE):
    routing_file=Path(routing_file);driver_summary_file=Path(driver_summary_file)
    if not routing_file.is_file() or not driver_summary_file.is_file():raise FileNotFoundError('Both historical Excel files are required.')
    route_fields=['route_id','route_name','driver_code','service_date','is_final','deleted_in_samsara','n_stops','n_orders','actual_dist_km','planned_dist_km','duration_min','n_appt_risk','n_appt_missed']
    stop_fields=['route_id','seq','actual_seq','kind','stop_type','lat','lng','weight_lb','skid_spots','linear_feet','appt_utc','appt_local','actual_arr_utc','actual_dep_utc','dwell_min','travel_from_prev_min','equipment_requested','special_handling']
    leg_fields=['route_id','ordno','action','weight']
    day_fields=['driver_code','day','n_routes','n_stops','hos_drive_min','hos_on_duty_min','actual_dist_km','vehicles']
    simple_fields=['Driver','Date','Routes','Stops visited','Logged driving (hours)','Logged on duty (hours)','Vehicle(s)']
    routes=list(read_sheet(routing_file,2,route_fields))
    stops=list(read_sheet(routing_file,3,stop_fields))
    legs=list(read_sheet(routing_file,4,leg_fields))
    days=list(read_sheet(routing_file,5,day_fields))
    summary_days=list(read_sheet(driver_summary_file,2,simple_fields))
    # Cross-check two independently exported driver-day summaries by date + driver code.
    independent={}
    for d in summary_days:
        code=str(d.get('Driver') or '').split(' ')[0].split('–')[0].strip()
        independent[(code,str(d.get('Date')))]=d
    count_matched=0;stop_disagreements=0
    for d in days:
        other=independent.get((str(d.get('driver_code')),str(d.get('day'))))
        if not other:continue
        count_matched+=1
        if int(number(d.get('n_stops')) or 0)!=int(number(other.get('Stops visited')) or 0):
            stop_disagreements+=1
    # All observations are retained in summary counts. Public-facing cache never copies identifiers or names.
    stops_by_route=defaultdict(list)
    for stop in stops:stops_by_route[str(stop['route_id'])].append(stop)
    days_by_driver_date={(str(d['driver_code']),str(d['day'])):d for d in days}
    visible=[]
    for route in routes:
        id_key=str(route['route_id'])
        rs=stops_by_route[id_key]
        coordinates=[]
        for row in sorted(rs,key=lambda r:(number(r['actual_seq']) or number(r['seq']) or 99999)):
            if not valid_coordinate(row['lat'],row['lng']):continue
            coordinates.append({
                'seq':int(number(row['actual_seq']) or number(row['seq']) or 0),
                'lat':round(float(row['lat']),6),'lng':round(float(row['lng']),6),
                'type':str(row.get('kind') or row.get('stop_type') or 'Unknown')[:28],
                'weight_reported':(number(row.get('weight_lb')) or 0)>0,
                'appointment_recorded':present(row.get('appt_utc')) or present(row.get('appt_local')),
                'arrived_recorded':present(row.get('actual_arr_utc')),
            })
        day=days_by_driver_date.get((str(route['driver_code']),str(route['service_date'])),{})
        visible.append({
            'id':id_key,'label':str(route['route_name'])[:32],
            'date':str(route['service_date']),'driver':f"Driver {route['driver_code']}",
            'n_stops':int(number(route.get('n_stops')) or 0),'n_orders':int(number(route.get('n_orders')) or 0),
            'actual_km':number(route.get('actual_dist_km')),'planned_km':number(route.get('planned_dist_km')),
            'duration_min':number(route.get('duration_min')),
            'final':str(route.get('is_final')) in ('1','True','true'),
            'deleted':str(route.get('deleted_in_samsara')) in ('1','True','true'),
            'driver_day_hos_minutes':number(day.get('hos_drive_min')),
            'driver_day_on_duty_minutes':number(day.get('hos_on_duty_min')),
            'points':coordinates,
        })
    visible.sort(key=lambda r:(r['date'],r['driver'],r['label'],r['id']))
    per_date=Counter(str(r['service_date']) for r in routes)
    total_real_km=[number(r['actual_dist_km']) for r in routes if (number(r.get('actual_dist_km')) or 0)>0]
    report={
        'version':'0.4.0',
        'sources':{'routing_report':routing_file.name,'driver_day_summary':driver_summary_file.name},
        'date_range':[min(per_date),max(per_date)] if per_date else [],
        'counts':{'routes':len(routes),'stops':len(stops),'order_legs':len(legs),'routing_driver_days':len(days),'summary_driver_days':len(summary_days), 'days':len(per_date)},
        'historical_metrics':{'recorded_route_km_total':round(sum(total_real_km),1),'route_distance_observations':len(total_real_km),'driver_day_crosscheck_matched':count_matched,'driver_day_stop_count_disagreements':stop_disagreements},
        'daily_routes':dict(sorted(per_date.items())),
        'coverage':data_quality(routes,stops,legs,days,summary_days),
        'gaps':[
            {'name':'Truck capacities','status':'Unavailable','description':'No verified GVWR, cargo capacity, trailer internal dimensions, axle limits or free space per assignment.'},
            {'name':'Realistic cargo loading','status':'Unavailable','description':'Some stop weights and skid/linear-feet hints exist, but physical item dimensions, stability, door access and unload geometry are incomplete.'},
            {'name':'Legal driver/vehicle availability','status':'Not validated','description':'HOS observations do not establish remaining hours, licences, rest cycles or the actual future roster.'},
            {'name':'Pickup and drop commitments','status':'Partial','description':'Historical stop sequence and some appointment data exist; future windows and priority are not complete.'},
            {'name':'Road travel time matrix','status':'Unavailable','description':'Stored GPS and historical observed km exist; cannot infer route-specific road-network travel between arbitrary stops.'},
            {'name':'Pricing and partner carriers','status':'Unavailable','description':'No verified commercial pricing, partnership capacity or service terms in these spreadsheets.'},
        ],
        'warnings':[
            'Historical observations only. No live truck, driver, or shipment availability is provided.',
            'Driver labels are derived from driver codes; names and street addresses are removed from the packaged cache.',
            'Some observations may be revisions or incomplete. Filter to relevant final routes before comparing outcomes.',
            'GPS polylines represent direct segments between actual stops, not drivable roads.',
            'Never use historical route comparisons as proof of safe, legal, or feasible alternative dispatch plans.',
        ],
        'routes':visible,
    }
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return report


def get_history():
    if not CACHE.exists():return None
    return json.loads(CACHE.read_text(encoding='utf-8'))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Generate a redacted route cache from the two source XLSX reports.')
    parser.add_argument('routing',type=Path)
    parser.add_argument('driver_summary',type=Path)
    parser.add_argument('--output',type=Path,default=CACHE)
    args=parser.parse_args()
    report=create_history(args.routing,args.driver_summary,args.output)
    print(json.dumps({'counts':report['counts'],'range':report['date_range'],'coverage':report['coverage']},indent=2))
