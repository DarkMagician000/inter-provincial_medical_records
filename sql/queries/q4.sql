SELECT DISTINCT patient_id
FROM public.all_visit
WHERE specialty = 'cardio'
  AND (result->>'bp_systolic')::int >= 140;
