from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
import math

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

# Load all three datasets once at startup
with open("data/dense_drainage.geojson") as f:
    drainage_data = json.load(f)

with open("data/gully_inlets.geojson") as f:
    gully_data = json.load(f)

with open("data/manholes.geojson") as f:
    manhole_data = json.load(f)


def haversine(lat1, lng1, lat2, lng2):
    """Distance in meters between two lat/lng points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def count_nearby_points(data, lat, lng, radius_m):
    """Count how many Point features fall within radius_m of (lat, lng)."""
    count = 0
    for feature in data["features"]:
        plng, plat = feature["geometry"]["coordinates"]
        if haversine(lat, lng, plat, plng) <= radius_m:
            count += 1
    return count


def find_nearby_pipes(lat, lng, radius_m):
    """Return pipe segments with at least one endpoint within radius_m."""
    nearby = []
    for feature in drainage_data["features"]:
        coords = feature["geometry"]["coordinates"]
        # Check distance to the pipe's first coordinate (simple approximation)
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
    radius = 500  # meters

    nearby_pipes = find_nearby_pipes(lat, lng, radius)
    gully_count = count_nearby_points(gully_data, lat, lng, radius)
    manhole_count = count_nearby_points(manhole_data, lat, lng, radius)

    zones = []
    for pipe in nearby_pipes:
        # Base risk from pipe diameter
        if pipe["diameter_mm"] <= 300:
            risk = "high"
        elif pipe["diameter_mm"] <= 600:
            risk = "moderate"
        else:
            risk = "low"

        # Escalate risk if gully inlet coverage is sparse nearby
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
