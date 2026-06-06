-- Single source of truth for the observation horizon ("as-of" date), derived from the data
-- itself instead of a hardcoded literal, so the model stays correct whenever data is regenerated.
WITH config AS (
  SELECT GREATEST(
    (SELECT MAX(CAST(scheduled_at AS DATE)) FROM stg_sessions),
    (SELECT MAX(CAST(event_timestamp AS DATE)) FROM stg_app_events),
    (SELECT MAX(transaction_date) FROM stg_transactions),
    (SELECT MAX(CAST(sent_at AS DATE)) FROM stg_email_events),
    (SELECT MAX(COALESCE(churn_date, DATE '1900-01-01')) FROM stg_ground_truth)
  ) AS as_of_date
),

-- Generate date spine for active member days
date_spine AS (
  SELECT CAST(range AS DATE) AS date_day
  FROM range(
    (SELECT MIN(join_date) FROM stg_members),
    (SELECT as_of_date + INTERVAL 1 DAY FROM config),
    INTERVAL '1 day'
  )
),

member_date_spine AS (
  SELECT
    d.date_day,
    m.member_id,
    m.join_date,
    m.dob,
    m.gender,
    m.home_studio_id,
    mb.membership_tier,
    mb.monthly_price,
    gt.churned,
    gt.churn_date
  FROM date_spine d
  CROSS JOIN stg_members m
  JOIN stg_ground_truth gt ON m.member_id = gt.member_id
  JOIN stg_memberships mb ON m.member_id = mb.member_id
  WHERE d.date_day >= m.join_date
    AND d.date_day <= COALESCE(gt.churn_date, (SELECT as_of_date FROM config))
),

-- Pre-aggregations of events by day and member
daily_sessions AS (
  SELECT
    member_id,
    CAST(scheduled_at AS DATE) AS event_date,
    COUNT(*) AS booked_count,
    SUM(CASE WHEN attended THEN 1 ELSE 0 END) AS attended_count,
    SUM(CASE WHEN attended THEN sauna_temp_f ELSE 0.0 END) AS temp_sum,
    SUM(CASE WHEN attended THEN 1 ELSE 0 END) AS temp_count
  FROM stg_sessions
  GROUP BY 1, 2
),

daily_transactions AS (
  SELECT
    member_id,
    transaction_date AS event_date,
    SUM(CASE WHEN transaction_type LIKE 'Retail%' AND status = 'Paid' THEN amount ELSE 0.0 END) AS retail_spend,
    SUM(CASE WHEN transaction_type = 'Membership Fee' AND status = 'Failed' THEN 1 ELSE 0 END) AS membership_failed_count,
    MAX(CASE WHEN transaction_type = 'Membership Fee' THEN status END) AS membership_status
  FROM stg_transactions
  GROUP BY 1, 2
),

daily_app_events AS (
  SELECT
    member_id,
    CAST(event_timestamp AS DATE) AS event_date,
    -- 'open_app' is the app's login-equivalent event; it is the only open event the source emits.
    SUM(CASE WHEN event_type = 'open_app' THEN 1 ELSE 0 END) AS logins_count,
    SUM(CASE WHEN event_type = 'view_metrics' THEN 1 ELSE 0 END) AS metric_views_count
  FROM stg_app_events
  GROUP BY 1, 2
),

daily_chats AS (
  SELECT
    member_id,
    CAST(timestamp AS DATE) AS event_date,
    COUNT(*) AS chats_count,
    SUM(CASE WHEN sender = 'member' AND (
      LOWER(message_text) LIKE '%cancel%' OR
      LOWER(message_text) LIKE '%freeze%' OR
      LOWER(message_text) LIKE '%terminate%' OR
      LOWER(message_text) LIKE '%decline%'
    ) THEN 1 ELSE 0 END) AS cancellation_queries_count
  FROM stg_ai_coach_chats
  GROUP BY 1, 2
),

