SELECT DISTINCT patient_id
FROM public.visit
WHERE specialty = 'cardio'
  AND (result->>'bp_systolic')::int >= 140;
