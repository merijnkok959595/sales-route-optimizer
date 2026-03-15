from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import requests
import math
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

app = FastAPI(title="Sales Route Optimizer")

# ── Models ────────────────────────────────────────────────────────────────────

class Klant(BaseModel):
    id: str
    naam: str
    lat: float
    lng: float
    omzet: float                        # jaaromzet in euros
    prioriteit_score: float             # 0.0 - 2.0 multiplier
    bezoekduur_min: int = 45            # minuten ter plaatse
    tijdvenster_open: Optional[int] = None   # minuten vanaf 00:00, bijv 9*60=540
    tijdvenster_sluit: Optional[int] = None  # bijv 17*60=1020

class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    eind_lat: Optional[float] = None    # None = zelfde als start (retour)
    eind_lng: Optional[float] = None
    beschikbare_uren: float             # bijv 8.0
    am_kosten_per_uur: float = 80.0     # euros per uur AM
    klanten: List[Klant]
    google_api_key: Optional[str] = None  # als None: gebruik Haversine schatting

class Stop(BaseModel):
    id: str
    naam: str
    volgorde: int
    aankomsttijd_min: int               # minuten vanaf start
    location_value: float               # euros netto waarde

class RouteResponse(BaseModel):
    stops: List[Stop]
    totale_waarde: float
    totale_reistijd_min: int
    totale_stops: int
    niet_bezocht: int

# ── Helpers ───────────────────────────────────────────────────────────────────

