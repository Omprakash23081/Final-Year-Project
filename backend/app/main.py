from datetime import datetime
from io import BytesIO, StringIO
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .database import Base, engine, get_db
from .models import (
    Forecast, ModelRun, OptimizationPlan, PassengerCount, Route, Stop, Vehicle,
)
from .seed import seed_database
from .services import get_passenger_frame, optimize_routes, train_and_forecast, validate_dataframe

Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="AI-Based Public Transport Route Optimization API",
    version="1.0.0",
    description="Demand forecasting and constrained fleet allocation for public transport.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    db = next(get_db())
    try:
        seed_database(db)
    finally:
        db.close()


class RouteInput(BaseModel):
    route_code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1)
    distance_km: float = Field(ge=0)
    estimated_travel_min: int = Field(ge=1)
    min_frequency: int = Field(default=2, ge=1)
    max_frequency: int = Field(default=12, ge=1)
    operating_cost: float = Field(default=500, ge=0)


class StopInput(BaseModel):
    name: str
    stop_code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    route_id: Optional[int] = None


class VehicleInput(BaseModel):
    vehicle_code: str
    capacity: int = Field(ge=1)
    available: bool = True
    route_id: Optional[int] = None
    operating_cost: float = Field(default=500, ge=0)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "transport-optimization-api"}


@app.post("/api/data/generate-synthetic")
def generate_synthetic(db: Session = Depends(get_db)):
    existing = db.query(PassengerCount).count()
    if existing:
        return {"status": "existing", "row_count": existing, "synthetic": True}
    seed_database(db)
    return {"status": "generated", "row_count": db.query(PassengerCount).count(), "synthetic": True}


@app.post("/api/data/passenger/upload")
async def upload_passenger(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported.")
    try:
        df = pd.read_csv(file.file)
    except Exception as exc:
        raise HTTPException(400, f"Could not read CSV: {exc}") from exc
    validation = validate_dataframe(df)
    if not validation["valid"]:
        raise HTTPException(422, detail=f"Missing required columns: {', '.join(validation['missing_columns'])}")
    if validation["negative_passenger_counts"]:
        raise HTTPException(422, "Passenger counts cannot be negative.")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "route_id", "stop_id", "passenger_count"])
    inserted = 0
    for row in df.to_dict("records"):
        timestamp = pd.Timestamp(row["timestamp"]).to_pydatetime()
        db.add(PassengerCount(
            timestamp=timestamp,
            route_id=str(row["route_id"]),
            stop_id=str(row["stop_id"]),
            passenger_count=int(row["passenger_count"]),
            hour=int(timestamp.hour),
            weekday=int(timestamp.weekday()),
            synthetic=False,
        ))
        inserted += 1
    db.commit()
    validation["inserted_rows"] = inserted
    return validation


@app.get("/api/data/statistics")
def data_statistics(db: Session = Depends(get_db)):
    df = get_passenger_frame(db)
    if df.empty:
        return {"row_count": 0, "route_count": 0, "stop_count": 0, "synthetic": True}
    return {
        "row_count": len(df),
        "route_count": int(df["route_id"].nunique()),
        "stop_count": int(df["stop_id"].nunique()),
        "mean_passenger_count": round(float(df["passenger_count"].mean()), 2),
        "minimum_passenger_count": int(df["passenger_count"].min()),
        "maximum_passenger_count": int(df["passenger_count"].max()),
        "synthetic_rows": int(df["synthetic"].sum()),
        "observed_rows": int((~df["synthetic"]).sum()),
        "missing_values": {k: int(v) for k, v in df.isna().sum().items() if v},
        "duplicate_rows": int(df.duplicated().sum()),
    }


@app.get("/api/data/passenger")
def passenger_preview(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(PassengerCount).order_by(PassengerCount.timestamp.desc()).limit(limit).all()
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "route_id": r.route_id,
            "stop_id": r.stop_id,
            "passenger_count": r.passenger_count,
            "synthetic": r.synthetic,
        }
        for r in rows
    ]


@app.post("/api/forecast/train")
def train_forecast(db: Session = Depends(get_db)):
    result = train_and_forecast(db)
    if "error" in result:
        raise HTTPException(422, result["error"])
    return result


@app.get("/api/forecast/evaluation")
def forecast_evaluation(db: Session = Depends(get_db)):
    runs = db.query(ModelRun).all()
    if not runs:
        return {"trained": False, "models": []}
    return {
        "trained": True,
        "models": [
            {
                "name": r.name,
                "mae": r.mae,
                "rmse": r.rmse,
                "wape": r.wape,
                "peak_mae": r.peak_mae,
                "synthetic": r.synthetic,
            }
            for r in runs
        ],
    }


