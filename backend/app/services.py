import io
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy.orm import Session
from .models import PassengerCount, Route, Vehicle, Forecast, ModelRun


def get_passenger_frame(db: Session) -> pd.DataFrame:
    rows = db.query(PassengerCount).all()
    if not rows:
        return pd.DataFrame(columns=["timestamp", "route_id", "stop_id", "passenger_count", "hour", "weekday", "synthetic"])
    return pd.DataFrame([{
        "timestamp": r.timestamp,
        "route_id": r.route_id,
        "stop_id": r.stop_id,
        "passenger_count": r.passenger_count,
        "hour": r.hour,
        "weekday": r.weekday,
        "synthetic": r.synthetic,
    } for r in rows])


def validate_dataframe(df: pd.DataFrame) -> dict:
    required = {"timestamp", "route_id", "stop_id", "passenger_count"}
    missing_columns = sorted(required - set(df.columns))
    duplicate_count = int(df.duplicated().sum())
    missing_values = {k: int(v) for k, v in df.isna().sum().items() if v}
    numeric = pd.to_numeric(df.get("passenger_count"), errors="coerce")
    return {
        "valid": not missing_columns,
        "missing_columns": missing_columns,
        "missing_values": missing_values,
        "duplicate_rows": duplicate_count,
        "row_count": len(df),
        "negative_passenger_counts": int((numeric < 0).sum()),
    }


