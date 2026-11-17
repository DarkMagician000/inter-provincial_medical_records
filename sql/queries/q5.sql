-- Two-stage aggregation: each site groups by patient, central combines the results.
-- max >= 140 means at least one qualifying visit; patients are disjoint across sites.
SELECT patient_id FROM public.cardio_patient_bp WHERE max_bp_systolic >= 140
UNION ALL
SELECT patient_id FROM hcm.cardio_patient_bp WHERE max_bp_systolic >= 140
UNION ALL
SELECT patient_id FROM cantho.cardio_patient_bp WHERE max_bp_systolic >= 140
UNION ALL
SELECT patient_id FROM dongnai.cardio_patient_bp WHERE max_bp_systolic >= 140;