def haversine_minuten(lat1, lng1, lat2, lng2) -> int:
    """Schat reistijd in minuten op basis van vogelvluchtafstand (85 km/h gemiddeld)."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    km = R * 2 * math.asin(math.sqrt(a))
    return max(1, int(km / 85 * 60))

def bouw_reistijd_matrix(punten: list, api_key: str = None) -> list:
    """
    Bouw NxN matrix van reistijden in minuten.
    punten = lijst van (lat, lng) tuples
    Als api_key gegeven: gebruik Google Distance Matrix API
    Anders: gebruik Haversine schatting
    """
    n = len(punten)

    if api_key:
        # Google Distance Matrix API
        origins = "|".join(f"{lat},{lng}" for lat, lng in punten)
        destinations = origins
        url = (
            f"https://maps.googleapis.com/maps/api/distancematrix/json"
            f"?origins={origins}&destinations={destinations}"
            f"&mode=driving&key={api_key}"
        )
        resp = requests.get(url).json()
        matrix = []
        for row in resp["rows"]:
            matrix.append([
                el["duration"]["value"] // 60  # seconden → minuten
                for el in row["elements"]
            ])
        return matrix
    else:
        # Haversine fallback
        matrix = []
        for i, (lat1, lng1) in enumerate(punten):
            row = []
            for j, (lat2, lng2) in enumerate(punten):
                if i == j:
                    row.append(0)
                else:
                    row.append(haversine_minuten(lat1, lng1, lat2, lng2))
            matrix.append(row)
        return matrix

def bereken_location_value(klant: Klant, am_kosten_per_uur: float) -> float:
    """
    location_value = omzetpotentie - reiskosten
    Reiskosten worden later per route berekend.
    Hier berekenen we alleen de bruto potentie.
    """
    return klant.omzet * klant.prioriteit_score

# ── OR-Tools optimizer ────────────────────────────────────────────────────────

def optimaliseer_route(
    reistijd_matrix: list,
    location_values: list,
    bezoekduren: list,
    tijdvensters: list,
    tijdsbudget_min: int,
    am_kosten_per_minuut: float,
    n_klanten: int,
) -> dict:
    """
    Kern OR-Tools logica.
    Index 0 = depot (start/eind)
    Index 1..n = klanten
    """
    n = len(reistijd_matrix)

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    # ── Reistijd callback ──
    def reistijd_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return reistijd_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(reistijd_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # ── Tijd dimensie (inclusief bezoekduur) ──
    def tijd_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return reistijd_matrix[from_node][to_node] + bezoekduren[from_node]

    tijd_callback_index = routing.RegisterTransitCallback(tijd_callback)
    routing.AddDimension(
        tijd_callback_index,
        60,                 # max wachttijd per stop (minuten)
        tijdsbudget_min,    # max totale tijd
        False,
        "Tijd"
    )
    tijd_dimensie = routing.GetDimensionOrDie("Tijd")

    # ── Tijdvensters per klant ──
    # Depot krijgt volledige dag range
    depot_index = manager.NodeToIndex(0)
    tijd_dimensie.CumulVar(depot_index).SetRange(0, tijdsbudget_min)

    for i in range(1, n):
        open_min, sluit_min = tijdvensters[i]
        index = manager.NodeToIndex(i)
        if open_min is not None and sluit_min is not None:
            # Clamp binnen tijdsbudget
            open_clamped  = max(0, min(open_min, tijdsbudget_min))
            sluit_clamped = max(0, min(sluit_min, tijdsbudget_min))
            if open_clamped < sluit_clamped:
                tijd_dimensie.CumulVar(index).SetRange(open_clamped, sluit_clamped)
            else:
                tijd_dimensie.CumulVar(index).SetRange(0, tijdsbudget_min)
        else:
            tijd_dimensie.CumulVar(index).SetRange(0, tijdsbudget_min)

    # ── Penalty voor overslaan (location_value omzetten naar minuten-equivalent) ──
    # We drukken waarde uit in minuten: €1 = 1/am_kosten_per_minuut minuten
    for i in range(1, n):  # skip depot (index 0)
        index = manager.NodeToIndex(i)
        waarde_in_minuten = int(location_values[i] / max(am_kosten_per_minuut, 0.01))
        penalty = max(1, min(waarde_in_minuten, tijdsbudget_min * 10))
        routing.AddDisjunction([index], penalty)

    # ── Zoekstrategie ──
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = 10

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        return {"stops": [], "totale_reistijd": 0}

    # ── Extraheer route ──
    stops = []
    index = routing.Start(0)
    totale_reistijd = 0
    huidige_tijd = 0

    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:
            aankomst = solution.Value(tijd_dimensie.CumulVar(index))
            stops.append({
                "node": node,
                "aankomsttijd_min": aankomst,
            })
        next_index = solution.Value(routing.NextVar(index))
        totale_reistijd += reistijd_matrix[manager.IndexToNode(index)][manager.IndexToNode(next_index)]
        index = next_index

    return {
        "stops": stops,
        "totale_reistijd": totale_reistijd,
    }

# ── API Endpoint ──────────────────────────────────────────────────────────────

@app.post("/route", response_model=RouteResponse)
def bereken_route(req: RouteRequest):
    if not req.klanten:
        raise HTTPException(status_code=400, detail="Geen klanten meegegeven")

    tijdsbudget_min = int(req.beschikbare_uren * 60)
    am_kosten_per_min = req.am_kosten_per_uur / 60

    # Depot = startpunt (index 0)
    eind_lat = req.eind_lat or req.start_lat
    eind_lng = req.eind_lng or req.start_lng

    # Punten: [depot, klant1, klant2, ...]
    punten = [(req.start_lat, req.start_lng)] + [(k.lat, k.lng) for k in req.klanten]

    # Reistijd matrix ophalen
    matrix = bouw_reistijd_matrix(punten, req.google_api_key)

    # Location values (index 0 = depot = 0)
    location_values = [0.0] + [bereken_location_value(k, req.am_kosten_per_uur) for k in req.klanten]

    # Bezoekduren (depot = 0)
    bezoekduren = [0] + [k.bezoekduur_min for k in req.klanten]

    # Tijdvensters (depot = volledige dag)
    tijdvensters = [(0, tijdsbudget_min)] + [
        (k.tijdvenster_open, k.tijdvenster_sluit) for k in req.klanten
    ]

    # OR-Tools
    resultaat = optimaliseer_route(
        matrix,
        location_values,
        bezoekduren,
        tijdvensters,
        tijdsbudget_min,
        am_kosten_per_min,
        len(req.klanten),
    )

    # Bouw response
    stops_out = []
    bezochte_nodes = {s["node"] for s in resultaat["stops"]}

    for volgorde, stop in enumerate(resultaat["stops"], 1):
        node = stop["node"]
        klant = req.klanten[node - 1]
        reiskosten = matrix[0][node] * am_kosten_per_min  # schatting vanaf depot
        netto_value = bereken_location_value(klant, req.am_kosten_per_uur) - reiskosten

        stops_out.append(Stop(
            id=klant.id,
            naam=klant.naam,
            volgorde=volgorde,
            aankomsttijd_min=stop["aankomsttijd_min"],
            location_value=round(netto_value, 2),
        ))

    totale_waarde = sum(s.location_value for s in stops_out)
    niet_bezocht = len(req.klanten) - len(stops_out)

    return RouteResponse(
        stops=stops_out,
        totale_waarde=round(totale_waarde, 2),
        totale_reistijd_min=resultaat["totale_reistijd"],
        totale_stops=len(stops_out),
        niet_bezocht=niet_bezocht,
    )

@app.get("/health")
def health():
    return {"status": "ok"}
