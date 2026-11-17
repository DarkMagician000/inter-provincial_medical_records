SELECT DISTINCT v.patient_id
FROM public.visit_cardio c JOIN public.visit v USING (visit_id)
WHERE c.bp_systolic >= 140;
