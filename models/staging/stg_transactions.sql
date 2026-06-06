SELECT
  transaction_id,
  member_id,
  studio_id,
  transaction_date,
  amount,
  transaction_type,
  status,
  is_synthetic
FROM raw_transactions