@app.get("/api/forecast")
def list_forecasts(db: Session = Depends(get_db)):
    rows = db.query(Forecast).order_by(Forecast.timestamp).all()
    return [
        {"timestamp": r.timestamp.isoformat(), "route_id": r.route_id,
         "predicted_demand": r.predicted_demand, "model_name": r.model_name}
        for r in rows
    ]


@app.post("/api/routes")
def create_route(payload: RouteInput, db: Session = Depends(get_db)):
    if db.query(Route).filter(Route.route_code == payload.route_code).first():
        raise HTTPException(409, "Route code already exists.")
    route = Route(**payload.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    return {"id": route.id, **payload.model_dump()}


@app.get("/api/routes")
def list_routes(db: Session = Depends(get_db)):
    return [
        {
            "id": r.id, "route_code": r.route_code, "name": r.name,
            "distance_km": r.distance_km, "estimated_travel_min": r.estimated_travel_min,
            "min_frequency": r.min_frequency, "max_frequency": r.max_frequency,
            "operating_cost": r.operating_cost,
        }
        for r in db.query(Route).all()
    ]


@app.put("/api/routes/{route_id}")
def update_route(route_id: int, payload: RouteInput, db: Session = Depends(get_db)):
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise HTTPException(404, "Route not found.")
    for key, value in payload.model_dump().items():
        setattr(route, key, value)
    db.commit()
    return {"id": route.id, **payload.model_dump()}


@app.delete("/api/routes/{route_id}")
def delete_route(route_id: int, db: Session = Depends(get_db)):
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise HTTPException(404, "Route not found.")
    db.delete(route)
    db.commit()
    return {"deleted": route_id}


@app.post("/api/stops")
def create_stop(payload: StopInput, db: Session = Depends(get_db)):
    if db.query(Stop).filter(Stop.stop_code == payload.stop_code).first():
        raise HTTPException(409, "Stop code already exists.")
    stop = Stop(**payload.model_dump())
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return {"id": stop.id, **payload.model_dump()}


@app.get("/api/stops")
def list_stops(db: Session = Depends(get_db)):
    return [
        {"id": s.id, "name": s.name, "stop_code": s.stop_code,
         "latitude": s.latitude, "longitude": s.longitude, "route_id": s.route_id}
        for s in db.query(Stop).all()
    ]


@app.post("/api/vehicles")
def create_vehicle(payload: VehicleInput, db: Session = Depends(get_db)):
    if db.query(Vehicle).filter(Vehicle.vehicle_code == payload.vehicle_code).first():
        raise HTTPException(409, "Vehicle code already exists.")
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return {"id": vehicle.id, **payload.model_dump()}


@app.put("/api/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, payload: VehicleInput, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(404, "Vehicle not found.")
    for key, value in payload.model_dump().items():
        setattr(vehicle, key, value)
    db.commit()
    return {"id": vehicle.id, **payload.model_dump()}


@app.get("/api/vehicles")
def list_vehicles(db: Session = Depends(get_db)):
    return [
        {"id": v.id, "vehicle_code": v.vehicle_code, "capacity": v.capacity,
         "available": v.available, "route_id": v.route_id, "operating_cost": v.operating_cost}
        for v in db.query(Vehicle).all()
    ]


@app.post("/api/optimization/run")
def run_optimization(db: Session = Depends(get_db)):
    result = optimize_routes(db)
    if "error" in result:
        raise HTTPException(422, result["error"])
    return result


@app.get("/api/optimization")
def list_optimization(db: Session = Depends(get_db)):
    plans = db.query(OptimizationPlan).all()
    routes = {r.id: r for r in db.query(Route).all()}
    if not plans:
        result = optimize_routes(db)
        if "plans" not in result:
            return result
        return result
    return {
        "feasible": all(p.feasible for p in plans),
        "plans": [
            {
                "route_id": p.route_id,
                "route_code": routes[p.route_id].route_code if p.route_id in routes else str(p.route_id),
                "route_name": routes[p.route_id].name if p.route_id in routes else "Unknown",
                "predicted_demand": p.predicted_demand,
                "required_trips": p.required_trips,
                "recommended_vehicles": p.recommended_vehicles,
                "vehicle_utilization": p.utilization,
                "unmet_demand": p.unmet_demand,
                "estimated_operating_cost": p.operating_cost,
                "service_frequency": p.service_frequency,
                "feasible": p.feasible,
            }
            for p in plans
        ],
        "fleet_used": sum(p.recommended_vehicles for p in plans),
        "total_unmet_demand": round(sum(p.unmet_demand for p in plans), 2),
        "engine": "PuLP",
    }


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    df = get_passenger_frame(db)
    routes = db.query(Route).all()
    stops = db.query(Stop).count()
    vehicles = db.query(Vehicle).all()
    forecast_rows = db.query(Forecast).all()
    plans = db.query(OptimizationPlan).all()
    average = round(float(df["passenger_count"].mean()), 2) if not df.empty else 0.0
    predicted = round(float(sum(r.predicted_demand for r in forecast_rows) / len(forecast_rows)), 2) if forecast_rows else 0.0
    utilization = round(float(sum(p.utilization for p in plans) / len(plans)), 2) if plans else 0.0

    hourly = {}
    route_distribution = {}
    if not df.empty:
        hourly = df.groupby("hour")["passenger_count"].sum().sort_index().astype(float).to_dict()
        route_distribution = df.groupby("route_id")["passenger_count"].sum().astype(float).to_dict()

    return {
        "total_routes": len(routes),
        "total_stops": stops,
        "total_vehicles": len(vehicles),
        "available_vehicles": sum(1 for v in vehicles if v.available),
        "average_demand": average,
        "predicted_demand": predicted,
        "vehicle_utilization": utilization,
        "high_demand_routes": [
            {"route_id": k, "demand": round(float(v), 2)}
            for k, v in sorted(route_distribution.items(), key=lambda item: item[1], reverse=True)[:5]
        ],
        "routes_requiring_vehicles": [
            {"route_id": p.route_id, "shortfall": round(p.unmet_demand, 2)}
            for p in plans if p.unmet_demand > 0
        ],
        "hourly_demand": [{"hour": str(int(k)).zfill(2), "demand": round(float(v), 2)} for k, v in hourly.items()],
        "route_distribution": [{"route_id": k, "demand": round(float(v), 2)} for k, v in route_distribution.items()],
    }


@app.get("/api/reports/{report_type}/csv")
def report_csv(report_type: str, db: Session = Depends(get_db)):
    if report_type == "passenger":
        df = get_passenger_frame(db)
    elif report_type == "forecast":
        df = pd.DataFrame([
            {"timestamp": r.timestamp, "route_id": r.route_id, "predicted_demand": r.predicted_demand, "model_name": r.model_name}
            for r in db.query(Forecast).all()
        ])
    elif report_type == "optimization":
        df = pd.DataFrame([
            {"route_id": p.route_id, "predicted_demand": p.predicted_demand,
             "required_trips": p.required_trips, "recommended_vehicles": p.recommended_vehicles,
             "utilization": p.utilization, "unmet_demand": p.unmet_demand,
             "operating_cost": p.operating_cost, "feasible": p.feasible}
            for p in db.query(OptimizationPlan).all()
        ])
    elif report_type == "fleet":
        df = pd.DataFrame([
            {"vehicle_code": v.vehicle_code, "capacity": v.capacity,
             "available": v.available, "route_id": v.route_id}
            for v in db.query(Vehicle).all()
        ])
    else:
        raise HTTPException(404, "Unknown report type.")
    if df.empty:
        df = pd.DataFrame([{"status": "No data available"}])
    output = StringIO()
    df.to_csv(output, index=False)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_type}-report.csv"},
    )


