from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
import math
import os
import requests

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

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
# Load all three datasets once at startup
with open("data/dense_drainage.geojson") as f:
    drainage_data = json.load(f)

with open("data/gully_inlets.geojson") as f:
    gully_data = json.load(f)

with open("data/manholes.geojson") as f:
    manhole_data = json.load(f)


def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def count_nearby_points(data, lat, lng, radius_m):
    count = 0
    for feature in data["features"]:
        plng, plat = feature["geometry"]["coordinates"]
        if haversine(lat, lng, plat, plng) <= radius_m:
            count += 1
    return count


def find_nearby_pipes(lat, lng, radius_m):
    nearby = []
    for feature in drainage_data["features"]:
        coords = feature["geometry"]["coordinates"]
        plng, plat = coords[0]
        if haversine(lat, lng, plat, plng) <= radius_m:
            nearby.append({
                "pipe_id": feature["properties"].get("pipe_id"),
                "diameter_mm": feature["properties"].get("diameter_mm"),
                "lat": plat,
                "lng": plng
            })
    return nearby


@app.get("/risk-zones")
def get_risk_zones(lat: float, lng: float):
    radius = 500

    nearby_pipes = find_nearby_pipes(lat, lng, radius)
    gully_count = count_nearby_points(gully_data, lat, lng, radius)
    manhole_count = count_nearby_points(manhole_data, lat, lng, radius)

    zones = []
    for pipe in nearby_pipes:
        if pipe["diameter_mm"] <= 300:
            risk = "high"
        elif pipe["diameter_mm"] <= 600:
            risk = "moderate"
        else:
            risk = "low"

        if gully_count < 3 and risk == "moderate":
            risk = "high"

        zones.append({
            "zone_id": pipe["pipe_id"],
            "risk_level": risk,
            "lat": pipe["lat"],
            "lng": pipe["lng"]
        })

    return {
        "zones": zones,
        "context": {
            "gully_inlets_nearby": gully_count,
            "manholes_nearby": manhole_count,
            "radius_m": radius
        }
    }


@app.get("/rainfall")
def get_rainfall(lat: float, lng: float):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()
    return data  # temporarily return everything raw, for debugging


@app.get("/debug-key")
def debug_key():
    return {"key_seen": OPENWEATHER_API_KEY}
