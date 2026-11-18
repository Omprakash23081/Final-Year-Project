from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy.orm import Session
from .models import Forecast, ModelRun, OptimizationPlan, PassengerCount, Route, Vehicle


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
    numeric = pd.to_numeric(df["passenger_count"], errors="coerce") if "passenger_count" in df else pd.Series(dtype=float)
    timestamps = pd.to_datetime(df["timestamp"], errors="coerce") if "timestamp" in df else pd.Series(dtype="datetime64[ns]")
    return {
        "valid": not missing_columns,
        "missing_columns": missing_columns,
        "missing_values": missing_values,
        "duplicate_rows": duplicate_count,
        "row_count": len(df),
        "invalid_timestamps": int(timestamps.isna().sum()),
        "invalid_passenger_counts": int(numeric.isna().sum()),
        "non_integer_passenger_counts": int((numeric.notna() & ((numeric % 1) != 0)).sum()),
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
    hourly["lag_24"] = hourly["lag_24"].fillna(hourly["lag_1"])
    hourly["rolling_24"] = hourly["rolling_24"].fillna(hourly["lag_1"])
    model_data = hourly.dropna(subset=["timestamp", "passenger_count", "lag_1"])
    if len(model_data) < 24:
        return {"error": "Not enough cleaned hourly records for model training."}

    features = ["hour", "weekday", "lag_1", "lag_24", "rolling_24"]
    unique_times = model_data["timestamp"].drop_duplicates().sort_values().tolist()
    if len(unique_times) < 2:
        return {"error": "At least two distinct hourly timestamps are required for chronological evaluation."}
    split_index = min(len(unique_times) - 1, max(1, int(len(unique_times) * 0.8)))
    split_time = unique_times[split_index]
    train = model_data[model_data["timestamp"] < split_time]
    test = model_data[model_data["timestamp"] >= split_time]
    if train.empty or test.empty:
        return {"error": "Not enough distinct timestamps for a chronological train/test split."}

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
        peak_mask = y_true >= np.percentile(y_true, 90)
        peak_mae = float(mean_absolute_error(y_true[peak_mask], y_pred[peak_mask]))
        return {"mae": round(mae, 2), "rmse": round(rmse, 2), "wape": round(wape, 2), "peak_mae": round(peak_mae, 2)}

    seasonal_metrics = metrics(actual, seasonal_actual)
    rf_metrics = metrics(actual, predicted)
    db.query(ModelRun).delete()
    all_synthetic = bool(frame["synthetic"].all())
    db.add_all([
        ModelRun(name="Seasonal Naive", model_type="Seasonal naive", synthetic=all_synthetic, **seasonal_metrics),
        ModelRun(name="Random Forest", model_type="Random Forest Regressor", synthetic=all_synthetic, **rf_metrics),
    ])

    # Generate route-specific 24-hour forecasts using the latest temporal features.
    forecasts = []
    db.query(Forecast).delete()
    last = hourly.groupby("route_id").tail(1)
    base_timestamp = hourly["timestamp"].max()
    for _, route_row in last.iterrows():
        history = hourly[hourly["route_id"] == route_row["route_id"]]["passenger_count"].astype(float).tolist()
        for hour_offset in range(24):
            timestamp = base_timestamp + timedelta(hours=hour_offset + 1)
            lag_1 = history[-1]
            lag_24 = history[-24] if len(history) >= 24 else float(np.mean(history))
            rolling_24 = float(np.mean(history[-24:]))
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
            history.append(demand)
            db.add(Forecast(timestamp=timestamp, route_id=route_row["route_id"],
                            predicted_demand=demand, model_name="Random Forest"))
    db.commit()

    comparison = [
        {"timestamp": str(t), "route_id": str(route_id),
         "actual": round(float(y), 2), "predicted": round(float(p), 2)}
        for t, route_id, y, p in zip(test["timestamp"], test["route_id"], actual, predicted)
    ]
    high_demand = sorted(forecasts, key=lambda x: x["predicted_demand"], reverse=True)[:10]
    return {
        "synthetic": all_synthetic,
        "peak_hours": [
            {"hour": int(hour), "average_demand": round(float(value), 2)}
            for hour, value in hourly.groupby("hour")["passenger_count"].mean().sort_values(ascending=False).head(5).items()
        ],
        "metrics": {"seasonal_naive": seasonal_metrics, "random_forest": rf_metrics},
        "comparison": comparison[-100:],
        "forecast": forecasts,
        "high_demand": high_demand,
    }


def optimize_routes(db: Session) -> dict:
    try:
        import pulp
    except ImportError as exc:
        raise RuntimeError("PuLP is required for route optimization. Install backend requirements.") from exc
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
    available_vehicles = db.query(Vehicle).filter(Vehicle.available.is_(True)).all()
    current_by_route = {}
    for vehicle in db.query(Vehicle).all():
        if vehicle.route_id:
            current_by_route[vehicle.route_id] = current_by_route.get(vehicle.route_id, 0) + 1

    route_inputs = []
    for code, values in route_forecasts.items():
        route = route_lookup.get(code)
        if route:
            route_inputs.append((code, route, float(max(values))))
    if not route_inputs:
        return {"feasible": False, "error": "No forecasted demand matches a registered route.", "plans": []}

    model = pulp.LpProblem("transit_fleet_allocation", pulp.LpMinimize)
    trip_vars = {}
    assignment_vars = {}
    unmet_vars = {}
    trips_per_vehicle = {}
    unmet_penalty = 10000.0
    max_capacity = max((vehicle.capacity for vehicle in available_vehicles), default=0)
    for code, route, demand in route_inputs:
        trip_vars[code] = pulp.LpVariable(
            f"trips_{route.id}", lowBound=route.min_frequency,
            upBound=route.max_frequency, cat="Integer",
        )
        unmet_vars[code] = pulp.LpVariable(f"unmet_{route.id}", lowBound=0)
        trips_per_vehicle[code] = max(1, int(60 / max(route.estimated_travel_min, 1)))
        assignment_vars[code] = {
            vehicle.id: pulp.LpVariable(f"route_{route.id}_vehicle_{vehicle.id}", cat="Binary")
            for vehicle in available_vehicles
        }
        vehicle_capacity = pulp.lpSum(
            assignment_vars[code][vehicle.id] * vehicle.capacity * trips_per_vehicle[code]
            for vehicle in available_vehicles
        )
        model += trip_vars[code] * max_capacity + unmet_vars[code] >= demand
        model += vehicle_capacity + unmet_vars[code] >= demand
        model += pulp.lpSum(assignment_vars[code].values()) <= trip_vars[code]

    for vehicle in available_vehicles:
        model += pulp.lpSum(
            assignment_vars[code][vehicle.id]
            for code, _, _ in route_inputs
        ) <= 1
    model += pulp.lpSum(
        unmet_vars[code] * unmet_penalty
        + trip_vars[code] * route.operating_cost
        + pulp.lpSum(assignment_vars[code].values()) * 0.01
        for code, route, _ in route_inputs
    )
    status = model.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return {
            "feasible": False,
            "error": f"Optimization solver did not find an optimal plan: {pulp.LpStatus[status]}",
            "plans": [],
        }

    plans = []
    total_unmet = 0.0
    fleet_used = 0
    db.query(OptimizationPlan).delete()
    for code, route, demand in route_inputs:
        required_trips = int(round(pulp.value(trip_vars[code])))
        assigned_vehicles = [
            vehicle for vehicle in available_vehicles
            if pulp.value(assignment_vars[code][vehicle.id]) > 0.5
        ]
        recommended = len(assigned_vehicles)
        capacity = min(
            required_trips * max_capacity,
            sum(v.capacity * trips_per_vehicle[code] for v in assigned_vehicles),
        )
        unmet = max(0.0, demand - capacity)
        utilization = demand / capacity * 100 if capacity > 0 else 0.0
        cost = required_trips * route.operating_cost
        feasible = unmet <= 1e-6 and recommended <= len(available_vehicles)
        plan = {
            "route_id": route.id,
            "route_code": code,
            "route_name": route.name,
            "predicted_demand": round(demand, 2),
            "current_allocated_vehicles": current_by_route.get(route.id, 0),
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
        "available_fleet": len(available_vehicles),
        "total_unmet_demand": round(total_unmet, 2),
        "engine": "PuLP integer linear program",
    }
