from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
import math
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import firebase_admin
from firebase_admin import credentials, firestore
import json as json_lib

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

# --- Firebase setup ---
cred_dict = json_lib.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Load GeoJSON datasets once at startup ---
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
    return {
        "rain_1h_mm": data.get("rain", {}).get("1h", 0),
        "weather": data.get("weather", [{}])[0].get("description", "unknown")
    }


# --- Scheduled rainfall polling ---
latest_rainfall = {"rain_1h_mm": 0, "weather": "unknown"}

def poll_rainfall():
    global latest_rainfall
    lat, lng = 22.5406, 88.339
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()
    latest_rainfall = {
        "rain_1h_mm": data.get("rain", {}).get("1h", 0),
        "weather": data.get("weather", [{}])[0].get("description", "unknown")
    }
    print("Rainfall updated:", latest_rainfall)

scheduler = BackgroundScheduler()
scheduler.add_job(poll_rainfall, 'interval', minutes=15)
scheduler.start()

poll_rainfall()

@app.get("/latest-rainfall")
def get_latest_rainfall():
    return latest_rainfall


# --- Firestore test route ---
@app.get("/test-firestore")
def test_firestore():
    doc_ref = db.collection("test").document("hello")
    doc_ref.set({"message": "Firestore is connected!"})
    return {"status": "success"}
from pydantic import BaseModel
from datetime import datetime


class DeviceRegistration(BaseModel):
    token: str
    lat: float
    lng: float


@app.post("/register-device")
async def register_device(payload: DeviceRegistration):
    db.collection("devices").document(payload.token).set({
        "lat": payload.lat,
        "lng": payload.lng,
        "updated_at": datetime.utcnow()
    })
    return {"status": "registered"}
