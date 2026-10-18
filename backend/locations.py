"""Approximate geographic demo presets. Never substitute for a customer street address.
The depot address is publicly listed by Trans Ontario Express.
Local optimization coordinates use ~3 kilometres per demonstration unit.
"""
from math import cos, radians
DEPOT = {'label':'Trans Ontario Express • Scarborough depot', 'lat':43.8158, 'lng':-79.2361, 'address':'2215 Markham Rd, Scarborough, ON M1B 2W3'}
CITY_PRESETS = {
    'central': ('Trans Ontario depot • Scarborough', 43.8158, -79.2361),
    'scarborough': ('Scarborough, ON',43.775,-79.257),
    'toronto': ('Toronto, ON',43.6532,-79.3832),
    'markham': ('Markham, ON',43.8561,-79.3370),
    'vaughan': ('Vaughan, ON',43.8372,-79.5083),
    'mississauga': ('Mississauga, ON',43.5890,-79.6441),
    'brampton': ('Brampton, ON',43.7315,-79.7624),
    'burlington': ('Burlington, ON',43.3255,-79.7990),
    'hamilton': ('Hamilton, ON',43.2557,-79.8711),
    'niagara_falls': ('Niagara Falls, ON',43.0896,-79.0849),
    'oakville': ('Oakville, ON',43.4675,-79.6877),
    'oshawa': ('Oshawa, ON',43.8971,-78.8658),
    'whitby': ('Whitby, ON',43.8975,-78.9429),
    'kitchener': ('Kitchener, ON',43.4516,-80.4925),
    'london': ('London, ON',42.9849,-81.2453),
    'ottawa': ('Ottawa, ON',45.4215,-75.6972),
    'montreal': ('Montréal, QC',45.5019,-73.5674),
    'quebec_city': ('Québec City, QC',46.8139,-71.2080),
    'winnipeg': ('Winnipeg, MB',49.8951,-97.1384),
    'regina': ('Regina, SK',50.4452,-104.6189),
    'saskatoon': ('Saskatoon, SK',52.1332,-106.6700),
    'calgary': ('Calgary, AB',51.0447,-114.0719),
    'edmonton': ('Edmonton, AB',53.5461,-113.4938),
    'vancouver': ('Vancouver, BC',49.2827,-123.1207),
}
KM_PER_UNIT = 3.0
# Local spherical tangent approximation; suitable ONLY for illustrating same-day planning.
def to_xy(lat,lng):
    return ((lng-DEPOT['lng'])*111.32*cos(radians(DEPOT['lat']))/KM_PER_UNIT,
            (lat-DEPOT['lat'])*111.32/KM_PER_UNIT)
def to_latlng(x,y):
    return (round(DEPOT['lat']+y*KM_PER_UNIT/111.32,6),
            round(DEPOT['lng']+x*KM_PER_UNIT/(111.32*cos(radians(DEPOT['lat']))),6))
ZONES={key:{'label':name,'lat':lat,'lng':lng,'x':to_xy(lat,lng)[0],'y':to_xy(lat,lng)[1]}
       for key,(name,lat,lng) in CITY_PRESETS.items()}
LONG_HAUL={'ottawa','montreal','quebec_city','winnipeg','regina','saskatoon','calgary','edmonton','vancouver'}
# Legacy fictional-zone IDs are retained only for orders created before v0.7.
LEGACY_PRESETS={
 'west':('Legacy West Industrial Park (approx)',43.81,-79.39),
 'north':('Legacy North Hub (approx)',43.93,-79.31),
 'east':('Legacy East Warehouse (approx)',43.82,-79.08),
 'south':('Legacy South Terminal (approx)',43.70,-79.33),
 'outer':('Legacy Outer Hub (approx)',43.90,-79.02),
}
for _key,(_name,_lat,_lng) in LEGACY_PRESETS.items():
    ZONES[_key]={'label':_name,'lat':_lat,'lng':_lng,'x':to_xy(_lat,_lng)[0],'y':to_xy(_lat,_lng)[1]}
