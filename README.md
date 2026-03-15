# Sales Route Optimizer

## Installatie
```bash
pip install ortools fastapi uvicorn requests
```

## Draaien als API
```bash
uvicorn main:app --reload --port 8000
```

API documentatie: http://localhost:8000/docs

## Testen zonder API
```bash
python3 test.py
```

## Werkt zonder Google API key
Gebruikt Haversine schatting (vogelvlucht).
Voeg `"google_api_key": "AIza..."` toe voor echte rijtijden.

## Input structuur
```json
{
  "start_lat": 52.576,
  "start_lng": 4.833,
  "beschikbare_uren": 8.0,
  "am_kosten_per_uur": 80.0,
  "klanten": [
    {
      "id": "k01",
      "naam": "Restaurant X",
      "lat": 52.38,
      "lng": 4.90,
      "omzet": 45000,
      "prioriteit_score": 1.6,
      "bezoekduur_min": 45,
      "tijdvenster_open": 540,
      "tijdvenster_sluit": 660
    }
  ]
}
```

## Prioriteit score guide
| Situatie | Score |
|---|---|
| Contract verloopt | 1.8 - 2.0 |
| Offerte uitstaan | 1.4 - 1.6 |
| Normaal onderhoud | 1.0 |
| Net bezocht | 0.4 - 0.6 |