daily_emails AS (
  SELECT
    member_id,
    CAST(sent_at AS DATE) AS event_date,
    COUNT(*) AS emails_sent,
    SUM(CASE WHEN status IN ('Opened', 'Clicked') THEN 1 ELSE 0 END) AS emails_opened,
    SUM(CASE WHEN status = 'Clicked' THEN 1 ELSE 0 END) AS emails_clicked
  FROM stg_email_events
  GROUP BY 1, 2
),

-- Join spine with daily activities
daily_joined AS (
  SELECT
    mds.date_day,
    mds.member_id,
    mds.join_date,
    mds.dob,
    mds.gender,
    mds.home_studio_id,
    mds.membership_tier,
    mds.monthly_price,
    mds.churned,
    mds.churn_date,
    
    -- Sessions
    ds.booked_count AS daily_sessions_booked,
    ds.attended_count AS daily_sessions_attended,
    ds.temp_sum AS daily_temp_sum,
    ds.temp_count AS daily_temp_count,
    
    -- Transactions
    dt.retail_spend AS daily_retail_spend,
    dt.membership_failed_count AS daily_failed_payments,
    dt.membership_status AS daily_membership_status,
    
    -- App Events
    da.logins_count AS daily_app_logins,
    da.metric_views_count AS daily_metric_views,
    
    -- Chats
    dc.chats_count AS daily_chats,
    dc.cancellation_queries_count AS daily_cancellation_queries,
    
    -- Emails
    de.emails_sent AS daily_emails_sent,
    de.emails_opened AS daily_emails_opened,
    de.emails_clicked AS daily_emails_clicked
  FROM member_date_spine mds
  LEFT JOIN daily_sessions ds ON mds.member_id = ds.member_id AND mds.date_day = ds.event_date
  LEFT JOIN daily_transactions dt ON mds.member_id = dt.member_id AND mds.date_day = dt.event_date
  LEFT JOIN daily_app_events da ON mds.member_id = da.member_id AND mds.date_day = da.event_date
  LEFT JOIN daily_chats dc ON mds.member_id = dc.member_id AND mds.date_day = dc.event_date
  LEFT JOIN daily_emails de ON mds.member_id = de.member_id AND mds.date_day = de.event_date
),

