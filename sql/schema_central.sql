CREATE TABLE hospital (
    hospital_id integer PRIMARY KEY,
    name text,
    province text
);

CREATE TABLE drug (
    drug_code text PRIMARY KEY,
    name text,
    unit text,
    price numeric
);

CREATE TABLE patient (
    patient_id integer PRIMARY KEY,
    full_name text,
    birth_year smallint,
    gender char,
    home_province text
);

CREATE TABLE visit (
    visit_id integer PRIMARY KEY,
    patient_id integer REFERENCES patient (patient_id),
    hospital_id integer REFERENCES hospital (hospital_id),
    specialty text,
    visit_date date,
    result jsonb
);

CREATE TABLE prescription (
    prescription_id integer PRIMARY KEY,
    visit_id integer REFERENCES visit (visit_id),
    drug_code text REFERENCES drug (drug_code),
    quantity integer,
    days smallint
);

CREATE TABLE visit_cardio (
    visit_id integer PRIMARY KEY REFERENCES visit (visit_id),
    bp_systolic smallint,
    bp_diastolic smallint,
    heart_rate smallint,
    ecg_rhythm text,
    ecg_qt_ms smallint
);

CREATE TABLE visit_eye (
    visit_id integer PRIMARY KEY REFERENCES visit (visit_id),
    va_left numeric,
    va_right numeric,
    iop_mmhg smallint
);

CREATE TABLE visit_blood (
    visit_id integer PRIMARY KEY REFERENCES visit (visit_id),
    wbc numeric,
    rbc numeric,
    glucose numeric
);

CREATE TABLE visit_eye_diagnosis (
    visit_id integer REFERENCES visit_eye (visit_id),
    seq smallint,
    diagnosis text,
    PRIMARY KEY (visit_id, seq)
);

CREATE TABLE visit_blood_test (
    visit_id integer REFERENCES visit_blood (visit_id),
    code text,
    value numeric,
    unit text,
    PRIMARY KEY (visit_id, code)
);
