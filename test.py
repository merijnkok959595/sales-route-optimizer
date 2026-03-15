"""
Test het route optimizer systeem met dummy Noord-Holland data.
Geen Google API key nodig - gebruikt Haversine schatting.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    bouw_reistijd_matrix,
    bereken_location_value,
    optimaliseer_route,
    Klant,
)

# ── Dummy klanten Noord-Holland ───────────────────────────────────────────────
klanten = [
    Klant(id="k01", naam="Restaurant De Vliet - Alkmaar",      lat=52.632, lng=4.747, omzet=45000, prioriteit_score=1.6, bezoekduur_min=45, tijdvenster_open=9*60,  tijdvenster_sluit=11*60),
    Klant(id="k02", naam="Café t Centrum - Hoorn",              lat=52.643, lng=5.060, omzet=28000, prioriteit_score=1.2, bezoekduur_min=30, tijdvenster_open=10*60, tijdvenster_sluit=17*60),
    Klant(id="k03", naam="Hotel Haarlem Noord",                 lat=52.387, lng=4.646, omzet=92000, prioriteit_score=1.8, bezoekduur_min=60, tijdvenster_open=9*60,  tijdvenster_sluit=16*60),
    Klant(id="k04", naam="Bistro Purmerend",                    lat=52.502, lng=4.960, omzet=35000, prioriteit_score=0.8, bezoekduur_min=30, tijdvenster_open=None,  tijdvenster_sluit=None),
    Klant(id="k05", naam="Grand Café Zaandam",                  lat=52.439, lng=4.813, omzet=67000, prioriteit_score=1.4, bezoekduur_min=45, tijdvenster_open=14*60, tijdvenster_sluit=17*60),
    Klant(id="k06", naam="Lunchroom Den Helder",                lat=52.959, lng=4.762, omzet=21000, prioriteit_score=0.6, bezoekduur_min=30, tijdvenster_open=None,  tijdvenster_sluit=None),
    Klant(id="k07", naam="Restaurant Enkhuizen Haven",          lat=52.703, lng=5.295, omzet=54000, prioriteit_score=1.5, bezoekduur_min=45, tijdvenster_open=11*60, tijdvenster_sluit=14*60),
    Klant(id="k08", naam="Café Broek in Waterland",             lat=52.435, lng=4.995, omzet=18000, prioriteit_score=1.9, bezoekduur_min=30, tijdvenster_open=9*60,  tijdvenster_sluit=12*60),
    Klant(id="k09", naam="Hotel Egmond aan Zee",                lat=52.616, lng=4.629, omzet=78000, prioriteit_score=1.3, bezoekduur_min=60, tijdvenster_open=None,  tijdvenster_sluit=None),
    Klant(id="k10", naam="Snackbar Schagen",                    lat=52.788, lng=4.800, omzet=12000, prioriteit_score=0.5, bezoekduur_min=20, tijdvenster_open=None,  tijdvenster_sluit=None),
]

# ── Setup ─────────────────────────────────────────────────────────────────────
START = (52.576, 4.833)   # Heerhugowaard
AM_KOSTEN_PER_UUR = 80.0
AM_KOSTEN_PER_MIN = AM_KOSTEN_PER_UUR / 60
BESCHIKBARE_UREN  = 8.0
TIJDSBUDGET_MIN   = int(BESCHIKBARE_UREN * 60)

print("=" * 60)
print("  SALES ROUTE OPTIMIZER — Noord-Holland")
print("=" * 60)
print(f"  Start/eind: Heerhugowaard")
print(f"  Tijdsbudget: {BESCHIKBARE_UREN} uur ({TIJDSBUDGET_MIN} min)")
print(f"  AM kosten:   €{AM_KOSTEN_PER_UUR}/uur")
print(f"  Klanten:     {len(klanten)}")
print()

# Toon alle klanten met hun potentie
print("KLANTEN — gesorteerd op bruto potentie:")
print("-" * 60)
gesorteerd = sorted(klanten, key=lambda k: k.omzet * k.prioriteit_score, reverse=True)
for k in gesorteerd:
    potentie = k.omzet * k.prioriteit_score
    tw = f"{k.tijdvenster_open//60:02d}:00-{k.tijdvenster_sluit//60:02d}:00" if k.tijdvenster_open else "hele dag"
    print(f"  {k.naam:<40} potentie: €{potentie:>8,.0f}  [{tw}]")

print()
print("Reistijden berekenen (Haversine)...")

# Punten: depot + klanten
punten = [START] + [(k.lat, k.lng) for k in klanten]
matrix = bouw_reistijd_matrix(punten)

location_values = [0.0] + [bereken_location_value(k, AM_KOSTEN_PER_UUR) for k in klanten]
bezoekduren     = [0]   + [k.bezoekduur_min for k in klanten]
tijdvensters    = [(0, TIJDSBUDGET_MIN)] + [
    (k.tijdvenster_open, k.tijdvenster_sluit) for k in klanten
]

print("OR-Tools optimalisatie uitvoeren...")
resultaat = optimaliseer_route(
    matrix, location_values, bezoekduren, tijdvensters,
    TIJDSBUDGET_MIN, AM_KOSTEN_PER_MIN, len(klanten)
)

# ── Output ────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("  OPTIMALE ROUTE")
print("=" * 60)

totale_waarde = 0
bezochte_ids  = set()

for volgorde, stop in enumerate(resultaat["stops"], 1):
    node  = stop["node"]
    klant = klanten[node - 1]
    aankomst_uur = stop["aankomsttijd_min"] // 60
    aankomst_min = stop["aankomsttijd_min"] % 60
    reiskosten   = matrix[0][node] * AM_KOSTEN_PER_MIN
    netto        = bereken_location_value(klant, AM_KOSTEN_PER_UUR) - reiskosten
    totale_waarde += netto
    bezochte_ids.add(klant.id)

    print(f"  Stop {volgorde}: {klant.naam}")
    print(f"         Aankomst:  {aankomst_uur:02d}:{aankomst_min:02d}")
    print(f"         Potentie:  €{klant.omzet * klant.prioriteit_score:,.0f}")
    print(f"         Netto:     €{netto:,.0f}")
    print()

niet_bezocht = [k for k in klanten if k.id not in bezochte_ids]

print("-" * 60)
print(f"  Bezochte stops:    {len(resultaat['stops'])}")
print(f"  Totale reistijd:   {resultaat['totale_reistijd']} min ({resultaat['totale_reistijd']//60}u {resultaat['totale_reistijd']%60}min)")
print(f"  Totale routewaarde: €{totale_waarde:,.0f}")
print()

if niet_bezocht:
    print("OVERGESLAGEN (te laag rendement of tijdconflict):")
    for k in niet_bezocht:
        print(f"  ✗ {k.naam} (potentie €{k.omzet * k.prioriteit_score:,.0f})")

print("=" * 60)
