from datetime import datetime
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from .database import Base


class Route(Base):
    __tablename__ = "routes"
    id = Column(Integer, primary_key=True, index=True)
    route_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    distance_km = Column(Float, default=0)
    estimated_travel_min = Column(Integer, default=30)
    min_frequency = Column(Integer, default=2)
    max_frequency = Column(Integer, default=12)
    operating_cost = Column(Float, default=500)
    stops = relationship("Stop", back_populates="route")
    schedules = relationship("Schedule", back_populates="route")


class Stop(Base):
    __tablename__ = "stops"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    stop_code = Column(String, unique=True, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    route = relationship("Route", back_populates="stops")


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_code = Column(String, unique=True, nullable=False)
    capacity = Column(Integer, nullable=False)
    available = Column(Boolean, default=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    operating_cost = Column(Float, default=500)


class PassengerCount(Base):
    __tablename__ = "passenger_counts"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    route_id = Column(String, nullable=False, index=True)
    stop_id = Column(String, nullable=False)
    passenger_count = Column(Integer, nullable=False)
    hour = Column(Integer, nullable=False)
    weekday = Column(Integer, nullable=False)
    synthetic = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id"))
    vehicle_id = Column(Integer, nullable=True)
    departure_time = Column(String)
    trips = Column(Integer, default=0)
    route = relationship("Route", back_populates="schedules")


class ModelRun(Base):
    __tablename__ = "model_runs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    model_type = Column(String, nullable=False)
    mae = Column(Float)
    rmse = Column(Float)
    wape = Column(Float)
    peak_mae = Column(Float)
    synthetic = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Forecast(Base):
    __tablename__ = "forecasts"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    route_id = Column(String, nullable=False)
    predicted_demand = Column(Float, nullable=False)
    model_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OptimizationPlan(Base):
    __tablename__ = "optimization_plans"
    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, nullable=False)
    predicted_demand = Column(Float)
    required_trips = Column(Integer)
    recommended_vehicles = Column(Integer)
    utilization = Column(Float)
    unmet_demand = Column(Float)
    operating_cost = Column(Float)
    service_frequency = Column(Integer)
    feasible = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
