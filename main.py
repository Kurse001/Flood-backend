from fastapi import FastAPI

app = FastAPI()

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