import streamlit as st
import pandas as pd
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import os
import datetime
import hashlib

# Page configuration
st.set_page_config(
    page_title="HOTWORX Churn Control Center",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Dark UI (Emil Kowalski Design style)
st.markdown("""
<style>
    /* Main container background */
    .stApp {
        background-color: #0D0D0D;
        color: #E2E8F0;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #121212 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Input inputs, dropdowns */
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
        background-color: #1A1A1A !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
    }
    
    /* Custom Card */
    .card {
        background-color: #151515;
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        transition: border-color 0.3s ease;
    }
    .card:hover {
        border-color: rgba(95, 87, 255, 0.3);
    }
    
    /* Stat Metrics */
    .metric-title {
        font-size: 13px;
        color: #8A8F98;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        font-size: 32px;
        font-weight: 700;
        color: #FFFFFF;
        margin-top: 6px;
    }
    .metric-delta {
        font-size: 13px;
        margin-top: 4px;
        font-weight: 600;
    }
    .delta-up { color: #FF4A4A; }
    .delta-down { color: #10B981; }
    
    /* Electric Indigo Accent Buttons */
    .stButton>button {
        background-color: #5F57FF !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 10px 24px !important;
        transition: transform 0.16s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.2s !important;
    }
    .stButton>button:hover {
        background-color: #4B44E6 !important;
        border: none !important;
    }
    .stButton>button:active {
        transform: scale(0.96) !important;
    }
    
    /* Secondary/Outline Buttons */
    .stButton>button[secondary="true"] {
        background-color: transparent !important;
        color: #E2E8F0 !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
    }
    .stButton>button[secondary="true"]:hover {
        background-color: rgba(255, 255, 255, 0.05) !important;
    }
    
    /* Heading styling */
    h1, h2, h3 {
        color: #FFFFFF !important;
        font-weight: 700 !important;
    }
    
    /* Divider */
    hr {
        border-color: rgba(255, 255, 255, 0.06) !important;
    }
</style>
""", unsafe_allow_html=True)

DATA_DIR = "./data"
AUDIT_LOG_PATH = os.path.join(DATA_DIR, "intervention_audit_log.parquet")
QUEUE_PATH = os.path.join(DATA_DIR, "intervention_queue.parquet")
IDENTITY_PATH = os.path.join(DATA_DIR, "int_member_identity.parquet")
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
SCORES_PATH = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
GROUND_TRUTH_PATH = os.path.join(DATA_DIR, "ground_truth.parquet")

# Dashboard accounts are loaded WITHOUT plaintext passwords in source (see auth.py):
#   - dashboard_users.json (gitignored) or DASHBOARD_USERS_JSON env, if present (hashed records)
#   - else a demo fallback: hashed in-memory from DASHBOARD_ADMIN_PW / DASHBOARD_GM_PW (demo defaults)
from auth import load_user_accounts, verify_password
USER_ACCOUNTS = load_user_accounts()

# ==============================================================================
# AUTHENTICATION LAYER
# ==============================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""
    st.session_state.user_studio = None

def login():
    st.sidebar.title("🔐 Authentication")
    username = st.sidebar.text_input("Username").strip().lower()
    password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Log In"):
        acct = USER_ACCOUNTS.get(username)
        if acct and verify_password(password, acct["password_hash"]):
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.user_role = acct["role"]
            st.session_state.user_studio = acct["studio"]
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password.")

def logout():
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""
    st.session_state.user_studio = None
    st.rerun()

if not st.session_state.authenticated:
    st.title("🔥 HOTWORX Churn Control Center")
    st.subheader("Predictive Member Retention & Intervention Dashboard")
    st.info("Please enter your credentials in the sidebar to log in.")
    login()
    st.stop()

# ==============================================================================
# ROW-LEVEL SQL DATABASE ENGINE (DUCKDB) -- per-session, access-scoped
# ==============================================================================
import re

user_role = st.session_state.user_role
user_studio = st.session_state.user_studio

def get_scoped_connection():
    """Return a PER-SESSION DuckDB connection whose base views (features/identity/scores) are
    already scoped to the logged-in user's access. For a GM, `features` is filtered to their home
    studio, and `identity`/`scores` are restricted to members in that filtered set -- so EVERY
    downstream query that references these names is row-level-secured automatically, with no
    query-text rewriting.

    The connection lives in st.session_state (NOT @st.cache_resource), so concurrent users never
    share or overwrite each other's scoped views, which the previous cached-connection design did.
    """
    if "db_con" not in st.session_state:
        st.session_state.db_con = duckdb.connect(database=":memory:")
    con = st.session_state.db_con

    import secure_data
    df_identity = secure_data.read_encrypted_parquet(IDENTITY_PATH)
    con.register("identity_raw", df_identity)

    if user_role == "GM" and user_studio:
        # studio comes from the trusted USER_ACCOUNTS dict; validate before inlining because
        # DuckDB cannot bind parameters inside a CREATE VIEW statement.
        if not re.fullmatch(r"[A-Za-z0-9_]+", str(user_studio)):
            raise ValueError("Invalid studio identifier.")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW features AS SELECT * FROM read_parquet('{FEATURES_PATH}') WHERE home_studio_id = '{user_studio}'")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW identity AS SELECT * FROM identity_raw WHERE hashed_member_id IN (SELECT hashed_member_id FROM features)")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW scores AS SELECT * FROM read_parquet('{SCORES_PATH}') WHERE hashed_member_id IN (SELECT hashed_member_id FROM features)")
    else:
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW features AS SELECT * FROM read_parquet('{FEATURES_PATH}')")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW identity AS SELECT * FROM identity_raw")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW scores AS SELECT * FROM read_parquet('{SCORES_PATH}')")

    if os.path.exists(GROUND_TRUTH_PATH):
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW ground_truth AS SELECT * FROM read_parquet('{GROUND_TRUTH_PATH}')")
    return con

