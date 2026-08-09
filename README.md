# 🔥 HOTWORX Churn Control Center

**Predictive Member Retention & Intervention Dashboard**

An end-to-end machine learning system that predicts member churn for fitness studios, explains *why* each member is at risk, and automatically routes personalized interventions — all wrapped in a premium dark-themed control center.

> Production-architected prototype built on synthetic data. Every component is designed so real HOTWORX data sources can be swapped in without rewriting business logic. All performance metrics are benchmarked on synthetic data — see [Model Performance](#-model-performance) for context.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **Churn Prediction** | XGBoost classifier with **AUC 0.96** and **74% precision** at the top-10% risk tier |
| **Explainable Risk Scores** | Each at-risk member gets human-readable reasons: billing failures, session drop-off, AI coach inquiries |
| **Automated Interventions** | Rules engine maps risk tiers → emails, SMS, push notifications, or staff call tasks |
| **A/B Testing Built-In** | Deterministic 10% holdout group with lift measurement charts |
| **Row-Level Security** | GMs only see their own studio's members; admins see everything |
| **Identity Encryption** | PII encrypted at rest with AES-256 (Fernet); decrypted in-memory only |
| **Kill Switch & Rate Limits** | Global hourly send cap (50/hr) and per-member 7-day cooldown prevent spam |

---

## 📸 Dashboard Views

### Studio Overview
Risk distribution across all studios, weekly churn forecast, and MRR at risk.

### Member Detail
Individual member diagnostic profiles with risk gauges, behavioral trend lines, and intervention history.

### Intervention Queue & A/B Results
Sortable action queue for staff, plus treatment vs. control churn rate comparison.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                               │
│  generate_synthetic_data.py → 7 tables, 5K members, 10 studios │
│  data_adapters.py → toggle: local parquet ↔ production SQL      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                   Feature Engineering                           │
│  models/staging/stg_*.sql → models/marts/fct_member_features    │
│  run_pipeline.py → DuckDB execution → 29 rolling daily features │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                     ML Scoring Layer                             │
│  train_evaluate.ipynb → XGBoost + isotonic calibration          │
│  score_members.py → daily risk scores + text explanations       │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│              Intervention Router + Dashboard                    │
│  interventions.py → rules engine, A/B holdout, rate limits      │
│  dashboard.py → Streamlit control center (dark theme, RLS)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- pip

### Local Setup

```bash
# Clone the repository
git clone https://github.com/NightsTTV/hotworx-churn-demo.git
cd hotworx-churn-demo

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Launch the dashboard
streamlit run dashboard.py
```

The app ships with pre-built synthetic data in `data/`, so it works immediately.

### Default Login Credentials

| Username | Role | Access |
|---|---|---|
| `admin` | Admin | All studios |
| `gm_s01` – `gm_s10` | GM | One studio each |

Default demo passwords are intentionally weak — they are **never stored in plaintext** (hashed with PBKDF2-HMAC-SHA256 + per-user random salt at runtime). Set strong passwords for any real deployment via the `DASHBOARD_ADMIN_PW` and `DASHBOARD_GM_PW` environment variables.

---

## 🔄 Regenerate Data from Scratch

If you want to regenerate the synthetic dataset:

```bash
# Step 1: Generate 5,000 synthetic members across 10 studios
python generate_synthetic_data.py

# Step 2: Build daily feature engineering pipeline (DuckDB)
python run_pipeline.py

# Step 3: Score active members with the trained model
python score_members.py

# Step 4: Route interventions through the rules engine
python interventions.py

# Step 5: Launch the dashboard
streamlit run dashboard.py
```

---

## 📁 Project Structure

```
hotworx-churn-demo/
├── dashboard.py                 # Streamlit control center (main entry point)
├── auth.py                      # PBKDF2 password hashing & user account loader
├── generate_synthetic_data.py   # Synthetic member/event data generator
├── run_pipeline.py              # DuckDB feature engineering orchestrator
├── score_members.py             # ML scoring engine with risk explanations
├── interventions.py             # Rules engine, adapters, A/B holdout, rate limits
├── secure_data.py               # AES-256 Fernet encryption for PII at rest
├── identity_resolver.py         # Multi-source fuzzy identity matching engine
├── data_adapters.py             # Unified data connector (parquet ↔ SQL toggle)
├── query_demo.py                # CLI tool for querying member feature profiles
├── requirements.txt             # Python dependencies
│
├── models/                      # SQL feature engineering models
│   ├── staging/                 # stg_*.sql — raw table normalization
│   ├── intermediate/            # int_member_identity.sql — cross-system join keys
│   └── marts/                   # fct_member_features_daily.sql — 29 daily features
│
├── data/                        # Pre-built synthetic parquet datasets
│   ├── members.parquet
│   ├── sessions.parquet
│   ├── transactions.parquet
│   ├── fct_member_features_daily.parquet
│   ├── churn_scores_daily.parquet
│   ├── int_member_identity.parquet  # Encrypted (AES-256)
│   └── ...
│
├── deploy/                      # Production deployment recipes
│   ├── Dockerfile               # Multi-stage build (dashboard + cron scheduler)
│   ├── docker-compose.yml       # Dashboard + nightly ETL scheduler
│   └── terraform/               # AWS ECS, RDS, Secrets Manager provisioning
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
│
├── train_evaluate.ipynb         # Model training notebook (XGBoost + calibration)
├── demo_visualization.ipynb     # Data exploration & validation notebook
├── SECURITY.md                  # Threat model & data classification audit
├── handoff_runbook.md           # Operator on-call playbook & A/B measurement guide
└── playbook_identity_resolution.md  # Identity matching rules documentation
```

---

## 📊 Model Performance

> **Note:** All metrics are evaluated on **synthetic data** generated by `generate_synthetic_data.py`. The high AUC reflects the structured nature of synthetic data, not a claim about real-world churn prediction performance. Retraining on real member data is required before drawing production conclusions.

| Metric | Value (synthetic) | Target |
|---|---|---|
| **AUC-ROC** | 0.963 | > 0.80 ✅ |
| **Precision @ top-10%** | 73.9% | > 50% ✅ |
| **Calibration** | Well-calibrated | Scores ≈ real probabilities ✅ |

### Top Predictive Signals
1. Billing failure indicators
2. Days since last session
3. App login frequency (30-day rolling)
4. AI Coach cancel/freeze inquiries
5. Email open rate decline

---

## 🔒 Security

- **PII Encryption**: `int_member_identity.parquet` encrypted with AES-256 Fernet symmetric keys
- **Password Hashing**: PBKDF2-HMAC-SHA256 with 240,000 iterations and per-user random salt
- **Row-Level Security**: DuckDB temporary views scoped per-session; GMs isolated to their studio
- **Credential Validation**: Live API adapters fail loudly if keys are missing in production mode
- **Model Artifacts**: `.joblib` and `.pkl` files gitignored to prevent training data leakage

See [SECURITY.md](SECURITY.md) for the full threat model.

---

## 🐳 Docker Deployment

```bash
cd deploy

# Build and launch dashboard + nightly ETL scheduler
docker-compose up --build -d

# Dashboard available at http://localhost:8501
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HOTWORX_IDENTITY_ENCRYPTION_KEY` | Yes (prod) | Fernet AES-256 encryption key |
| `HOTWORX_IDENTITY_SALT` | Yes (prod) | Hashing pepper for surrogate keys |
| `HOTWORX_DATA_SOURCE` | No | `demo` (default) or `production` |
| `HOTWORX_DB_CONN` | Prod only | SQLAlchemy connection string |
| `INTERVENTIONS_LIVE` | No | `true` to enable live API calls |
| `TWILIO_ACCOUNT_SID` | Live only | Twilio SMS credentials |
| `TWILIO_AUTH_TOKEN` | Live only | Twilio SMS credentials |
| `HW_CAMPAIGN_API_KEY` | Live only | Email campaign API key |
| `PUSH_SERVER_KEY` | Live only | Firebase Cloud Messaging key |
| `DASHBOARD_ADMIN_PW` | No | Override default admin password |
| `DASHBOARD_GM_PW` | No | Override default GM password |

---

## 🛣️ Roadmap

- [ ] Connect real SailPOS / app database exports via `data_adapters.py`
- [ ] Replace synthetic data with anonymized HOTWORX member data
- [ ] Deploy to AWS ECS using `deploy/terraform/` configs
- [ ] Activate live Twilio SMS and HW Campaign email integrations
- [ ] Implement 30/60/90-day A/B test measurement cadence
- [ ] Add model retraining pipeline with drift detection

---

## 📄 License

This project is proprietary and confidential. Source code access is restricted.

---

<p align="center">
  Built with ❤️ using Python, Streamlit, DuckDB, XGBoost, and Plotly
</p>
