from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://flood-app-geoloc.vercel.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/risk-zones")
def get_risk_zones(lat: float, lng: float):
    # hardcoded fake data for now
    return {
        "zones": [
            {
                "zone_id": "zone1",
                "risk_level": "high",
                "lat": lat + 0.01,
                "lng": lng + 0.01
            },
            {
                "zone_id": "zone2",
                "risk_level": "moderate",
                "lat": lat - 0.01,
                "lng": lng - 0.01
            }
        ]
    }

@app.get("/debug-geojson")
def debug_geojson():
    with open("data/gully_inlets.geojson") as f:
        gully = json.load(f)
    with open("data/manholes.geojson") as f:
        manholes = json.load(f)
    return {
        "gully_sample": gully["features"][0],
        "manhole_sample": manholes["features"][0]
    }
