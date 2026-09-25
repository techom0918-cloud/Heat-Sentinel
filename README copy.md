# 🔥 Heat-Sentinel

> **AI-powered heat-risk forecasting and heat intelligence platform for India**

Heat-Sentinel combines weather data, derived heat-stress indicators, machine-learning forecasting, a FastAPI backend, and a React/Vite frontend into one local development platform.

This document is the **complete from-scratch setup guide**. It is intended to replace the old `README.md`.

---

## Table of Contents

1. [What is Heat-Sentinel?](#1-what-is-heat-sentinel)
2. [System Architecture](#2-system-architecture)
3. [Project Structure](#3-project-structure)
4. [Prerequisites](#4-prerequisites)
5. [Clone / Extract the Project](#5-clone--extract-the-project)
6. [Python Environment](#6-python-environment)
7. [Backend Setup](#7-backend-setup)
8. [Frontend Setup](#8-frontend-setup)
9. [Environment Variables](#9-environment-variables)
10. [Dataset and ML Pipeline](#10-dataset-and-ml-pipeline)
11. [Training the Heat Model](#11-training-the-heat-model)
12. [Model Artifact Location](#12-model-artifact-location)
13. [Running Heat-Sentinel](#13-running-heat-sentinel)
14. [Verifying the Backend](#14-verifying-the-backend)
15. [Verifying the Frontend](#15-verifying-the-frontend)
16. [Development Workflow](#16-development-workflow)
17. [Windows PowerShell Commands](#17-windows-powershell-commands)
18. [Important Dependency Versions](#18-important-dependency-versions)
19. [Known Issues and Fixes](#19-known-issues-and-fixes)
20. [LightGBM Windows Compatibility](#20-lightgbm-windows-compatibility)
21. [Model Evaluation](#21-model-evaluation)
22. [Data and ML Concepts](#22-data-and-ml-concepts)
23. [API Overview](#23-api-overview)
24. [Frontend Configuration](#24-frontend-configuration)
25. [Production Notes](#25-production-notes)
26. [Security](#26-security)
27. [Testing](#27-testing)
28. [Troubleshooting Checklist](#28-troubleshooting-checklist)
29. [Clean Reinstall](#29-clean-reinstall)
30. [Git and Repository Hygiene](#30-git-and-repository-hygiene)
31. [Future Feature Roadmap](#31-future-feature-roadmap)
32. [Recommended UI/UX Direction](#32-recommended-uiux-direction)
33. [Final Quick Start](#33-final-quick-start)

---

# 1. What is Heat-Sentinel?

Heat-Sentinel is a heat-risk intelligence system designed to estimate future heat-risk categories from weather and derived environmental indicators.

The current ML workflow:

```text
Historical weather data
        ↓
Feature engineering
        ↓
Heat-stress indicators
        ↓
Time-aware train/validation/test split
        ↓
Multiple ML models
        ↓
Model selection
        ↓
Random Forest model
        ↓
heat_model.joblib
        ↓
FastAPI forecast service
        ↓
React/Vite dashboard
```

The current forecasting target is the **heat-risk category approximately 3 days ahead**.

Current categories are:

- `LOW`
- `MODERATE`
- `HIGH`
- `VERY_HIGH`
- `EXTREME`

The currently available training data contains no `EXTREME` samples in the labelled train/validation/test splits, so the `EXTREME` class should not be interpreted as successfully learned merely because it exists as a category.

---

# 2. System Architecture

Heat-Sentinel has three major runtime components.

```text
┌──────────────────────────────┐
│       React + Vite UI        │
│          :5173               │
└──────────────┬───────────────┘
               │ HTTP
               ▼
┌──────────────────────────────┐
│       FastAPI Backend        │
│          :8000               │
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
 ML model artifact    Data/services
 ml/heat_model.joblib
```

### Frontend

The frontend is responsible for:

- Dashboard UI
- Forecast display
- City information
- Charts
- API requests
- Loading/error/empty states
- Responsive presentation

Typical development URL:

```text
http://127.0.0.1:5173
```

### Backend

The backend is a FastAPI application.

Typical development URL:

```text
http://127.0.0.1:8000
```

FastAPI documentation is normally available at:

```text
http://127.0.0.1:8000/docs
```

### ML

The ML pipeline:

```text
ml/heat_pipeline.py
```

trains and evaluates the model and saves the trained artifact.

The ML pipeline does **not** need a separate server.

---

# 3. Project Structure

The current repository contains the following major areas:

```text
Heat-Sentinel/
│
├── .git/
├── .venv/
│
├── backend/
│   ├── app/
│   ├── data/
│   ├── models/
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── .env.example
│
├── ml/
│   ├── heat_pipeline.py
│   ├── train_heat_model.py
│   └── ...
│
├── data/
├── outputs/
├── docs/
│
├── .env
├── .env.example
├── .gitignore
├── README.md
│
└── legacy / phase-1 scripts
```

### Important

The repository also contains older Phase-1 data-processing scripts in the root.

Do **not** randomly delete or move them without checking their imports and references.

They can eventually be reorganized into:

```text
scripts/
docs/
data/
tests/
```

but repository cleanup is a separate task from getting the application running.

---

# 4. Prerequisites

Recommended Windows environment:

| Component | Recommended |
|---|---|
| OS | Windows 10/11 64-bit |
| Python | **3.13.x** |
| Node.js | Current Node LTS compatible with frontend |
| npm | Comes with Node.js |
| Git | Latest stable |
| Browser | Chrome / Edge / Firefox |
| RAM | 8 GB minimum, 16 GB+ recommended |
| Disk | Several GB free |

## Why Python 3.13?

Python 3.14 caused dependency/build compatibility problems in this project, particularly around scientific Python packages.

Use Python 3.13 for the current setup.

Check:

```powershell
python --version
py --version
```

Expected:

```text
Python 3.13.x
```

If multiple Python versions exist:

```powershell
py -0p
```

---

# 5. Clone / Extract the Project

If using Git:

```powershell
git clone <YOUR_REPOSITORY_URL> Heat-Sentinel
cd Heat-Sentinel
```

If the project was downloaded as a ZIP:

1. Extract the ZIP.
2. Put the project somewhere convenient.
3. Open PowerShell in the project directory.

Example:

```powershell
cd D:\Heat-Sentinel
```

Verify:

```powershell
Get-ChildItem
```

You should see folders such as:

```text
backend
frontend
ml
data
docs
outputs
```

---

# 6. Python Environment

## 6.1 Create the virtual environment

From the project root:

```powershell
py -3.13 -m venv .venv
```

## 6.2 Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can temporarily allow scripts for the current user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then:

```powershell
.\.venv\Scripts\Activate.ps1
```

You should see something similar to:

```text
(.venv) PS D:\Heat-Sentinel>
```

## 6.3 Upgrade pip

```powershell
python -m pip install --upgrade pip
```

Verify:

```powershell
python --version
pip --version
```

---

# 7. Backend Setup

Move into the backend:

```powershell
cd backend
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Return to root:

```powershell
cd ..
```

Verify FastAPI:

```powershell
python -m uvicorn --version
```

Expected environment currently uses Uvicorn with Python 3.13.

Verify core packages:

```powershell
python -c "import fastapi, pandas, pydantic; print('Dependencies OK')"
```

Expected:

```text
Dependencies OK
```

---

# 8. Frontend Setup

Open a **new PowerShell terminal**.

Go to the frontend:

```powershell
cd D:\Heat-Sentinel\frontend
```

Install Node dependencies:

```powershell
npm install
```

If this project is configured for pnpm, use the package-manager version declared by the repository instead:

```powershell
pnpm install
```

Do not mix package managers unnecessarily.

Start the frontend:

```powershell
npm run dev
```

or, if pnpm is configured:

```powershell
pnpm dev
```

Typical Vite address:

```text
http://127.0.0.1:5173
```

---

# 9. Environment Variables

There may be environment files at:

```text
.env
.env.example
backend/.env.example
frontend/.env.example
```

Never commit secrets.

A typical frontend API configuration may look like:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

Use the exact variable names expected by the existing frontend code.

Do not invent additional environment variables unless the application actually reads them.

## `.env.example`

Use `.env.example` as the safe template.

Never put:

- API keys
- database passwords
- private tokens
- cloud credentials
- production secrets

into Git.

---

# 10. Dataset and ML Pipeline

The project contains historical heat/weather data.

The current major raw dataset is:

```text
heat_raw_hourly.csv
```

It contains approximately:

```text
578,592 hourly rows
6 cities
2015-01-01 through 2025-12-31
```

The ML pipeline transforms this data into labelled examples.

The target represents a future heat-risk category approximately **3 days ahead**.

---

# 11. Training the Heat Model

From the project root:

```powershell
cd D:\Heat-Sentinel
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run:

```powershell
python ml\heat_pipeline.py
```

The pipeline:

1. Loads the raw heat dataset.
2. Creates features.
3. Creates future risk targets.
4. Performs time-aware train/validation/test splitting.
5. Evaluates baseline models.
6. Trains multiple ML models.
7. Selects the validation model.
8. Evaluates on held-out test data.
9. Saves the trained model.
10. Produces future forecasts.

---

# 12. Model Artifact Location

The trained model must be saved here:

```text
ml/heat_model.joblib
```

The pipeline now resolves the location relative to the script:

```python
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "heat_model.joblib"
```

The model is therefore independent of the directory from which the script is launched.

The save operation should use:

```python
joblib.dump(model, MODEL_PATH)
```

This prevents the old problem where running:

```powershell
python ml\heat_pipeline.py
```

could accidentally create:

```text
Heat-Sentinel/
└── heat_model.joblib
```

instead of:

```text
Heat-Sentinel/
└── ml/
    └── heat_model.joblib
```

## Verify the model

```powershell
Test-Path .\ml\heat_model.joblib
```

Expected:

```text
True
```

Check its size:

```powershell
Get-Item .\ml\heat_model.joblib | Select-Object Name,Length,LastWriteTime
```

---

# 13. Running Heat-Sentinel

Heat-Sentinel should normally run with **two terminals**.

## Terminal 1 — Backend

```powershell
cd D:\Heat-Sentinel
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

If the repository's backend package exposes a different module path, use the existing project command/configuration.

Backend:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Terminal 2 — Frontend

```powershell
cd D:\Heat-Sentinel\frontend
npm run dev
```

Frontend:

```text
http://127.0.0.1:5173
```

---

# 14. Verifying the Backend

Open:

```text
http://127.0.0.1:8000/docs
```

If Swagger/OpenAPI loads, the FastAPI server is running.

You can also test the root endpoint if the project defines one:

```powershell
Invoke-WebRequest http://127.0.0.1:8000
```

For API-specific tests, use the routes displayed by:

```text
/docs
```

---

# 15. Verifying the Frontend

Open:

```text
http://127.0.0.1:5173
```

Check:

- Page loads.
- No Vite compilation errors.
- Network requests reach port `8000`.
- Forecast data appears.
- Browser console has no critical errors.

If the UI loads but forecast data is missing, check the backend first.

---

# 16. Development Workflow

Recommended order whenever you start development:

```text
1. Open project
        ↓
2. Activate .venv
        ↓
3. Start backend
        ↓
4. Start frontend
        ↓
5. Open dashboard
        ↓
6. Check browser console
        ↓
7. Check backend terminal
        ↓
8. Make changes
        ↓
9. Test
        ↓
10. Commit
```

## When changing ML code

Use:

```powershell
python ml\heat_pipeline.py
```

Then verify:

```powershell
Test-Path .\ml\heat_model.joblib
```

Restart the backend after replacing the model if the backend loads the artifact during startup.

---

# 17. Windows PowerShell Commands

## Go to project

```powershell
cd D:\Heat-Sentinel
```

## Activate environment

```powershell
.\.venv\Scripts\Activate.ps1
```

## Deactivate

```powershell
deactivate
```

## Python version

```powershell
python --version
```

## Installed packages

```powershell
python -m pip list
```

## Backend dependencies

```powershell
python -m pip install -r backend\requirements.txt
```

## Run ML

```powershell
python ml\heat_pipeline.py
```

## Check model

```powershell
Test-Path .\ml\heat_model.joblib
```

## Start backend

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

## Start frontend

```powershell
cd frontend
npm run dev
```

---

# 18. Important Dependency Versions

## Python

Use:

```text
Python 3.13.x
```

## LightGBM

The project should pin:

```text
lightgbm==4.6.0
```

Do **not** casually change this to:

```text
lightgbm>=4.5,<5
```

The reason is Windows compatibility.

The project was tested with LightGBM 4.6.0 successfully.

---

# 19. Known Issues and Fixes

## Issue: Python 3.14 causes package installation/build failures

### Symptom

Pandas or another scientific package attempts to build from source and installation fails.

### Fix

Use Python 3.13:

```powershell
py -3.13 -m venv .venv
```

Then reinstall dependencies.

---

## Issue: `No trained model artifact is present`

### Cause

The backend cannot find:

```text
ml/heat_model.joblib
```

### Fix

Run:

```powershell
python ml\heat_pipeline.py
```

Then:

```powershell
Test-Path .\ml\heat_model.joblib
```

It must return:

```text
True
```

Restart the backend.

---

## Issue: Frontend cannot connect to backend

Check that backend is running:

```text
http://127.0.0.1:8000/docs
```

Then verify frontend API configuration.

The development API base is expected to be similar to:

```text
http://127.0.0.1:8000/api/v1
```

---

## Issue: Port 8000 is already in use

Find the process:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

Then either stop the conflicting process or run the backend on another port and update the frontend API URL.

---

## Issue: Port 5173 is already in use

Vite may automatically choose another port.

Read the terminal output and open the URL it provides.

---

# 20. LightGBM Windows Compatibility

A significant compatibility issue was encountered with LightGBM 4.7.x on the Windows environment used for this project.

The failure appeared as:

```text
OSError: exception: access violation reading 0x0000000000000000
```

The crash occurred during LightGBM dataset/label handling.

Diagnostics showed:

- LightGBM could import.
- Classifier creation worked.
- A synthetic random-data LightGBM fit worked.
- Actual Heat-Sentinel data triggered the crash.
- Converting features to NumPy did not resolve it.
- `n_jobs=1` did not resolve it.
- Replacing labels did not resolve it.
- Numeric values were finite and valid.
- LightGBM 4.6.0 successfully processed the actual Heat-Sentinel data.

Therefore the working project configuration is:

```text
lightgbm==4.6.0
```

If this problem returns after reinstalling dependencies:

```powershell
python -m pip uninstall -y lightgbm
python -m pip install lightgbm==4.6.0
```

Verify:

```powershell
python -c "import lightgbm; print(lightgbm.__version__)"
```

Expected:

```text
4.6.0
```

---

# 21. Model Evaluation

The successful ML run produced the following held-out test results.

### Persistence baseline

```text
Macro F1 : 0.710
Accuracy : 0.742
POD      : 0.916
FAR      : 0.084
CSI      : 0.845
```

### Selected Random Forest

```text
Macro F1 : 0.723
Accuracy : 0.766
POD      : 0.947
FAR      : 0.090
CSI      : 0.866
```

Per-class test performance:

| Risk class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| LOW | 0.76 | 0.67 | 0.71 | 609 |
| MODERATE | 0.72 | 0.69 | 0.71 | 1172 |
| HIGH | 0.80 | 0.88 | 0.84 | 2082 |
| VERY_HIGH | 0.73 | 0.56 | 0.63 | 505 |
| EXTREME | — | — | — | 0 |

Overall:

```text
Accuracy ≈ 0.77
Weighted F1 ≈ 0.76
```

These metrics are a snapshot of the current dataset/model run. They should be regenerated whenever data, feature engineering, model configuration, or splitting logic changes.

---

# 22. Data and ML Concepts

The pipeline currently uses engineered heat-related features such as:

- Maximum heat index
- Mean heat index
- Rolling heat-index averages
- Rolling maxima
- Lagged heat-index values
- Temperature statistics
- WBGT
- UTCI
- Hot-streak indicators
- Categorical risk information
- Other weather-derived variables

Examples of high-importance features from the current run included:

```text
heat_index_max_rmean_7
heat_index_max_rmax_3
heat_index_max
heat_index_max_rmean_3
heat_index_max_rmean_14
heat_index_max_rmax_7
heat_index_mean
temperature_mean
wbgt_max
utci_max_rmean_7
hot_streak
```

Feature importance indicates model usage/correlation within the fitted model; it should not automatically be interpreted as causal influence.

---

# 23. API Overview

The backend is built with FastAPI.

The exact available endpoints should always be checked through:

```text
http://127.0.0.1:8000/docs
```

The frontend currently uses an API base similar to:

```text
http://127.0.0.1:8000/api/v1
```

A healthy development architecture is:

```text
Browser
  ↓
React/Vite
  ↓
REST API
  ↓
FastAPI
  ↓
Forecast service
  ↓
heat_model.joblib
```

---

# 24. Frontend Configuration

The frontend should not hardcode production infrastructure into source code.

Prefer environment-based configuration.

Example:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

Production can then use a different API URL without changing application source code.

After changing Vite environment variables, restart the frontend dev server.

---

# 25. Production Notes

The development setup is:

```text
Frontend: Vite dev server
Backend: Uvicorn --reload
ML: local joblib artifact
```

This is not automatically a production deployment.

A production architecture should consider:

```text
CDN / Reverse Proxy
        ↓
Frontend
        ↓
HTTPS API
        ↓
FastAPI workers
        ↓
Model service / model artifact
        ↓
Database / object storage
```

Production requirements may include:

- HTTPS
- CORS restriction
- authentication
- rate limiting
- structured logging
- monitoring
- health checks
- model versioning
- data validation
- secret management
- automated deployments
- backup strategy

---

# 26. Security

## Never commit secrets

Check:

```powershell
git status
```

Make sure `.env` is ignored.

## Never expose

Do not commit:

```text
API keys
Passwords
Private tokens
Cloud credentials
Database credentials
JWT secrets
```

## CORS

Development can allow localhost.

Production should restrict allowed origins to trusted domains.

## Input validation

Backend endpoints should validate:

- city
- date/time
- numeric values
- ranges
- request size
- unknown fields where appropriate

---

# 27. Testing

Before considering a major change complete, test:

## Backend

```powershell
cd D:\Heat-Sentinel
.\.venv\Scripts\Activate.ps1
```

Then run the project's test suite, for example:

```powershell
pytest
```

If tests are scoped to backend:

```powershell
pytest backend\tests
```

Use the test command actually defined by the repository.

## ML

Run:

```powershell
python ml\heat_pipeline.py
```

Verify that:

```text
training completes
validation completes
test evaluation completes
model saves
forecast generation completes
```

## Frontend

```powershell
cd frontend
npm run build
```

A successful production build is a useful sanity check even during development.

---

# 28. Troubleshooting Checklist

When something fails, check in this order.

## 1. Correct directory

```powershell
Get-Location
```

Expected:

```text
D:\Heat-Sentinel
```

## 2. Correct Python

```powershell
python --version
```

Expected:

```text
Python 3.13.x
```

## 3. Virtual environment

```powershell
Get-Command python
```

It should point to:

```text
D:\Heat-Sentinel\.venv\Scripts\python.exe
```

## 4. Dependencies

```powershell
python -c "import fastapi, pandas, pydantic, lightgbm; print('Dependencies OK')"
```

## 5. LightGBM version

```powershell
python -c "import lightgbm; print(lightgbm.__version__)"
```

Expected:

```text
4.6.0
```

## 6. Model artifact

```powershell
Test-Path .\ml\heat_model.joblib
```

Expected:

```text
True
```

## 7. Backend

Open:

```text
http://127.0.0.1:8000/docs
```

## 8. Frontend

Open:

```text
http://127.0.0.1:5173
```

## 9. Browser console

Press:

```text
F12
```

Check:

```text
Console
Network
```

## 10. Backend terminal

Look for Python/FastAPI tracebacks.

---

# 29. Clean Reinstall

If the environment becomes corrupted, recreate it.

From project root:

```powershell
deactivate
```

Remove:

```powershell
Remove-Item -Recurse -Force .\.venv
```

Create again:

```powershell
py -3.13 -m venv .venv
```

Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install backend requirements:

```powershell
python -m pip install -r backend\requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm install
cd ..
```

Verify:

```powershell
python -c "import fastapi, pandas, pydantic, lightgbm; print('Dependencies OK')"
```

Verify LightGBM:

```powershell
python -c "import lightgbm; print(lightgbm.__version__)"
```

Then regenerate the model:

```powershell
python ml\heat_pipeline.py
```

---

# 30. Git and Repository Hygiene

The repository should eventually keep the root clean.

Recommended root:

```text
Heat-Sentinel/
├── backend/
├── frontend/
├── ml/
├── data/
├── outputs/
├── docs/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── README.md
└── LICENSE
```

Large generated files should generally not be committed blindly.

Potential generated artifacts include:

```text
heat_raw_hourly.csv
*.joblib
*.csv
generated reports
generated charts
temporary files
```

Whether a specific artifact belongs in Git depends on the project's reproducibility strategy.

For large datasets/models, consider Git LFS or object storage.

---

# 31. Future Feature Roadmap

Heat-Sentinel can be expanded into a complete heat-intelligence platform.

## Phase A — Intelligence Dashboard

Add:

- Current heat risk
- 3-day forecast
- 7-day trend
- City selector
- Risk timeline
- Weather indicators
- Heat-stress metrics
- Forecast confidence
- Model metadata

## Phase B — India Heat-Risk Map

Interactive map showing:

```text
LOW
MODERATE
HIGH
VERY HIGH
EXTREME
```

Potential technologies:

- Leaflet
- MapLibre
- Mapbox
- GeoJSON
- vector tiles

## Phase C — Explainable AI

For each forecast show:

```text
Why is the risk high?
```

Example:

```text
Heat-index trend        ↑
Maximum temperature     ↑
Humidity                ↑
Recent hot streak       ↑
UTCI                    ↑
```

Use model explainability carefully.

Do not present model feature contribution as medical or physical causation.

## Phase D — What-If Simulator

Allow a user to modify:

```text
Temperature
Humidity
Wind
Solar/radiation-related variables
```

and calculate a hypothetical model output.

Clearly label this as a simulation rather than an observed forecast.

## Phase E — Historical Analytics

Add:

- Monthly heat trends
- Seasonal patterns
- City comparison
- Historical extremes
- Heat-wave duration
- Year-over-year analysis
- Anomaly detection

## Phase F — Heat-Wave Detection

Detect sustained periods satisfying project-defined heat-risk thresholds.

Display:

```text
Start
Peak
Duration
Affected cities
Severity
End
```

## Phase G — Alert System

Potential channels:

- Browser notification
- Email
- Telegram
- WhatsApp
- SMS

Only notify when defined thresholds are met.

## Phase H — AI Heat Analyst

Build a natural-language interface over actual project data.

Example:

```text
Which cities have the highest predicted heat risk
over the next three days?
```

The AI layer should query real structured data rather than inventing values.

## Phase I — Production Platform

Add:

- Authentication
- User roles
- Saved cities
- Alert preferences
- Audit logs
- Monitoring
- Model versioning
- Scheduled retraining
- Data pipeline automation

---

# 32. Recommended UI/UX Direction

The dashboard should look like a serious climate-tech product rather than a generic admin panel.

## Visual direction

Use:

- Dark or dark-first interface
- Clean typography
- Heat-inspired accent gradients
- Strong data hierarchy
- Minimal glass effects
- Subtle animations
- High-quality charts
- Responsive layout
- Accessible contrast

Avoid:

- excessive glassmorphism
- excessive gradients
- huge decorative elements
- unnecessary animations
- cluttered cards
- dashboard widgets with no useful information

## Suggested dashboard

```text
┌─────────────────────────────────────────────────────────────┐
│ Heat-Sentinel                     Search   Alerts   Profile │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  India Heat Risk                                            │
│  ┌──────────────────────────────┐  ┌─────────────────────┐ │
│  │                              │  │ Today's Risk        │ │
│  │        INDIA MAP             │  │ HIGH                │ │
│  │                              │  │                     │ │
│  │     city risk visualization  │  │ 3-Day Forecast      │ │
│  │                              │  │ ↑ HIGH              │ │
│  └──────────────────────────────┘  └─────────────────────┘ │
│                                                             │
│  Risk Timeline                                              │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  Temperature   Humidity   Heat Index   WBGT   UTCI          │
│                                                             │
│  City comparison                                            │
│  Delhi | Kochi | Bengaluru | Ahmedabad | Kolkata | Nagpur  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Required UI states

Every important component should have:

### Loading

```text
Loading forecast...
```

### Empty

```text
No forecast data available.
```

### Error

```text
Unable to load forecast.
Retry
```

### Success

Display the actual data.

This prevents blank screens and confusing failures.

---

# 33. Final Quick Start

For a machine that has never run Heat-Sentinel before:

## Step 1

Install:

```text
Python 3.13
Node.js LTS
Git
```

## Step 2

Open project:

```powershell
cd D:\Heat-Sentinel
```

## Step 3

Create Python environment:

```powershell
py -3.13 -m venv .venv
```

## Step 4

Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Step 5

Install backend dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

## Step 6

Verify:

```powershell
python -c "import fastapi, pandas, pydantic, lightgbm; print('Dependencies OK')"
```

## Step 7

Verify LightGBM:

```powershell
python -c "import lightgbm; print(lightgbm.__version__)"
```

Expected:

```text
4.6.0
```

## Step 8

Train the model:

```powershell
python ml\heat_pipeline.py
```

## Step 9

Verify model:

```powershell
Test-Path .\ml\heat_model.joblib
```

Expected:

```text
True
```

## Step 10

Start backend:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

## Step 11

Open:

```text
http://127.0.0.1:8000/docs
```

## Step 12

Open another terminal:

```powershell
cd D:\Heat-Sentinel\frontend
npm install
npm run dev
```

## Step 13

Open:

```text
http://127.0.0.1:5173
```

---

# 🚀 One-Page Startup Cheat Sheet

```powershell
# Terminal 1
cd D:\Heat-Sentinel
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2
cd D:\Heat-Sentinel\frontend
npm run dev
```

Open:

```text
Frontend
http://127.0.0.1:5173

Backend
http://127.0.0.1:8000

API Docs
http://127.0.0.1:8000/docs
```

If the model is missing:

```powershell
cd D:\Heat-Sentinel
.\.venv\Scripts\Activate.ps1
python ml\heat_pipeline.py
```

Then restart the backend.

---

# 🧠 Important Project Rules

1. Use **Python 3.13** for the current environment.
2. Keep **LightGBM pinned to 4.6.0**.
3. The trained model belongs at:
   ```text
   ml/heat_model.joblib
   ```
4. Do not commit `.env`.
5. Do not expose secrets in frontend code.
6. Do not treat feature importance as causal proof.
7. Do not claim the `EXTREME` class is well trained when the current labelled dataset has zero `EXTREME` test samples.
8. Re-run the ML pipeline whenever training data or feature engineering changes.
9. Restart the backend after replacing a model artifact if it loads the model during startup.
10. Keep generated data and legacy scripts organized as the repository evolves.
11. Do not blindly move/delete Phase-1 scripts until their imports and references are checked.
12. Prefer reproducible, documented commands over machine-specific paths.

---

# 📌 Project Status

Current validated development environment:

```text
OS             Windows
Python         3.13.15
Uvicorn        0.34.0
LightGBM       4.6.0
ML model       Random Forest
Model artifact ml/heat_model.joblib
Backend        FastAPI
Frontend       React + Vite
```

The current ML pipeline has been successfully executed on the Heat-Sentinel dataset, producing a trained model and future city forecasts.

---

## License

Add the project's actual license here once the repository's licensing decision has been finalized.

---

## Maintainer Notes

This README is intended to be the single high-level setup and operation reference for Heat-Sentinel.

When the architecture changes, update this document together with:

- dependency versions
- environment variables
- model artifact location
- startup commands
- API routes
- frontend configuration
- ML training procedure
- deployment procedure