-- Rolling window calculations
rolling_features AS (
  SELECT
    date_day,
    member_id,
    join_date,
    dob,
    gender,
    home_studio_id,
    membership_tier,
    monthly_price,
    churned,
    churn_date,
    
    -- Demographics and Membership
    date_day - join_date AS tenure_days,
    (date_day - dob) / 365.25 AS age,
    
    -- Sessions (7d & 30d)
    SUM(COALESCE(daily_sessions_booked, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS sessions_booked_7d,
    SUM(COALESCE(daily_sessions_booked, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS sessions_booked_30d,
    
    SUM(COALESCE(daily_sessions_attended, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS sessions_attended_7d,
    SUM(COALESCE(daily_sessions_attended, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS sessions_attended_30d,
    
    -- Sauna Temp 30d
    SUM(COALESCE(daily_temp_sum, 0.0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS temp_sum_30d,
    SUM(COALESCE(daily_temp_count, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS temp_count_30d,
    
    -- Days since last session
    MAX(CASE WHEN COALESCE(daily_sessions_attended, 0) > 0 THEN date_day END) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS last_attended_date,
    
    -- Transactions (30d)
    SUM(COALESCE(daily_retail_spend, 0.0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS retail_spend_30d,
    SUM(COALESCE(daily_failed_payments, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS failed_payments_count_30d,
    
    -- Last membership fee transaction status
    LAST_VALUE(daily_membership_status IGNORE NULLS) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS last_payment_status,
    
    -- App Events (7d & 30d)
    SUM(COALESCE(daily_app_logins, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS app_logins_7d,
    SUM(COALESCE(daily_app_logins, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS app_logins_30d,
    SUM(COALESCE(daily_metric_views, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS metric_views_30d,
    
    -- Chats (30d)
    SUM(COALESCE(daily_chats, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS coach_chat_count_30d,
    SUM(COALESCE(daily_cancellation_queries, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS cancellation_queries_count_30d,
    
    -- Emails (30d)
    SUM(COALESCE(daily_emails_sent, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS emails_sent_30d,
    SUM(COALESCE(daily_emails_opened, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS emails_opened_30d,
    SUM(COALESCE(daily_emails_clicked, 0)) OVER (
      PARTITION BY member_id ORDER BY date_day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS emails_clicked_30d
  FROM daily_joined
)

SELECT
  i.hashed_member_id,
  r.date_day,
  CAST(r.age AS DOUBLE) AS age,
  r.gender,
  r.home_studio_id,
  r.membership_tier,
  r.monthly_price,
  CAST(r.tenure_days AS INTEGER) AS tenure_days,
  
  CAST(r.sessions_booked_7d AS INTEGER) AS sessions_booked_7d,
  CAST(r.sessions_booked_30d AS INTEGER) AS sessions_booked_30d,
  CAST(r.sessions_attended_7d AS INTEGER) AS sessions_attended_7d,
  CAST(r.sessions_attended_30d AS INTEGER) AS sessions_attended_30d,
  
  -- NULL (not 0.0) when there were no bookings in the window, so an *inactive* member is
  -- distinguishable from one who *booked but no-showed*. XGBoost handles missingness natively.
  CASE
    WHEN r.sessions_booked_7d > 0 THEN CAST(r.sessions_attended_7d AS DOUBLE) / r.sessions_booked_7d
    ELSE NULL
  END AS attendance_rate_7d,

  CASE
    WHEN r.sessions_booked_30d > 0 THEN CAST(r.sessions_attended_30d AS DOUBLE) / r.sessions_booked_30d
    ELSE NULL
  END AS attendance_rate_30d,
  
  CASE 
    WHEN r.temp_count_30d > 0 THEN r.temp_sum_30d / r.temp_count_30d
    ELSE 0.0 
  END AS avg_sauna_temp_30d,
  
  COALESCE(r.date_day - r.last_attended_date, 999) AS days_since_last_session,
  r.retail_spend_30d,
  
  CASE 
    WHEN r.last_payment_status = 'Failed' THEN TRUE 
    ELSE FALSE 
  END AS last_recurring_payment_failed,
  
  CAST(r.failed_payments_count_30d AS INTEGER) AS failed_payments_count_30d,
  CAST(r.app_logins_7d AS INTEGER) AS app_logins_7d,
  CAST(r.app_logins_30d AS INTEGER) AS app_logins_30d,
  CAST(r.metric_views_30d AS INTEGER) AS metric_views_30d,
  CAST(r.coach_chat_count_30d AS INTEGER) AS coach_chat_count_30d,
  
  CASE 
    WHEN r.cancellation_queries_count_30d > 0 THEN TRUE 
    ELSE FALSE 
  END AS has_cancellation_query_30d,
  
  CAST(r.emails_sent_30d AS INTEGER) AS emails_sent_30d,
  CAST(r.emails_opened_30d AS INTEGER) AS emails_opened_30d,
  CAST(r.emails_clicked_30d AS INTEGER) AS emails_clicked_30d,
  
  -- NULL (not 0.0) when no emails were sent in the window, consistent with attendance_rate;
  -- "wasn't emailed" is not the same as "emailed and never opened".
  CASE
    WHEN r.emails_sent_30d > 0 THEN CAST(r.emails_opened_30d AS DOUBLE) / r.emails_sent_30d
    ELSE NULL
  END AS email_open_rate_30d,
  
  -- Target Churn Label: cancels in the next 14 days
  CASE
    WHEN r.churned AND r.churn_date BETWEEN r.date_day + INTERVAL '1 day' AND r.date_day + INTERVAL '14 days' THEN TRUE
    ELSE FALSE
  END AS is_churned_14d,
  
  TRUE AS is_synthetic
FROM rolling_features r
JOIN int_member_identity i ON r.member_id = i.member_id
ORDER BY 1, 2
