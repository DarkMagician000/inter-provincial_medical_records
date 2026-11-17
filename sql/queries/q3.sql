SELECT *
FROM public.all_visit
WHERE visit_date >= DATE '2026-03-01'
  AND visit_date < DATE '2026-04-01'
  AND hospital_id = ANY(ARRAY(
      SELECT hospital_id FROM public.hospital WHERE province = 'tayninh'
  ));
