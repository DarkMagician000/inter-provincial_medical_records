SELECT p.home_province, sum(pr.quantity * d.price) AS total_cost
FROM public.prescription pr
JOIN public.visit v USING (visit_id)
JOIN public.patient p USING (patient_id)
JOIN public.drug d USING (drug_code)
WHERE v.visit_date >= DATE '2025-01-01' AND v.visit_date < DATE '2026-01-01'
GROUP BY p.home_province;