def train_and_forecast(db: Session) -> dict:
    frame = get_passenger_frame(db)
    if len(frame) < 48:
        return {"error": "Not enough passenger data. Generate synthetic data or upload at least 48 records."}
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["passenger_count"] = pd.to_numeric(frame["passenger_count"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "passenger_count"])
    hourly = frame.groupby(["timestamp", "route_id"], as_index=False)["passenger_count"].sum()
    hourly = hourly.sort_values("timestamp")

    hourly["hour"] = hourly["timestamp"].dt.hour
    hourly["weekday"] = hourly["timestamp"].dt.weekday
    hourly["lag_1"] = hourly.groupby("route_id")["passenger_count"].shift(1)
    hourly["lag_24"] = hourly.groupby("route_id")["passenger_count"].shift(24)
    hourly["rolling_24"] = hourly.groupby("route_id")["passenger_count"].transform(
        lambda s: s.shift(1).rolling(24, min_periods=1).mean()
    )
    model_data = hourly.dropna()
    if len(model_data) < 24:
        return {"error": "Not enough cleaned hourly records for model training."}

    features = ["hour", "weekday", "lag_1", "lag_24", "rolling_24"]
    split = max(1, int(len(model_data) * 0.8))
    train, test = model_data.iloc[:split], model_data.iloc[split:]
    if test.empty:
        test = model_data.iloc[-1:]
        train = model_data.iloc[:-1]

    # Seasonal naive predicts from the same hour one day earlier.
    seasonal_actual = test["lag_24"].fillna(test["lag_1"]).fillna(test["passenger_count"].mean())
    rf = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=1, n_jobs=-1)
    rf.fit(train[features], train["passenger_count"])
    predicted = rf.predict(test[features])
    actual = test["passenger_count"].to_numpy()

    def metrics(y_true, y_pred):
        mae = mean_absolute_error(y_true, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        wape = float(np.sum(np.abs(y_true - y_pred)) / max(np.sum(np.abs(y_true)), 1) * 100)
        peak_mae = float(mean_absolute_error(y_true[y_true >= np.percentile(y_true, 90)],
                                            y_pred[y_true >= np.percentile(y_true, 90)]))
        return {"mae": round(mae, 2), "rmse": round(rmse, 2), "wape": round(wape, 2), "peak_mae": round(peak_mae, 2)}

    seasonal_metrics = metrics(actual, seasonal_actual)
    rf_metrics = metrics(actual, predicted)
    db.query(ModelRun).delete()
    db.add_all([
        ModelRun(name="Seasonal Naive", model_type="Seasonal naive", synthetic=bool(frame["synthetic"].any()), **seasonal_metrics),
        ModelRun(name="Random Forest", model_type="Random Forest Regressor", synthetic=bool(frame["synthetic"].any()), **rf_metrics),
    ])

    # Generate route-specific 24-hour forecasts using the latest temporal features.
    forecasts = []
    db.query(Forecast).delete()
    last = hourly.groupby("route_id").tail(1)
    for _, route_row in last.iterrows():
        base_timestamp = hourly["timestamp"].max()
        for hour_offset in range(24):
            timestamp = base_timestamp + timedelta(hours=hour_offset + 1)
            lag_1 = float(route_row["passenger_count"])
            lag_24 = float(hourly[(hourly["route_id"] == route_row["route_id"])].tail(24)["passenger_count"].mean())
            rolling_24 = float(hourly[(hourly["route_id"] == route_row["route_id"])].tail(24)["passenger_count"].mean())
            feature = pd.DataFrame([{
                "hour": timestamp.hour,
                "weekday": timestamp.weekday(),
                "lag_1": lag_1,
                "lag_24": lag_24,
                "rolling_24": rolling_24,
            }])
            demand = max(0.0, float(rf.predict(feature)[0]))
            item = {"timestamp": timestamp.isoformat(), "route_id": route_row["route_id"], "predicted_demand": round(demand, 2)}
            forecasts.append(item)
            db.add(Forecast(timestamp=timestamp, route_id=route_row["route_id"],
                            predicted_demand=demand, model_name="Random Forest"))
    db.commit()

    comparison = [
        {"timestamp": r.timestamp.isoformat(), "route_id": r.route_id,
         "actual": 0.0, "predicted": round(r.predicted_demand, 2)}
        for r in test.assign(timestamp=test["timestamp"]).itertuples()
    ] if False else [
        {"timestamp": str(t), "actual": round(float(y), 2), "predicted": round(float(p), 2)}
        for t, y, p in zip(test["timestamp"].tail(len(predicted)), actual, predicted)
    ]
    high_demand = sorted(forecasts, key=lambda x: x["predicted_demand"], reverse=True)[:10]
    return {
        "synthetic": bool(frame["synthetic"].all()),
        "metrics": {"seasonal_naive": seasonal_metrics, "random_forest": rf_metrics},
        "comparison": comparison[-100:],
        "forecast": forecasts,
        "high_demand": high_demand,
    }


def optimize_routes(db: Session) -> dict:
    try:
        import pulp
    except Exception:
        pulp = None
    forecasts = db.query(Forecast).all()
    if not forecasts:
        trained = train_and_forecast(db)
        if "error" in trained:
            return {"feasible": False, "error": trained["error"], "plans": []}
        forecasts = db.query(Forecast).all()

    route_forecasts = {}
    for item in forecasts:
        route_forecasts.setdefault(item.route_id, []).append(item.predicted_demand)
    route_lookup = {r.route_code: r for r in db.query(Route).all()}
    vehicle_lookup = {}
    for vehicle in db.query(Vehicle).filter(Vehicle.available == True).all():
        if vehicle.route_id:
            route = db.query(Route).filter(Route.id == vehicle.route_id).first()
            if route:
                vehicle_lookup.setdefault(route.route_code, []).append(vehicle)

    plans = []
    total_unmet = 0.0
    fleet_used = 0
    db.query(OptimizationPlan).delete()
    for code, forecast_values in route_forecasts.items():
        route = route_lookup.get(code)
        if not route:
            continue
        demand = float(sum(forecast_values) / len(forecast_values))
        vehicles = vehicle_lookup.get(code, [])
        if pulp:
            # PuLP integer program: minimize vehicle/trip cost and unmet demand
            # while enforcing route frequency and available-fleet constraints.
            model = pulp.LpProblem(f"allocation_{code}", pulp.LpMinimize)
            trip_count = pulp.LpVariable("trips", lowBound=route.min_frequency,
                                         upBound=route.max_frequency, cat="Integer")
            vehicle_count = pulp.LpVariable("vehicles", lowBound=0,
                                            upBound=max(len(vehicles), 0), cat="Integer")
            unmet_variable = pulp.LpVariable("unmet_demand", lowBound=0)
            average_capacity = sum(v.capacity for v in vehicles) / max(len(vehicles), 1)
            capacity_total = trip_count * average_capacity
            model += unmet_variable + vehicle_count * route.operating_cost * 0.001
            model += unmet_variable >= demand - capacity_total
            model += vehicle_count * average_capacity >= demand - unmet_variable
            model += vehicle_count <= len(vehicles)
            model += trip_count <= route.max_frequency
            model += vehicle_count >= 1 if vehicles else vehicle_count == 0
            model.solve(pulp.PULP_CBC_CMD(msg=False))
            required_trips = int(round(pulp.value(trip_count)))
            recommended = int(round(pulp.value(vehicle_count)))
        else:
            available_capacity = sum(max(v.capacity, 1) for v in vehicles)
            required_trips = int(np.ceil(demand / max(available_capacity / max(len(vehicles), 1), 40)))
            required_trips = max(route.min_frequency, min(required_trips, route.max_frequency))
            recommended = min(len(vehicles), max(1, int(np.ceil(demand / 50))))
        capacity = sum(v.capacity for v in vehicles[:recommended]) if recommended else 0
        unmet = max(0.0, demand - capacity)
        utilization = min(100.0, demand / max(capacity, 1) * 100)
        cost = recommended * route.operating_cost
        feasible = unmet <= 1e-6 and recommended <= len(vehicles)
        plan = {
            "route_id": route.id,
            "route_code": code,
            "route_name": route.name,
            "predicted_demand": round(demand, 2),
            "required_trips": required_trips,
            "recommended_vehicles": recommended,
            "vehicle_utilization": round(utilization, 2),
            "unmet_demand": round(unmet, 2),
            "estimated_operating_cost": round(cost, 2),
            "service_frequency": required_trips,
            "feasible": feasible,
        }
        plans.append(plan)
        total_unmet += unmet
        fleet_used += recommended
        db.add(OptimizationPlan(
            route_id=route.id, predicted_demand=demand, required_trips=required_trips,
            recommended_vehicles=recommended, utilization=utilization, unmet_demand=unmet,
            operating_cost=cost, service_frequency=required_trips, feasible=feasible,
        ))
    db.commit()
    return {
        "feasible": all(p["feasible"] for p in plans),
        "plans": plans,
        "fleet_used": fleet_used,
        "total_unmet_demand": round(total_unmet, 2),
        "engine": "PuLP" if pulp else "Capacity-based fallback",
    }
