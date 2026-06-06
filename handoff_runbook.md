# Operator Handoff & On-Call Runbook

This manual governs the maintenance, troubleshooting, and validation metrics of the HOTWORX Churn prediction and re-engagement system.

---

## 📞 On-Call Emergency Playbooks

### 1. Alert: Automated Outbound Kill Switch Fired
* **Symptom**: The log shows `RuntimeError: Global rate limit exceeded! Kill switch engaged...`
* **Trigger**: More than 50 automated messages (SMS/Email) were dispatched globally within a rolling 60-minute window. This indicates a potential loop or pipeline misfire.
* **Immediate Mitigation Actions**:
  1. Kill the active runner task or Docker container immediately.
  2. Inspect the audit log: `SELECT COUNT(*), action_type FROM read_parquet('data/intervention_audit_log.parquet') WHERE sent_at >= now() - INTERVAL 1 hour GROUP BY action_type` to locate the source of the high frequency sends.
  3. Verify that the scheduled cron trigger has not been spawned repeatedly (double-triggering).
  4. Ensure `INTERVENTIONS_LIVE=false` is set in the environment while debugging to force Dry-Run mode.

### 2. Alert: Identity Decryption Fails
* **Symptom**: `cryptography.fernet.InvalidToken` raised during scoring or dashboard render.
* **Troubleshooting Steps**:
  1. Check if the environment variable `HOTWORX_IDENTITY_ENCRYPTION_KEY` has been changed or rotated.
  2. If the key was rotated without re-encrypting the existing `data/int_member_identity.parquet` database, restore the old key to decrypt, then run `identity_resolver.py` with the new key to re-encrypt and write it back.

---

## 📈 30 / 60 / 90 Day A/B Measurement Plan

To evaluate the financial lift of the predictive interventions, we compare the churn rates of the **Treatment (notified)** group and the **Holdout (untreated control)** group.

### Metric Formulae

$$ \text{Treatment Churn Rate} = \frac{\text{Churned Treatment Members}}{\text{Total Treatment Members}} $$

$$ \text{Holdout Churn Rate} = \frac{\text{Churned Holdout Members}}{\text{Total Holdout Members}} $$

$$ \text{Absolute Churn Lift} = \text{Holdout Churn Rate} - \text{Treatment Churn Rate} $$

$$ \text{Relative Churn Reduction} = \frac{\text{Absolute Churn Lift}}{\text{Holdout Churn Rate}} $$

### Evaluation Cadence
* **30-Day Check**: Validate that A/B assignments are consistent (the same member does not jump groups) and verify initial re-engagement response rates (SMS link clicks and email open rates).
* **60-Day Check**: Measure relative risk metrics. Calculate the Chi-Square statistical significance test on the churn rates. (Target: $p < 0.05$).
* **90-Day Check**: Compute total saved revenue:
  $$ \text{Saved Revenue} = (\text{Total Treatment Members}) \times (\text{Absolute Churn Lift}) \times (\text{Average Monthly Price}) $$

---

## 🛠️ CI Secrets Auditing (TruffleHog & Gitleaks)

To protect keys and encryption secrets, configure the following hooks in GitHub Action workflows (`.github/workflows/security.yml`):

```yaml
name: Security Scan

on: [push, pull_request]

jobs:
  secrets-scan:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```
Ensure all developer workstations install pre-commit secret scanners:
```bash
pip install pre-commit
pre-commit install
```
Add a `.pre-commit-config.yaml` specifying `gitleaks` checks to prevent committing unencrypted keys or salts.
