SELECT
  session_id,
  member_id,
  studio_id,
  session_type,
  scheduled_at,
  attended,
  sauna_temp_f,
  is_synthetic
FROM raw_sessions
