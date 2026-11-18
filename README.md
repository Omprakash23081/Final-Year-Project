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

Alternatively, use `start-backend.bat` and `start-frontend.bat` from the project root.

## Main workflows
1. The backend seeds SQLite and a synthetic 30-day passenger dataset.
2. Upload a CSV under Data Management or use the generated data.
3. Train models under Demand Forecasting.
4. Run route optimization under Route Optimization.
5. Manage vehicles and routes.
6. Download CSV reports under Reports.

## API notes
- Passenger CSV requires `timestamp`, `route_id`, `stop_id`, and `passenger_count`.
- `POST /api/forecast/train` performs chronological train/test splitting and generates 24-hour forecasts.
- `POST /api/optimization/run` returns only feasible allocation plans or explicit capacity shortfalls.
- SQLite is stored in `backend/data/transport.db`.

## Limitations
- PuLP integer allocation is simplified to one operating frequency and average vehicle capacity per route.
- The sample route graph is a route-node view rather than a geographic map.
- PDF export is represented in the report module as CSV; PDF can be added through ReportLab without changing the API architecture.