def run_secure_query(query: str, params=()) -> pd.DataFrame:
    """Execute a query against the per-session, access-scoped views. GM row-level isolation is
    enforced by the view definitions in get_scoped_connection(), so the query runs verbatim --
    no fragile string substitution of table names."""
    con = get_scoped_connection()
    return con.execute(query, params).df()

# ==============================================================================
# SIDEBAR NAVIGATION
# ==============================================================================
st.sidebar.markdown(f"**User:** `{st.session_state.username}`")
st.sidebar.markdown(f"**Role:** `{user_role}`" + (f" (`{user_studio}`)" if user_studio else ""))

view_selection = st.sidebar.radio(
    "Select Dashboard View",
    ["Studio Overview", "Member Detail", "Intervention Queue & A/B Results"]
)

if st.sidebar.button("Log Out", key="logout_btn"):
    logout()

# Load latest score snapshot date
latest_date_df = run_secure_query("SELECT MAX(score_date) as latest FROM scores")
if latest_date_df.empty or latest_date_df["latest"].iloc[0] is None:
    st.error("No churn scores found in the database. Please run pipeline scoring first.")
    st.stop()
latest_snapshot_date = latest_date_df["latest"].iloc[0]

# ==============================================================================
# VIEW 1: STUDIO OVERVIEW
# ==============================================================================
if view_selection == "Studio Overview":
    st.title("🔥 Studio Overview Dashboard")
    st.subheader(f"Snapshot Date: {latest_snapshot_date}")
    st.markdown("---")
    
    # 1. Load summary data
    metrics_query = """
        SELECT 
            COUNT(DISTINCT s.hashed_member_id) as total_active,
            SUM(CASE WHEN s.risk_tier IN ('Medium', 'High', 'Critical') THEN 1 ELSE 0 END) as total_at_risk,
            SUM(s.churn_probability) as weekly_forecast,
            SUM(CASE WHEN s.churn_probability >= 0.50 THEN f.monthly_price ELSE 0 END) as mrr_at_risk
        FROM scores s
        JOIN features f ON s.hashed_member_id = f.hashed_member_id AND s.score_date = f.date_day
        WHERE s.score_date = ?
    """
    metrics_df = run_secure_query(metrics_query, (latest_snapshot_date,))
    
    total_active = metrics_df["total_active"].iloc[0]
    total_at_risk = metrics_df["total_at_risk"].iloc[0]
    weekly_forecast = metrics_df["weekly_forecast"].iloc[0]
    mrr_at_risk = metrics_df["mrr_at_risk"].iloc[0]
    
    # Render KPI Cards in columns
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Total Active Members</div>
            <div class="metric-value">{total_active:,}</div>
            <div class="metric-delta delta-down">✓ Managed Slices</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        risk_pct = (total_at_risk / total_active) if total_active > 0 else 0
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Members At-Risk (Med-Critical)</div>
            <div class="metric-value">{total_at_risk:,}</div>
            <div class="metric-delta delta-up">{risk_pct:.1%} of active</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col3:
        forecast_pct = (weekly_forecast / total_active) if total_active > 0 else 0
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Weekly Churn Forecast</div>
            <div class="metric-value">{weekly_forecast:.1f}</div>
            <div class="metric-delta delta-up">{forecast_pct:.1%} expected loss</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col4:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">MRR Value At-Risk (Score >= 50%)</div>
            <div class="metric-value">${mrr_at_risk:,.2f}</div>
            <div class="metric-delta delta-up">Requires Immediate Action</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown("### Risk Analytics & Distribution")
    
    # 2. Risk Tier Distribution
    distribution_query = """
        SELECT risk_tier, COUNT(*) as count 
        FROM scores 
        WHERE score_date = ? 
        GROUP BY risk_tier
    """
    dist_df = run_secure_query(distribution_query, (latest_snapshot_date,))
    
    # Reorder risk tiers logically
    tier_order = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    dist_df["order"] = dist_df["risk_tier"].map(tier_order)
    dist_df = dist_df.sort_values("order")
    
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        # Plotly Pie Chart
        fig_pie = px.pie(
            dist_df, 
            values='count', 
            names='risk_tier',
            title='Proportional Churn Risk Tiers',
            color='risk_tier',
            color_discrete_map={
                'Low': '#10B981',      # Green
                'Medium': '#FBBF24',   # Yellow
                'High': '#F97316',     # Orange
                'Critical': '#EF4444'  # Red
            },
            hole=0.4
        )
        fig_pie.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#E2E8F0',
            legend_title_text='Risk Tier'
        )
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with chart_col2:
        # Histogram of probabilities
        prob_df = run_secure_query("SELECT churn_probability FROM scores WHERE score_date = ?", (latest_snapshot_date,))
        fig_hist = px.histogram(
            prob_df, 
            x="churn_probability", 
            nbins=30,
            title="Distribution of Member Churn Probabilities",
            labels={'churn_probability': 'Predicted Churn Risk Score'},
            color_discrete_sequence=['#5F57FF']
        )
        fig_hist.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#E2E8F0',
            xaxis_tickformat='.0%'
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        
    # 3. Studio Breakdown (only relevant for Admins to view comparative performance)
    if user_role == "Admin":
        st.markdown("### Home Studio Risk Breakdown")
        studio_query = """
            SELECT 
                f.home_studio_id as studio,
                COUNT(DISTINCT s.hashed_member_id) as active_members,
                SUM(CASE WHEN s.risk_tier = 'Critical' THEN 1 ELSE 0 END) as critical_count,
                SUM(CASE WHEN s.risk_tier = 'High' THEN 1 ELSE 0 END) as high_count,
                SUM(CASE WHEN s.risk_tier = 'Medium' THEN 1 ELSE 0 END) as medium_count,
                ROUND(AVG(s.churn_probability) * 100, 2) as avg_risk_pct,
                ROUND(SUM(s.churn_probability), 1) as expected_churn_count
            FROM scores s
            JOIN features f ON s.hashed_member_id = f.hashed_member_id AND s.score_date = f.date_day
            WHERE s.score_date = ?
            GROUP BY f.home_studio_id
            ORDER BY expected_churn_count DESC
        """
        studio_breakdown = run_secure_query(studio_query, (latest_snapshot_date,))
        
        # Color formatting
        st.dataframe(
            studio_breakdown.style.background_gradient(subset=['avg_risk_pct', 'expected_churn_count'], cmap='OrRd'),
            use_container_width=True,
            hide_index=True
        )

