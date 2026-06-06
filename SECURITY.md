# Security Policy - HOTWORX Churn Prediction Pipeline

This document defines the security architecture, threat model, data classifications, and compliance guidelines for the HOTWORX churn prediction system.

---

## 🔒 Data Classifications

We categorize our data into three tiers to enforce least-privilege access and appropriate security controls:

### 1. Restricted (PII)
- **Data Types**: Plaintext Member Names, Emails, Phone Numbers, and Hashing Salts.
- **Artifact**: `data/int_member_identity.parquet`
- **Security Policy**:
  - Must be **encrypted at rest** using AES-256 (via symmetric Fernet encryption keys).
  - Access keys must *never* be stored in code or repository `.env` files.
  - Resolved plaintext data must only exist **in-memory** during diagnostics and must *never* be logged to stdout or files.

### 2. Confidential
- **Data Types**: Individual Churn Scores, Feature Matrix rows, and Intervention logs.
- **Artifacts**: `data/fct_member_features_daily.parquet`, `data/churn_scores_daily.parquet`, `data/intervention_queue.parquet`, and `data/intervention_audit_log.parquet`.
- **Security Policy**:
  - Stores de-identified hashed surrogate keys (`hashed_member_id`) instead of raw IDs.
  - Restricted to users with authorised data warehouse roles.

### 3. Public / Operational
- **Data Types**: Aggregated KPI stats, risk distribution metrics, and model performance charts.
- **Security Policy**:
  - Accessible via secure, role-authenticated dashboard panels.

---

## 🎯 Threat Model & Mitigations

### 1. Insider Abuse (Row-Level Security Bypass)
- **Threat**: A studio manager (GM) attempts to search or look up scores of members belonging to another studio (e.g. searching for a competitor's customer or personal associate).
- **Mitigation**: Security filters are hard-injected at the **database query layer** using DuckDB secure temporary views:
  ```sql
  CREATE TEMPORARY VIEW secure_features AS SELECT * FROM features WHERE home_studio_id = ?;
  CREATE TEMPORARY VIEW secure_scores AS SELECT * FROM scores WHERE hashed_member_id IN (SELECT hashed_member_id FROM secure_features);
  ```
  Even if front-end filters are bypassed or the URL is tampered with, the query engine returns zero rows for unauthorized studios.

### 2. Credential Leakage & API Key Theft
- **Threat**: Twilio SIDs, HW Campaign tokens, database credentials, or encryption keys are committed to Git.
- **Mitigation**:
  - All keys are loaded strictly via environment variables or cloud secrets managers (AWS Secrets Manager, GCP Secret Manager).
  - `.gitignore` explicitly filters out local development credential stores (`.env`, `.env.*`).
  - Added secrets scanning (gitleaks / trufflehog config) to the build pipeline.

### 3. Training Data Reconstruction via Model Inversion
- **Threat**: Model weight artifacts (`.joblib` pipelines) are committed to git, enabling an attacker to reverse-engineer training feature distributions.
- **Mitigation**: Model weights are gitignored and published to secure cloud bucket storages (e.g., S3/GCS) with restricted bucket access.

---

## 🛡️ Key Management

### Symmetric Encryption Key
To access encrypted identity logs, operators must set the following environment variables:
- `HOTWORX_IDENTITY_ENCRYPTION_KEY`: A base64-encoded 32-byte Fernet key.
- `HOTWORX_IDENTITY_SALT`: A secure cryptographic pepper for member ID hashing.

For local sandbox verification, if these variables are absent, a default development fallback is used, throwing a prominent console warning:
```
⚠️ WARNING: Using fallback development encryption keys. Do not run in production!
```
