# HeatSentinal

AI-Powered Human Heat-Health Early Warning & Decision Intelligence System

Smart India Hackathon 2026
PS ID: 26083
Problem: Extreme Heatwave Early Warning and Human Thermal Stress Index

## Overview

HeatSentinal transforms extreme-heat weather information into
human-centric heat-health decision intelligence.

Instead of answering only:

"How hot will it be?"

HeatSentinal answers:

"What will this heat mean for vulnerable populations,
where is the risk highest, why is the risk increasing,
and what action should authorities take?"

## Core Workflow

PREDICT
  ↓
EXPLAIN
  ↓
FORECAST
  ↓
MAP
  ↓
SIMULATE
  ↓
OPTIMIZE
  ↓
ALERT
  ↓
VALIDATE

## System Architecture

Weather + Historical Climate
        +
Population / Vulnerability
        +
Health / Mortality Data
        ↓
Data Processing
        ↓
Thermal Stress Engine
HI + WBGT + UTCI
        ↓
Human Vulnerability Engine
        ↓
AI / ML Risk Prediction
        ↓
Explainable AI / SHAP
        ↓
Risk Forecast & Trajectory
        ↓
Hyperlocal GIS
        ↓
Heat Action Simulator
        ↓
AI Action Optimizer
        ↓
Early Warning & Alerts
        ↓
Health / Mortality Validation
        ↓
Decision Intelligence Dashboard

## Key Capabilities

- Human thermal stress assessment
- Heat Index, WBGT and UTCI
- Population vulnerability assessment
- AI/ML heat-risk prediction
- Explainable AI using SHAP
- Risk trajectory and forecasting
- Hyperlocal GIS risk zones
- Heat Action Simulator
- AI Action Optimizer
- Early warning and alerts
- Health/mortality validation
- Decision-intelligence dashboard

## Technology Stack

### Frontend
- React
- TypeScript
- Vite
- Tailwind CSS
- Recharts
- Mapbox / GIS

### Backend
- Python
- FastAPI
- Pandas
- NumPy
- Pydantic

### Machine Learning
- Scikit-learn
- XGBoost
- SHAP
- Joblib

### Geospatial
- GeoPandas
- Shapely
- GeoJSON

## Backend Status

All planned backend phases are implemented and integrated.

| Phase | Module | Status |
|---|---|---|
| 1 | FastAPI Foundation | Complete |
| 2 | Weather Service | Complete |
| 3 | Thermal Stress Engine | Complete |
| 4 | Human Vulnerability Engine | Complete |
| 5 | Health Risk Engine | Complete |
| 6 | Explainable AI / SHAP | Complete |
| 7 | Risk Forecast & Trajectory | Complete |
| 8 | Hyperlocal GIS | Complete |
| 9 | Heat Action Simulator | Complete |
| 10 | AI Action Optimizer | Complete |
| 11 | Early Warning & Alerts | Complete |
| 12 | Health / Mortality Validation | Complete |
| 13 | Decision Intelligence Integration | Complete |
| 14 | Testing & Validation | Complete |
| 15 | Deployment / Production Readiness | Complete |

## Scientific Integrity

HeatSentinal distinguishes between:

- Observed data
- ML predictions
- Vulnerability estimates
- Modelled intervention effects
- Validation data

The system does not present prototype scores as medical diagnosis
and does not claim causal deaths prevented or mortality reduction
from intervention simulation.

## Project Team

- Om Sreyansh Srivastava — Data Pipeline / AI Integration / Team Lead
- Swapnil Sahu — AI / ML Model
- Shivansh — Backend
- Arpita Sethi — Backend / Database
- Radhika Garg — Frontend
- Ansh Rai — Frontend Dashboard / API Integration
- Tapan — Heatwave Prediction / Project Team

## Running the Backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload