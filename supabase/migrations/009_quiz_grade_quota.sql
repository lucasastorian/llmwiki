-- Durable rolling-window accounting for hosted free-form quiz grading.
-- One row is written immediately before each Workers AI request begins.

CREATE TABLE quiz_grade_attempts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX idx_quiz_grade_attempts_user_created
    ON quiz_grade_attempts (user_id, created_at);

ALTER TABLE quiz_grade_attempts ENABLE ROW LEVEL SECURITY;

-- Deliberately no authenticated policies. This is an internal billing ledger;
-- allowing users to insert or delete their own rows would let them manipulate
-- the quota. The hosted API's database owner writes it after JWT verification.
