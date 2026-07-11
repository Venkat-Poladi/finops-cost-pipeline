# Synthetic Cloud Billing Data

The files in this folder are deterministic, synthetic enterprise-scale
billing datasets created for developing and demonstrating the FinOps pipeline.

They do not represent the project owner's actual AWS or GCP usage or spend.

## Files

- `generate_synthetic_billing.py` — creates both datasets
- `aws_billing_sample.csv` — AWS CUR-inspired flattened CSV
- `gcp_billing_sample.csv` — GCP BigQuery billing-export-inspired CSV

## Dataset scope

- 90 usage days: April 1 through June 29, 2026
- Two AWS linked accounts
- Two GCP projects
- Five services per provider
- Two resources per service
- Usage charges, credits and refunds
- Tagged and untagged resources
- Shared platform costs
- Deliberate cost anomalies
- Exact duplicate rows
- Invalid negative regular-usage rows

## Important simplifications

The CSV schemas resemble real provider exports but are not exact copies.

- Real AWS CUR exposes cost-allocation tags as dynamic columns.
- Real GCP billing export stores labels and credits as repeated nested records.
- JSON strings are used in the CSV fixture because CSV cannot preserve nested
  cloud-provider data structures.
- Real AWS and GCP connectors will use provider-specific adapters before
  mapping records into the common FOCUS-aligned schema.

## Cost interpretation

These are enterprise-scale synthetic values. They must not be compared with
the project's low-spend live AWS and GCP learning accounts.