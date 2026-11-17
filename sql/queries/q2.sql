-- Two-stage aggregation: each site sums locally, central combines the results.
-- Patients (and their home provinces) are disjoint across sites: UNION ALL is exact.
SELECT home_province, total_cost FROM public.drug_cost_by_year WHERE year = 2025
UNION ALL
SELECT home_province, total_cost FROM hcm.drug_cost_by_year WHERE year = 2025
UNION ALL
SELECT home_province, total_cost FROM cantho.drug_cost_by_year WHERE year = 2025
UNION ALL
SELECT home_province, total_cost FROM dongnai.drug_cost_by_year WHERE year = 2025;
