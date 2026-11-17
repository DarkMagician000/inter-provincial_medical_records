SELECT v.specialty, count(*) AS visit_count
FROM public.visit v
JOIN public.patient p USING (patient_id)
WHERE p.home_province = 'tayninh'
  AND v.visit_date >= DATE '2026-03-01'
  AND v.visit_date < DATE '2026-04-01'
GROUP BY v.specialty;
