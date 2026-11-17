SELECT p.home_province, sum(pr.quantity * d.price) AS total_cost
FROM public.prescription pr
JOIN public.visit v USING (visit_id)
JOIN public.patient p USING (patient_id)
JOIN public.drug d USING (drug_code)
WHERE v.visit_date >= DATE '2025-01-01' AND v.visit_date < DATE '2026-01-01'
GROUP BY p.home_province
UNION ALL
SELECT p.home_province, sum(pr.quantity * d.price) AS total_cost
FROM hcm.prescription pr
JOIN hcm.visit v USING (visit_id)
JOIN hcm.patient p USING (patient_id)
JOIN hcm.drug d USING (drug_code)
WHERE v.visit_date >= DATE '2025-01-01' AND v.visit_date < DATE '2026-01-01'
GROUP BY p.home_province
UNION ALL
SELECT p.home_province, sum(pr.quantity * d.price) AS total_cost
FROM cantho.prescription pr
JOIN cantho.visit v USING (visit_id)
JOIN cantho.patient p USING (patient_id)
JOIN cantho.drug d USING (drug_code)
WHERE v.visit_date >= DATE '2025-01-01' AND v.visit_date < DATE '2026-01-01'
GROUP BY p.home_province
UNION ALL
SELECT p.home_province, sum(pr.quantity * d.price) AS total_cost
FROM dongnai.prescription pr
JOIN dongnai.visit v USING (visit_id)
JOIN dongnai.patient p USING (patient_id)
JOIN dongnai.drug d USING (drug_code)
WHERE v.visit_date >= DATE '2025-01-01' AND v.visit_date < DATE '2026-01-01'
GROUP BY p.home_province;
