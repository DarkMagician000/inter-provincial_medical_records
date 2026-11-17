SELECT :site_no * 1000000 + 1 AS start,
       :site_no * 1000000 + 999999 AS end
\gset

ALTER TABLE patient
    ADD CONSTRAINT patient_frag_ck CHECK (home_province = :'site'),
    ADD CONSTRAINT patient_id_ck
        CHECK (patient_id <= 20000 OR patient_id BETWEEN :start AND :end);

ALTER TABLE visit
    ADD CONSTRAINT visit_id_ck
        CHECK (visit_id <= 80000 OR visit_id BETWEEN :start AND :end),
    ADD CONSTRAINT visit_result_ck CHECK (
        CASE specialty
            WHEN 'cardio' THEN result ?& ARRAY['bp_systolic', 'bp_diastolic', 'heart_rate', 'ecg']
            WHEN 'eye' THEN result ?& ARRAY['va_left', 'va_right', 'iop_mmhg', 'diagnoses']
            WHEN 'blood' THEN result ?& ARRAY['wbc', 'rbc', 'glucose', 'tests']
            ELSE false
        END
    );

ALTER TABLE prescription
    ADD CONSTRAINT prescription_id_ck
        CHECK (prescription_id <= 200000 OR prescription_id BETWEEN :start AND :end);

CREATE SEQUENCE patient_id_seq START :start MINVALUE :start MAXVALUE :end NO CYCLE;
CREATE SEQUENCE visit_id_seq START :start MINVALUE :start MAXVALUE :end NO CYCLE;
CREATE SEQUENCE prescription_id_seq START :start MINVALUE :start MAXVALUE :end NO CYCLE;