@app.get("/api/reports/{report_type}/pdf")
def report_pdf(report_type: str, db: Session = Depends(get_db)):
    if report_type == "passenger":
        rows = db.query(PassengerCount).order_by(PassengerCount.timestamp.desc()).limit(200).all()
        headers = ["Timestamp", "Route", "Stop", "Passengers", "Source"]
        data = [[r.timestamp.strftime("%Y-%m-%d %H:%M"), r.route_id, r.stop_id,
                 str(r.passenger_count), "Synthetic" if r.synthetic else "Observed"] for r in rows]
    elif report_type == "forecast":
        rows = db.query(Forecast).order_by(Forecast.timestamp).all()
        headers = ["Timestamp", "Route", "Predicted demand", "Model"]
        data = [[r.timestamp.strftime("%Y-%m-%d %H:%M"), r.route_id,
                 str(round(r.predicted_demand, 2)), r.model_name] for r in rows]
    elif report_type == "optimization":
        rows = db.query(OptimizationPlan).all()
        headers = ["Route", "Trips", "Vehicles", "Unmet", "Cost", "Feasible"]
        data = [[str(r.route_id), str(r.required_trips), str(r.recommended_vehicles),
                 str(round(r.unmet_demand, 2)), str(round(r.operating_cost, 2)),
                 "Yes" if r.feasible else "No"] for r in rows]
    elif report_type == "fleet":
        rows = db.query(Vehicle).all()
        headers = ["Vehicle", "Capacity", "Available", "Route"]
        data = [[r.vehicle_code, str(r.capacity), "Yes" if r.available else "No",
                 str(r.route_id or "")] for r in rows]
    else:
        raise HTTPException(404, "Unknown report type.")

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"TransitAI - {report_type.title()} Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph("Generated from backend database records.", styles["BodyText"]),
        Spacer(1, 12),
    ]
    table_data = [headers] + (data or [["No data available"]])
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
    ]))
    elements.append(table)
    document.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={report_type}-report.pdf"},
    )
