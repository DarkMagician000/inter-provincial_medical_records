CREATE OR REPLACE VIEW drug_cost_by_year AS
SELECT p.home_province, extract(year FROM v.visit_date)::int AS year,
       sum(pr.quantity * d.price) AS total_cost
FROM prescription pr
JOIN visit v USING (visit_id)
JOIN patient p USING (patient_id)
JOIN drug d USING (drug_code)
GROUP BY 1, 2;

CREATE OR REPLACE VIEW cardio_patient_bp AS
SELECT v.patient_id, max(c.bp_systolic) AS max_bp_systolic
FROM visit_cardio c
JOIN visit v USING (visit_id)
GROUP BY 1;
