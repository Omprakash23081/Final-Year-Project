# AI-Based Public Transport Route Optimization System

## Overview
This application combines passenger-demand forecasting, Random Forest and Seasonal Naive comparison, PuLP-based fleet allocation, route/fleet management, and operational reporting. Synthetic records are generated automatically and are clearly labeled in the UI and database.

## Project structure
```text
backend/
  app/
    database.py
    main.py
    models.py
    seed.py
    services.py
  requirements.txt
  run.py
frontend/
  src/
    App.jsx
    api.js
    main.jsx
    styles.css
  package.json
  vite.config.js
```

## Windows setup
Requirements: Python 3.10+ and Node.js 18+.

From the project root:

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

Open a second terminal:

```bat
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Swagger documentation is available at `http://127.0.0.1:8000/docs`.

Alternatively, from the project root in PowerShell, run `.\start-backend.bat` and `.\start-frontend.bat` in separate terminals.

## Main workflows
1. The backend seeds SQLite with routes, stops, vehicles, and a synthetic 30-day passenger dataset.
2. Upload a CSV under Data Management or append a synthetic week from the generator.
3. Train models under Demand Forecasting.
4. Run route optimization under Route Optimization.
5. Manage vehicles and routes.
6. Review updated dashboard and allocation results; download CSV or PDF reports under Reports.

## API notes
- Passenger CSV requires `timestamp`, `route_id`, `stop_id`, and `passenger_count`.
- `POST /api/data/generate-synthetic` appends one synthetic passenger-data week.
- `POST /api/forecast/train` performs chronological train/test splitting and generates 24-hour forecasts.
- `POST /api/optimization/run` executes a PuLP integer program with individual vehicle assignment and a shared fleet constraint. Capacity shortfalls are reported by route.
- Vehicle CRUD endpoints are `GET/POST /api/vehicles` and `PUT/DELETE /api/vehicles/{id}`. Routes and stops have corresponding CRUD endpoints.
- SQLite is stored in `backend/data/transport.db`.

## Limitations
- The optimizer uses peak forecasted route-hour demand and hourly seat capacity based on route travel duration; it is not a full timetable solver.
- The sample route graph is a route-node view rather than a geographic map.
- Forecasting quality is only demonstrated on the currently loaded data; synthetic-data metrics must not be interpreted as real-world accuracy.
