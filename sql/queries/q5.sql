-- Patients are disjoint across sites; only within-site deduplication is needed.
SELECT DISTINCT v.patient_id
FROM public.visit_cardio c JOIN public.visit v USING (visit_id)
WHERE c.bp_systolic >= 140
UNION ALL
SELECT DISTINCT v.patient_id
FROM hcm.visit_cardio c JOIN hcm.visit v USING (visit_id)
WHERE c.bp_systolic >= 140
UNION ALL
SELECT DISTINCT v.patient_id
FROM cantho.visit_cardio c JOIN cantho.visit v USING (visit_id)
WHERE c.bp_systolic >= 140
UNION ALL
SELECT DISTINCT v.patient_id
FROM dongnai.visit_cardio c JOIN dongnai.visit v USING (visit_id)
WHERE c.bp_systolic >= 140;
