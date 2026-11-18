import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Route, Stop, Vehicle, PassengerCount


def seed_database(db: Session) -> None:
    if db.query(Route).count():
        return
    route_specs = [
        ("R01", "Central - Airport", 18.5, 46, 3, 14, 650),
        ("R02", "Railway - University", 12.2, 35, 3, 12, 520),
        ("R03", "Market - IT Park", 21.0, 52, 2, 10, 700),
        ("R04", "Hospital - Stadium", 15.4, 42, 2, 11, 580),
    ]
    route_ids = []
    for code, name, dist, travel, minimum, maximum, cost in route_specs:
        route = Route(route_code=code, name=name, distance_km=dist,
                      estimated_travel_min=travel, min_frequency=minimum,
                      max_frequency=maximum, operating_cost=cost)
        db.add(route)
        db.flush()
        route_ids.append(route.id)
        for index in range(5):
            db.add(Stop(
                name=f"{name} Stop {index + 1}",
                stop_code=f"{code}-S{index + 1}",
                latitude=20.0 + index * 0.01,
                longitude=78.5 + index * 0.01,
                route_id=route.id,
            ))

    for route_index, route_id in enumerate(route_ids):
        for index in range(5):
            db.add(Vehicle(
                vehicle_code=f"V{route_index + 1}{index + 1}",
                capacity=40 + (index % 3) * 10,
                available=True,
                route_id=route_id,
                operating_cost=500 + route_index * 30,
            ))

    random.seed(42)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    for day in range(30):
        for hour in range(24):
            for route_index, route_id in enumerate(route_ids):
                base = 45 + (24 - abs(hour - 8) if 6 <= hour <= 10 else 0)
                base += 18 if hour in (17, 18, 19) else 0
                base += route_index * 8
                for stop_index in range(5):
                    count = max(0, int(random.gauss(base * 0.18, 4)))
                    timestamp = now - timedelta(hours=(30 - day) * 24 - hour)
                    db.add(PassengerCount(
                        timestamp=timestamp,
                        route_id=f"R0{route_index + 1}",
                        stop_id=f"R0{route_index + 1}-S{stop_index + 1}",
                        passenger_count=count,
                        hour=timestamp.hour,
                        weekday=timestamp.weekday(),
                        synthetic=True,
                    ))
    db.commit()
