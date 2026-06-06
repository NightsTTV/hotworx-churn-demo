-- Identity / re-identification lookup table.
-- TODO (Phase 5): the hashing salt below is a hardcoded, committed, static pepper — it offers
-- little real protection. Before any real member data: move the salt to a secrets manager and
-- treat this whole table as RESTRICTED (encrypt at rest, least-privilege access), since it still
-- stores plaintext name/email/phone alongside the hashed key.
SELECT
  member_id,
  sha256(concat(email, 'hotworx_secret_salt_2026')) as hashed_member_id,
  name,
  email,
  phone
FROM stg_members
