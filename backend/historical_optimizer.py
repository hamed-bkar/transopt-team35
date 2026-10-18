"""Educational historical route ordering scenario using OR-Tools.

Not a safe dispatch plan: straight-line distances, no arrival windows, cargo safety,
vehicle restrictions, verified load, driver law, or traffic. Pickup dependencies are
not reconstructed, so only all-drop interior routes are accepted.
"""
from math import asin,cos,radians,sin,sqrt

class UnsupportedHistoricalRoute(ValueError):pass
class OptimizerUnavailable(RuntimeError):pass


def haversine_m(a,b):
    lat1,lon1=radians(a['lat']),radians(a['lng'])
    lat2,lon2=radians(b['lat']),radians(b['lng'])
    x=sin((lat2-lat1)/2)**2+cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return round(2*6371000*asin(min(1,sqrt(x))))


def chain_length(points,sequence):
    return sum(haversine_m(points[i],points[j]) for i,j in zip(sequence,sequence[1:]))


def compare_route(route):
    p=route['points']
    if len(p)<4 or len(p)>35:
        raise UnsupportedHistoricalRoute('Choose a route with 4–35 geolocated stops.')
    if not route.get('final') or route.get('deleted'):
        raise UnsupportedHistoricalRoute('Only final, non-deleted historical routes are eligible.')
    if not all(s['type'].strip().upper() in ('DROP-OFF','DROP','DELIVERY') for s in p[1:-1]):
        raise UnsupportedHistoricalRoute('Exploratory reordering is restricted to drop-only intermediate stops. Pickup precedence and mixed-service constraints are not validated.')
    try:
        from ortools.constraint_solver import routing_enums_pb2,pywrapcp
    except ImportError as exc:
        raise OptimizerUnavailable('Google OR-Tools is not installed. Run: py -m pip install -r requirements-optimization.txt') from exc
    n=len(p)
    # Keep first and final locations fixed; reorder only intermediate stops.
    manager=pywrapcp.RoutingIndexManager(n,1,[0],[n-1])
    model=pywrapcp.RoutingModel(manager)
    def transit(i,j):return haversine_m(p[manager.IndexToNode(i)],p[manager.IndexToNode(j)])
    cb=model.RegisterTransitCallback(transit)
    model.SetArcCostEvaluatorOfAllVehicles(cb)
    params=pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy=routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic=routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(2)
    solution=model.SolveWithParameters(params)
    if not solution:raise UnsupportedHistoricalRoute('The distance-only demonstration could not find a sequence.')
    index=model.Start(0);order=[]
    while not model.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index=solution.Value(model.NextVar(index))
    order.append(manager.IndexToNode(index))
    historical=list(range(n))
    baseline_m=chain_length(p,historical)
    candidate_m=chain_length(p,order)
    return {
        'route_id':route['id'],'algorithm':'OR-Tools geometric TSP with fixed first/last stops',
        'historical_order':historical,'candidate_order':order,
        'historical_direct_line_km':round(baseline_m/1000,2),
        'candidate_direct_line_km':round(candidate_m/1000,2),
        'geometry_only_difference_km':round((baseline_m-candidate_m)/1000,2),
        'actual_recorded_road_km':route['actual_km'],
        'not_dispatchable':True,
        'warnings':[
            'Experimental route ordering only; not a feasible dispatch recommendation.',
            'Uses great-circle segments, not drivable roads, travel time, or traffic.',
            'No customer appointments, actual driver hours, truck loading or securement are enforced.',
            'Historical road distance must NOT be compared numerically with geometric scenario distance for claimed savings.',
            'Start/end points are held fixed; only intermediate drop-only stops are reordered.',
        ],
    }
