from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json
import math
import os
import requests
import geopandas as gpd
from apscheduler.schedulers.background import BackgroundScheduler
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import messaging as fcm_messaging
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

# --- Load elevation-enriched datasets directly from GeoPackage ---
manholes_gdf = gpd.read_file("data/kmc_manholes_with_elevation.gpkg")
gully_gdf = gpd.read_file("data/gully_inlets.gpkg")
drainage_elevation_gdf = gpd.readfile("data/drainage_with_elevation.gpkg")

def haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def is_within_zone(device_lat, device_lng, zone_lat, zone_lng, radius_m=500):
    distance = haversine(device_lat, device_lng, zone_lat, zone_lng)
    return distance <= radius_m


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

def get_nearest_elevation(gdf, lat, lng, elevation_field="output_hh_1"):
    min_dist = float("inf")
    nearest_elev = None
    for _, row in gdf.iterrows():
        point_lng, point_lat = row.geometry.x, row.geometry.y
        dist = haversine(lat, lng, point_lat, point_lng)
        if dist < min_dist:
            min_dist = dist
            nearest_elev = row.get(elevation_field)
    return float(nearest_elev) if nearest_elev is not None else None

ELEVATION_MIN = 0
ELEVATION_MAX = 15

def elevation_risk_factor(elevation):
    if elevation is None:
        return 0
    normalized = (ELEVATION_MAX - elevation) / (ELEVATION_MAX - ELEVATION_MIN)
    return max(0, min(1, normalized))
    

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

        # --- Elevation factor ---
        elevation = get_nearest_elevation(manholes_gdf, pipe["lat"], pipe["lng"])
        elev_factor = elevation_risk_factor(elevation)

        if elev_factor > 0.7:
            if risk == "moderate":
                risk = "high"
            elif risk == "low":
                risk = "moderate"

        zones.append({
            "zone_id": pipe["pipe_id"],
            "risk_level": risk,
            "elevation_m": elevation,
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


def send_notification(token, zone):
    message = fcm_messaging.Message(
        notification=fcm_messaging.Notification(
            title="Flood Risk Alert",
            body=f"High flood risk ({zone['risk_level']}) detected near your location."
        ),
        token=token,
    )
    try:
        fcm_messaging.send(message)
        print(f"Notified device {token[:10]}...")
    except Exception as e:
        print(f"Failed to notify {token[:10]}...: {e}")


def check_and_notify():
    devices = db.collection("devices").stream()
    for device in devices:
        d = device.to_dict()
        send_notification(device.id, {"risk_level": "test"})


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
    check_and_notify()

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
