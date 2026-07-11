# Multi-Cloud FinOps Cost Pipeline

An end-to-end FinOps portfolio project that ingests AWS, GCP, and
Kubernetes cost data, normalizes it into a common FOCUS-aligned schema,
validates and reconciles costs, allocates shared spend, detects anomalies,
and produces finance-ready reports.

## Build approach

- Real AWS and GCP environments for billing exploration and authentication
- Synthetic billing data for development and testing
- Python, SQL, BigQuery, DuckDB, Excel, Power BI, and Tableau
- Automated tests and GitHub Actions