# ==============================================================================
# VIEW 2: MEMBER DETAIL
# ==============================================================================
elif view_selection == "Member Detail":
    st.title("🔍 Member Diagnostic Profile")
    st.markdown("---")
    
    # 1. Fetch available members to choose from (based on studio access)
    members_list_query = """
        SELECT i.member_id, i.name 
        FROM identity i
        ORDER BY i.name
    """
    members_list = run_secure_query(members_list_query)
    
    if members_list.empty:
        st.warning("No accessible members found for your home studio.")
        st.stop()
        
    member_options = [f"{row['name']} ({row['member_id']})" for _, row in members_list.iterrows()]
    selected_member_str = st.selectbox("Search & Select Member Profile:", member_options)
    
    selected_id = selected_member_str.split("(")[-1].replace(")", "")
    
    # 2. Get member core info
    member_info_query = """
        SELECT 
            i.name, i.email, i.phone, i.member_id, i.hashed_member_id,
            f.gender, f.home_studio_id, f.membership_tier, f.monthly_price, f.tenure_days,
            s.churn_probability, s.risk_tier, f.date_day
        FROM identity i
        JOIN features f ON i.hashed_member_id = f.hashed_member_id
        JOIN scores s ON i.hashed_member_id = s.hashed_member_id AND f.date_day = s.score_date
        WHERE i.member_id = ? AND s.score_date = ?
    """
    member_df = run_secure_query(member_info_query, (selected_id, latest_snapshot_date))
    
    if member_df.empty:
        st.error("Error loading selected member's profile.")
        st.stop()
        
    member = member_df.iloc[0]
    hashed_id = member["hashed_member_id"]
    
    # Render Diagnostic Grid
    m_col1, m_col2 = st.columns([1, 2])
    
    with m_col1:
        st.markdown("### Profile Card")
        # Custom formatted profile card
        st.markdown(f"""
        <div class="card">
            <h4>{member['name']}</h4>
            <hr>
            <p><b>Member ID:</b> {member['member_id']}</p>
            <p><b>Home Studio:</b> {member['home_studio_id']}</p>
            <p><b>Membership:</b> {member['membership_tier']} (${member['monthly_price']:.2f}/mo)</p>
            <p><b>Tenure:</b> {member['tenure_days']:,} days</p>
            <p><b>Email:</b> {member['email']}</p>
            <p><b>Phone:</b> {member['phone']}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Risk gauge chart
        prob = member["churn_probability"]
        tier = member["risk_tier"]
        
        # Color coding
        if tier == "Low": color = "#10B981"
        elif tier == "Medium": color = "#FBBF24"
        elif tier == "High": color = "#F97316"
        else: color = "#EF4444"
        
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = prob * 100,
            domain = {'x': [0, 1], 'y': [0, 1]},
            title = {'text': f"Risk Score ({tier})", 'font': {'size': 18, 'color': '#FFFFFF'}},
            number = {'suffix': "%", 'font': {'color': color, 'size': 36}},
            gauge = {
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#8A8F98"},
                'bar': {'color': color},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "rgba(255,255,255,0.08)",
                'steps': [
                    {'range': [0, 20], 'color': 'rgba(16, 185, 129, 0.15)'},
                    {'range': [20, 50], 'color': 'rgba(251, 191, 36, 0.15)'},
                    {'range': [50, 85], 'color': 'rgba(249, 115, 22, 0.15)'},
                    {'range': [85, 100], 'color': 'rgba(239, 68, 68, 0.15)'}
                ],
            }
        ))
        
        fig_gauge.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font={'color': '#FFFFFF'},
            height=200,
            margin=dict(l=20, r=20, t=30, b=10)
        )
        st.plotly_chart(fig_gauge, use_container_width=True)
        
    with m_col2:
        st.markdown("### Risk Explanation & Diagnostics")
        
        # Generate explanations (logic from score_members.py)
        # We'll pull the raw feature row for this member on this date to run rules
        raw_feat_query = "SELECT * FROM features WHERE hashed_member_id = ? AND date_day = ?"
        raw_feat_df = run_secure_query(raw_feat_query, (hashed_id, latest_snapshot_date))
        
        explanations = []
        if not raw_feat_df.empty:
            row = raw_feat_df.iloc[0]
            if row['last_recurring_payment_failed']:
                explanations.append("💳 **Recurring membership payment failed**: Auto-cancellation triggers exactly 14 days after payment failure.")
            if row['failed_payments_count_30d'] > 0:
                explanations.append(f"⚠️ **Multiple payment failures**: Had {row['failed_payments_count_30d']} failed transaction events in the last 30 days.")
            if row['has_cancellation_query_30d']:
                explanations.append("💬 **Chat cancellation search**: Flagged inquiry in AI Coach chat regarding account freezing or cancellation options.")
            if row['days_since_last_session'] > 14:
                explanations.append(f"💤 **Extended workout inactivity**: Member has not booked/attended a class in {row['days_since_last_session']} days.")
            if row['sessions_attended_30d'] < 3:
                explanations.append(f"📉 **Severe drop-off**: Only {row['sessions_attended_30d']} sauna bookings attended in the past 30 days.")
            if row['app_logins_30d'] < 4:
                explanations.append(f"📱 **Low app engagement**: Only {row['app_logins_30d']} app logins in the last month.")
            if row['sessions_booked_30d'] > 0 and row['attendance_rate_30d'] < 0.50:
                explanations.append(f"🚫 **Sauna no-show pattern**: Booked {row['sessions_booked_30d']} sessions but attended only {row['attendance_rate_30d']:.0%}.")
                
        if not explanations:
            explanations.append("📈 **General engagement decay**: Gradual decrease in email opens, click rates, and weekly app logins.")
            
        st.markdown('<div class="card">', unsafe_allow_html=True)
        for exp in explanations:
            st.write(exp)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Interactive Plotly chart showing historical booking/app logins
        st.markdown("#### Historical Activity Trends (Last 90 Days)")
        
        history_query = """
            SELECT date_day, sessions_attended_30d, app_logins_30d, coach_chat_count_30d
            FROM features
            WHERE hashed_member_id = ?
            ORDER BY date_day
        """
        history_df = run_secure_query(history_query, (hashed_id,))
        
        if not history_df.empty:
            history_df = history_df.tail(90)  # limit to last 90 snapshot days
            fig_trend = px.line(
                history_df,
                x='date_day',
                y=['sessions_attended_30d', 'app_logins_30d', 'coach_chat_count_30d'],
                title='30-Day Rolling Behavior Metric History',
                labels={'value': 'Count / Frequency', 'date_day': 'Date', 'variable': 'Metric'},
                color_discrete_sequence=['#5F57FF', '#10B981', '#FF9F1C']
            )
            fig_trend.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#E2E8F0',
                legend_title_text='Metric'
            )
            st.plotly_chart(fig_trend, use_container_width=True)
            
    # 4. Intervention History Table
    st.markdown("### Past Campaign & Call Interventions")
    
    if os.path.exists(AUDIT_LOG_PATH):
        audit_all = pd.read_parquet(AUDIT_LOG_PATH)
        # Filter for this member
        member_audit = audit_all[audit_all["hashed_member_id"] == hashed_id].copy()
        
        if member_audit.empty:
            st.info("No recorded interventions found for this member.")
        else:
            member_audit = member_audit.sort_values("sent_at", ascending=False)
            st.dataframe(
                member_audit[["sent_at", "action_type", "status", "message_body", "error_message"]],
                use_container_width=True,
                hide_index=True
            )
    else:
        st.info("No intervention audit logs exist yet.")

# ==============================================================================
# VIEW 3: INTERVENTION QUEUE & A/B RESULTS
# ==============================================================================
else:
    st.title("📋 Campaign Queue & A/B Validation")
    st.markdown("---")
    
    queue_tab, ab_tab = st.tabs(["Active Intervention Queue", "A/B Test Impact Measurements"])
    
    with queue_tab:
        st.markdown("### Current Queue Action Tasks")
        st.write("Outlined actions that require staff outreach or automated campaign reviews.")
        
        if os.path.exists(QUEUE_PATH):
            queue_all = pd.read_parquet(QUEUE_PATH)
            
            # Resolve GM row-level filter on Home Studio
            if user_role == "GM" and user_studio:
                queue_df = queue_all[queue_all["home_studio_id"] == user_studio].copy()
            else:
                queue_df = queue_all.copy()
                
            if queue_df.empty:
                st.info("No queued actions currently exist.")
            else:
                # Add status filter
                status_filter = st.selectbox("Filter by Queue Status:", ["All", "Pending", "Sent", "DryRun", "Holdout", "RateLimited"])
                if status_filter != "All":
                    filtered_q = queue_df[queue_df["status"] == status_filter].copy()
                else:
                    filtered_q = queue_df.copy()
                    
                # Format scores as percentage
                filtered_q["risk_score"] = filtered_q["risk_score"].apply(lambda x: f"{x:.1%}")
                
                # Show dataframe
                st.dataframe(
                    filtered_q[["action_id", "member_id", "risk_score", "risk_tier", "action_type", "action_details", "status", "created_at"]],
                    use_container_width=True,
                    hide_index=True
                )
                
                # Manual completion form for GM Phone Calls
                st.markdown("#### Complete Queued Phone Outreach Call")
                pending_calls = filtered_q[(filtered_q["action_type"] == "Call") & (filtered_q["status"] == "Pending")].copy()
                
                if pending_calls.empty:
                    st.info("No pending phone calls found in queue.")
                else:
                    call_options = [f"{row['member_id']} - Action: {row['action_id']}" for _, row in pending_calls.iterrows()]
                    selected_call = st.selectbox("Select Call Action to Update:", call_options)
                    
                    selected_act_id = selected_call.split("- Action: ")[-1].strip()
                    selected_mb_id = selected_call.split("- Action: ")[0].strip()
                    
                    notes = st.text_area("Outreach Notes / Outcome:", placeholder="E.g., Left voicemail. Or: Resolved payment issues, updated CC on file.")
                    
                    if st.button("Mark Call as Completed"):
                        # Read queue and audit files, update and save
                        q_df = pd.read_parquet(QUEUE_PATH)
                        a_df = pd.read_parquet(AUDIT_LOG_PATH)
                        
                        # Find indices
                        q_idx = q_df[q_df["action_id"] == selected_act_id].index
                        if len(q_idx) > 0:
                            q_df.loc[q_idx[0], "status"] = "Sent"
                            q_df.loc[q_idx[0], "processed_at"] = datetime.datetime.now()
                            q_df.to_parquet(QUEUE_PATH, index=False)
                            
                            # Append to audit log
                            new_audit_rec = {
                                "audit_id": f"AU{int(datetime.datetime.now().timestamp())}",
                                "member_id": selected_mb_id,
                                "hashed_member_id": q_df.loc[q_idx[0], "hashed_member_id"],
                                "sent_at": datetime.datetime.now(),
                                "action_type": "Call",
                                "status": "Sent",
                                "why_score": f"Completed outreach call | Outcome: {notes}",
                                "message_body": f"Notes: {notes}",
                                "error_message": ""
                            }
                            new_a_df = pd.DataFrame([new_audit_rec])
                            a_df = pd.concat([a_df, new_a_df], ignore_index=True)
                            a_df.to_parquet(AUDIT_LOG_PATH, index=False)
                            
                            st.success(f"Successfully updated task {selected_act_id}. Call marked as completed!")
                            st.rerun()
        else:
            st.info("No queue log exists yet. Run the rules engine first.")
            
    with ab_tab:
        st.markdown("### A/B Test Holdout Performance Impact")
        st.warning(
            "**Illustrative wireframe — not a measured result.** In this demo, interventions run in "
            "dry-run and the synthetic churn outcomes are pre-determined, so treatment cannot causally "
            "change them. Real lift requires *live* treatment measured forward over time against the "
            "deterministic 10% holdout. The layout below shows how that measurement will be reported."
        )

        if os.path.exists(GROUND_TRUTH_PATH) and os.path.exists(QUEUE_PATH):
            gt_df = pd.read_parquet(GROUND_TRUTH_PATH)
            q_df = pd.read_parquet(QUEUE_PATH)

            # Respect row-level access: a GM only ever measures their own studio.
            if user_role == "GM" and user_studio:
                q_df = q_df[q_df["home_studio_id"] == user_studio].copy()

            # NOTE: ground_truth has no `status` column, so the merge keeps the queue's `status`
            # (no `_x` suffix). The previous code referenced `status_x` and would KeyError on any
            # real queue data.
            merged_ab = q_df.merge(gt_df, on="member_id")
            holdout_group = merged_ab[merged_ab["status"] == "Holdout"].drop_duplicates(subset=["member_id"])
            treatment_group = merged_ab[merged_ab["status"].isin(["Sent", "DryRun", "Pending"])].drop_duplicates(subset=["member_id"])

            n_holdout = len(holdout_group)
            n_treat = len(treatment_group)

            if n_holdout == 0 or n_treat == 0:
                # No real cohorts yet -> clearly-labelled PLACEHOLDER values, purely to convey layout.
                is_mock = True
                n_holdout, n_treat, churn_holdout, churn_treat = 374, 3366, 86, 403
                st.caption("⚠️ PLACEHOLDER values below (no queued cohorts for this scope yet) — illustrative only, not from data.")
            else:
                is_mock = False
                churn_holdout = int(holdout_group["churned"].sum())
                churn_treat = int(treatment_group["churned"].sum())
                st.caption("Figures below are computed from the synthetic data; in this demo the gap is expected to be ~random (no causal effect).")

            rate_holdout = (churn_holdout / n_holdout) if n_holdout > 0 else 0
            rate_treat = (churn_treat / n_treat) if n_treat > 0 else 0
            lift = rate_holdout - rate_treat
            lift_pct = (lift / rate_holdout) if rate_holdout > 0 else 0

            col_ab1, col_ab2, col_ab3 = st.columns(3)

            with col_ab1:
                st.markdown(f"""
                <div class="card">
                    <div class="metric-title">Treatment Churn Rate (Notified)</div>
                    <div class="metric-value">{rate_treat:.1%}</div>
                    <div class="metric-delta delta-down">Sample Size: {n_treat:,}</div>
                </div>
                """, unsafe_allow_html=True)

            with col_ab2:
                st.markdown(f"""
                <div class="card">
                    <div class="metric-title">Holdout Churn Rate (Control)</div>
                    <div class="metric-value">{rate_holdout:.1%}</div>
                    <div class="metric-delta delta-up">Sample Size: {n_holdout:,}</div>
                </div>
                """, unsafe_allow_html=True)

            with col_ab3:
                st.markdown(f"""
                <div class="card">
                    <div class="metric-title">Absolute Churn Reduction</div>
                    <div class="metric-value">{lift:.1%}</div>
                    <div class="metric-delta delta-down">-{lift_pct:.1%} relative reduction</div>
                </div>
                """, unsafe_allow_html=True)

            chart_title = "Churn Rates Comparison (PLACEHOLDER)" if is_mock else "Churn Rates Comparison (synthetic, ~random)"
            fig_ab = go.Figure(data=[
                go.Bar(
                    x=['Treatment Group (Notified)', 'Holdout Group (Control)'],
                    y=[rate_treat * 100, rate_holdout * 100],
                    marker_color=['#10B981', '#EF4444'],
                    text=[f"{rate_treat:.1%}", f"{rate_holdout:.1%}"],
                    textposition='auto',
                )
            ])
            fig_ab.update_layout(
                title=chart_title,
                yaxis_title="Churn Rate (%)",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#E2E8F0',
            )
            st.plotly_chart(fig_ab, use_container_width=True)
        else:
            st.info("Data models required for A/B testing measurements are not loaded.")
