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

# Custom CSS for HOTWORX Athletic Branding (High-Contrast & Energetic Style)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=Oswald:wght@500;600;700&display=swap');

    /* Main container background - Stark clean white/light-gray layout */
    .stApp {
        background-color: #F9FAFB;
        color: #1F2937;
        font-family: 'Montserrat', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Reset all standard text in light panels to dark grey for maximum contrast */
    .stApp p, 
    .stApp li, 
    .stApp label,
    .stApp table,
    .stApp td,
    .stApp th,
    .stApp span:not(.priority-badge):not(.trend-arrow):not(.stMetricDelta):not(.funnel-segment), 
    .stApp div[data-testid="stMarkdownContainer"] p,
    .stApp div[data-testid="stMarkdownContainer"] li,
    .stApp div[data-testid="stMarkdownContainer"] span:not(.priority-badge) {
        color: #1F2937 !important;
    }
    
    /* Sidebar styling - Dark overlay block to make text pop */
    section[data-testid="stSidebar"] {
        background-color: #0F172A !important;
        border-right: 1px solid rgba(0, 0, 0, 0.1);
    }
    
    /* Sidebar text override - Force white/light-gray text inside the dark sidebar */
    section[data-testid="stSidebar"] p, 
    section[data-testid="stSidebar"] li, 
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] li,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] span {
        color: #F3F4F6 !important;
        font-family: 'Montserrat', sans-serif;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #FFFFFF !important;
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase !important;
    }
    
    /* Input inputs, dropdowns */
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
        background-color: #FFFFFF !important;
        color: #1F2937 !important;
        border: 1px solid #D1D5DB !important;
        border-radius: 8px !important;
    }
    input {
        color: #1F2937 !important;
        -webkit-text-fill-color: #1F2937 !important;
    }
    div[data-baseweb="select"] * {
        color: #1F2937 !important;
    }
    div[data-baseweb="popover"] * {
        color: #1F2937 !important;
    }
    div[data-baseweb="popover"] ul {
        background-color: #FFFFFF !important;
    }
    
    /* Custom Card - Stark white with light border & clean shadow */
    .card {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: border-color 0.2s ease-out, transform 0.2s ease-out;
        color: #1F2937;
    }
    .card:hover {
        border-color: #F27435;
        transform: translateY(-2px);
    }
    .card * {
        color: #1F2937 !important;
    }
    
    /* Stat Metrics */
    .metric-title {
        font-size: 12px;
        color: #6B7280 !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }
    .metric-value {
        font-size: 32px;
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase;
        font-weight: 700;
        color: #111827 !important;
        margin-top: 6px;
    }
    .metric-delta {
        font-size: 13px;
        margin-top: 4px;
        font-weight: 600;
    }
    .delta-up { color: #DC2626 !important; }
    .delta-down { color: #16A34A !important; }
    
    /* Fiery Orange-Red Gradient CTA Buttons */
    .stButton>button {
        background: linear-gradient(135deg, #F27435 0%, #D94126 100%) !important;
        color: #FFFFFF !important;
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
        font-weight: 600 !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 10px 24px !important;
        box-shadow: 0 4px 14px rgba(242, 116, 53, 0.3) !important;
        transition: transform 0.16s cubic-bezier(0.23, 1, 0.32, 1), opacity 0.2s !important;
    }
    .stButton>button:hover {
        opacity: 0.92 !important;
        color: #FFFFFF !important;
    }
    .stButton>button:active {
        transform: scale(0.97) !important;
    }
    
    /* Secondary/Outline Buttons */
    .stButton>button[secondary="true"] {
        background: transparent !important;
        color: #4B5563 !important;
        border: 1px solid #D1D5DB !important;
        box-shadow: none !important;
    }
    .stButton>button[secondary="true"]:hover {
        background-color: #F3F4F6 !important;
    }
    
    /* Heading styling - Oswald bold, heavy, and capitalized */
    h1, h2, h3, h4, h5, h6 {
        color: #111827 !important;
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px !important;
    }
    
    /* Divider */
    hr {
        border-color: #E5E7EB !important;
    }
    
    /* Action Card — priority-aware styling */
    .action-card {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        transition: border-color 0.2s ease-out, transform 0.2s ease-out;
        position: relative;
        color: #1F2937;
    }
    .action-card:hover {
        border-color: #F27435;
        transform: translateY(-2px);
    }
    .action-card.critical {
        border-left: 5px solid #EF4444;
    }
    .action-card.high {
        border-left: 5px solid #F97316;
    }
    .action-card.medium {
        border-left: 5px solid #FBBF24;
    }
    
    /* Priority Badge */
    .priority-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }
    .badge-critical { background: rgba(239, 68, 68, 0.1) !important; color: #EF4444 !important; }
    .badge-high { background: rgba(249, 115, 22, 0.1) !important; color: #F97316 !important; }
    .badge-medium { background: rgba(251, 191, 36, 0.1) !important; color: #D97706 !important; }
    .badge-low { background: rgba(16, 185, 129, 0.1) !important; color: #10B981 !important; }

    /* Info tooltip icon shown next to a metric, stat, or chart header */
    .info-icon {
        font-size: 12px;
        color: #6B7280;
        cursor: help;
        margin-left: 5px;
        font-weight: 400;
        vertical-align: middle;
    }
    .info-icon:hover { color: #F27435; }
    
    /* Celebration Banner - Orange-Red Heat Vibe */
    .celebration-banner {
        background: linear-gradient(135deg, rgba(242, 116, 53, 0.08), rgba(217, 65, 38, 0.08));
        border: 1px solid rgba(242, 116, 53, 0.2);
        border-radius: 12px;
        padding: 16px 24px;
        margin-bottom: 20px;
        text-align: center;
    }
    .celebration-banner .emoji { font-size: 24px; }
    .celebration-banner .text {
        color: #D94126 !important;
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase !important;
        font-weight: 600;
        font-size: 16px;
        letter-spacing: 0.5px;
    }
    
    /* Lifecycle Funnel Bar */
    .funnel-bar {
        display: flex;
        height: 32px;
        border-radius: 8px;
        overflow: hidden;
        margin: 8px 0;
    }
    .funnel-segment {
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 600;
        color: #FFFFFF !important;
        min-width: 2%;
        transition: flex 0.3s ease;
    }
    
    /* Health Score Ring */
    .health-score-container {
        text-align: center;
        padding: 16px;
    }
    .health-score-label {
        font-size: 12px;
        color: #6B7280 !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-top: 8px;
    }
    
    /* WoW Trend Delta */
    .trend-up { color: #DC2626 !important; }
    .trend-down { color: #16A34A !important; }
    .trend-flat { color: #6B7280 !important; }
    .trend-arrow { font-size: 14px; margin-right: 4px; }
    
    /* Style tabs to match Oswald typography */
    button[data-baseweb="tab"] {
        font-family: 'Oswald', sans-serif !important;
        text-transform: uppercase !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        color: #4B5563 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #D94126 !important;
        border-bottom-color: #D94126 !important;
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
LIFECYCLE_PATH = os.path.join(DATA_DIR, "member_lifecycle.parquet")
OUTCOMES_PATH = os.path.join(DATA_DIR, "intervention_outcomes.parquet")
ENGAGEMENT_PATH = os.path.join(DATA_DIR, "member_engagement.parquet")


def info(text: str) -> str:
    """Return a small ⓘ tooltip icon (native hover) explaining a metric, stat, or graph."""
    safe = str(text).replace('"', "'").replace("\n", " ")
    return f'<span class="info-icon" title="{safe}">&#9432;</span>'


def h_info(title: str, text: str, level: str = "###"):
    """Render a markdown section header followed by an ⓘ tooltip."""
    st.markdown(f"{level} {title} {info(text)}", unsafe_allow_html=True)


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

# --- Admin "View as Studio" oversight lens (selector rendered in the sidebar below) ----------
# Admin already sees ALL data, so this lens grants NO new access; it scopes the operational views
# to one GM's studio and is logged for auditability. effective_studio / studio_scoped are read
# (late-bound) by get_scoped_connection and every per-view filter; GM write-actions are disabled.
viewing_studio = None
effective_studio = user_studio if user_role == "GM" else None
studio_scoped = effective_studio is not None
oversight_readonly = False  # True only when an Admin is viewing as a studio

@st.cache_data(show_spinner=False)
def _list_studios():
    try:
        vals = pd.read_parquet(FEATURES_PATH, columns=["home_studio_id"])["home_studio_id"].dropna().unique().tolist()
        return sorted(str(v) for v in vals)
    except Exception:
        return []

def _log_oversight_access(admin_user, studio):
    """Record an Admin viewing a studio's GM lens. Oversight access is itself auditable; logged
    once per (admin, studio) change rather than on every Streamlit rerun."""
    marker = f"{admin_user}:{studio}"
    if st.session_state.get("_last_oversight") == marker:
        return
    st.session_state["_last_oversight"] = marker
    path = os.path.join(DATA_DIR, "admin_oversight_log.parquet")
    rec = pd.DataFrame([{"accessed_at": datetime.datetime.now(), "admin_user": admin_user, "viewed_studio": studio}])
    if os.path.exists(path):
        rec = pd.concat([pd.read_parquet(path), rec], ignore_index=True)
    rec.to_parquet(path, index=False)

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

    if studio_scoped and effective_studio:
        # effective_studio is a GM's own studio OR an Admin's "view as" selection. Validate before
        # inlining because DuckDB cannot bind parameters inside a CREATE VIEW statement.
        if not re.fullmatch(r"[A-Za-z0-9_]+", str(effective_studio)):
            raise ValueError("Invalid studio identifier.")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW features AS SELECT * FROM read_parquet('{FEATURES_PATH}') WHERE home_studio_id = '{effective_studio}'")
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

# --- Admin oversight lens: "View as Studio" -------------------------------------------------
if user_role == "Admin":
    _opts = ["All studios (admin)"] + _list_studios()
    _sel = st.sidebar.selectbox(
        "👁 View as Studio (oversight)", _opts, index=0,
        help="See exactly what a studio's GM sees. No new data access (admins already see "
             "everything); GM actions are read-only and the access is logged.",
    )
    viewing_studio = None if _sel.startswith("All studios") else _sel
    if viewing_studio:
        effective_studio = viewing_studio
        studio_scoped = True
        oversight_readonly = True
        _log_oversight_access(st.session_state.username, viewing_studio)
        st.sidebar.caption(f"👁 Viewing **{viewing_studio}** as its GM would · read-only · logged")

# Determine navigation options: GMs see "My Studio Today" first
if user_role == "GM":
    nav_options = ["My Studio Today", "Member Detail", "Intervention Queue & A/B Results", "Studio Overview"]
else:
    nav_options = ["Studio Overview", "My Studio Today", "Member Detail", "Intervention Queue & A/B Results", "Revenue Impact", "Model Health", "Win-Back Leaderboard"]

view_selection = st.sidebar.radio(
    "Select Dashboard View",
    nav_options
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
# VIEW 0: MY STUDIO TODAY (GM-focused action view)
# ==============================================================================
if view_selection == "My Studio Today":
    st.title("🔥 My Studio Today")
    st.subheader(f"Snapshot: {latest_snapshot_date}")
    st.markdown("---")

    # Win-back rank badge (motivation / year-end bonus race)
    if studio_scoped and effective_studio:
        try:
            import winback_leaderboard as wbl
            _rk = wbl.get_studio_rank(effective_studio)
            if _rk:
                _medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(_rk["rank"], "🏆")
                st.markdown(
                    f'<div class="celebration-banner"><span class="emoji">{_medal}</span> '
                    f'<span class="text">Win-back rank #{_rk["rank"]} of {_rk["of"]} · '
                    f'{_rk["reactivation_rate"]:.0%} reactivation · ${_rk["bonus_award"]:,.0f} bonus pace</span>'
                    f'{info("Studio rank and year-end bonus allocation pacing based on the reactivation rate of cancelled members.")}</div>',
                    unsafe_allow_html=True,
                )
        except Exception:
            pass

    # ---- Celebration Banner: members who moved from at_risk stages ----
    if os.path.exists(LIFECYCLE_PATH):
        lifecycle_df = pd.read_parquet(LIFECYCLE_PATH)
        if studio_scoped and effective_studio:
            lifecycle_df = lifecycle_df[lifecycle_df["home_studio_id"] == effective_studio]

        re_engaged_count = len(lifecycle_df[
            (lifecycle_df["previous_stage"].isin(["at_risk", "lapsed"])) &
            (lifecycle_df["stage"] == "engaged")
        ])
        if re_engaged_count > 0:
            st.markdown(f"""
            <div class="celebration-banner">
                <span class="emoji">🎉</span>
                <span class="text">{re_engaged_count} at-risk member{'s' if re_engaged_count != 1 else ''} re-engaged this period! Great work.</span>
                {info("Count of at-risk or lapsed members who successfully re-engaged (attended/booked a session) during this period.")}
            </div>
            """, unsafe_allow_html=True)

    # ---- Studio Health Score + WoW KPI Trends ----
    health_col, kpi_col = st.columns([1, 3])

    # Compute health metrics
    metrics_now = run_secure_query("""
        SELECT
            COUNT(DISTINCT s.hashed_member_id) as total_active,
            SUM(CASE WHEN s.risk_tier IN ('Medium', 'High', 'Critical') THEN 1 ELSE 0 END) as at_risk,
            SUM(s.churn_probability) as weekly_forecast,
            SUM(CASE WHEN s.churn_probability >= 0.50 THEN f.monthly_price ELSE 0 END) as mrr_at_risk
        FROM scores s
        JOIN features f ON s.hashed_member_id = f.hashed_member_id AND s.score_date = f.date_day
        WHERE s.score_date = ?
    """, (latest_snapshot_date,))

    total_active = int(metrics_now["total_active"].iloc[0]) if not metrics_now.empty else 0
    at_risk_now = int(metrics_now["at_risk"].iloc[0]) if not metrics_now.empty else 0
    forecast_now = float(metrics_now["weekly_forecast"].iloc[0]) if not metrics_now.empty else 0
    mrr_at_risk_now = float(metrics_now["mrr_at_risk"].iloc[0]) if not metrics_now.empty else 0

    # Retention rate component
    retention_rate = ((total_active - at_risk_now) / total_active * 100) if total_active > 0 else 100

    # Outcome success rate component
    outcome_success = 0.0
    if os.path.exists(OUTCOMES_PATH):
        try:
            outcomes_df = pd.read_parquet(OUTCOMES_PATH)
            if not outcomes_df.empty:
                positive = outcomes_df["outcome_30d"].isin(["re_engaged", "payment_resolved", "still_active"]).sum()
                outcome_success = (positive / len(outcomes_df)) * 100
        except Exception:
            pass

    # Health Score = retention_rate * 0.5 + outcome_success * 0.3 + attendance_component * 0.2
    attendance_component = min(100, retention_rate * 1.1)  # approximate
    health_score = int(retention_rate * 0.5 + outcome_success * 0.3 + attendance_component * 0.2)
    health_score = max(0, min(100, health_score))

    with health_col:
        # Health score color
        if health_score >= 75:
            h_color = "#10B981"
        elif health_score >= 50:
            h_color = "#FBBF24"
        else:
            h_color = "#EF4444"

        st.markdown(f'<div style="text-align: center; font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937;">Studio Health {info("Composite score (0-100) based on active member retention, outreach success rate, and class attendance.")}</div>', unsafe_allow_html=True)
        fig_health = go.Figure(go.Indicator(
            mode="gauge+number",
            value=health_score,
            domain={'x': [0, 1], 'y': [0, 1]},
            number={'font': {'color': h_color, 'size': 42}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#6B7280"},
                'bar': {'color': h_color},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "rgba(0,0,0,0.08)",
                'steps': [
                    {'range': [0, 40], 'color': 'rgba(239, 68, 68, 0.1)'},
                    {'range': [40, 70], 'color': 'rgba(251, 191, 36, 0.1)'},
                    {'range': [70, 100], 'color': 'rgba(16, 185, 129, 0.1)'},
                ],
            }
        ))
        fig_health.update_layout(
            paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
            font={'color': '#1F2937'}, height=180, margin=dict(l=20, r=20, t=10, b=10)
        )
        st.plotly_chart(fig_health, use_container_width=True, theme=None)

    with kpi_col:
        risk_pct = (at_risk_now / total_active * 100) if total_active > 0 else 0
        forecast_pct = (forecast_now / total_active * 100) if total_active > 0 else 0

        tip_active = info("Members active in the latest daily scoring snapshot for this studio.")
        tip_risk = info("Active members the model flags as Medium, High, or Critical churn risk.")
        tip_forecast = info("Expected number of churns in this studio = sum of active members' churn probabilities.")
        tip_mrr = info("Total monthly recurring revenue from members above 50% churn probability in this studio.")

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(f"""
            <div class="card">
                <div class="metric-title">Active Members {tip_active}</div>
                <div class="metric-value">{total_active:,}</div>
            </div>
            """, unsafe_allow_html=True)
        with k2:
            st.markdown(f"""
            <div class="card">
                <div class="metric-title">At-Risk {tip_risk}</div>
                <div class="metric-value">{at_risk_now:,}</div>
                <div class="metric-delta delta-up">{risk_pct:.1f}% of active</div>
            </div>
            """, unsafe_allow_html=True)
        with k3:
            st.markdown(f"""
            <div class="card">
                <div class="metric-title">Churn Forecast {tip_forecast}</div>
                <div class="metric-value">{forecast_now:.0f}</div>
                <div class="metric-delta delta-up">{forecast_pct:.1f}% expected</div>
            </div>
            """, unsafe_allow_html=True)
        with k4:
            st.markdown(f"""
            <div class="card">
                <div class="metric-title">MRR At-Risk {tip_mrr}</div>
                <div class="metric-value">${mrr_at_risk_now:,.0f}</div>
                <div class="metric-delta delta-up">Needs action</div>
            </div>
            """, unsafe_allow_html=True)

    # ---- Lifecycle Funnel ----
    if os.path.exists(LIFECYCLE_PATH):
        h_info("Member Lifecycle Funnel", "Visualizes the breakdown of all members in this studio across lifecycle stages (Onboarding, Engaged, At-Risk, Lapsed, Cancelled, Win-back).")

        # Filter to this studio for GM
        funnel_df = lifecycle_df.copy()
        stage_counts = funnel_df["stage"].value_counts()
        total_funnel = len(funnel_df)

        if total_funnel > 0:
            stage_config = [
                ("onboarding", "#5F57FF", "Onboarding"),
                ("engaged", "#10B981", "Engaged"),
                ("at_risk", "#FBBF24", "At-Risk"),
                ("lapsed", "#F97316", "Lapsed"),
                ("cancelled", "#8A8F98", "Cancelled"),
                ("win_back_eligible", "#A78BFA", "Win-Back"),
                ("win_back_expired", "#4B5563", "Expired"),
            ]

            segments_html = ""
            for stage_key, color, label in stage_config:
                count = stage_counts.get(stage_key, 0)
                pct = (count / total_funnel) * 100
                if pct > 0:
                    segments_html += f'<div class="funnel-segment" style="flex: {pct}; background-color: {color};" title="{label}: {count} ({pct:.1f}%)">{label[:3]} {count}</div>'

            st.markdown(f'<div class="funnel-bar">{segments_html}</div>', unsafe_allow_html=True)

            # Legend
            legend_html = " &nbsp; ".join([
                f'<span style="color:{color}">●</span> {label}: {stage_counts.get(sk, 0)}'
                for sk, color, label in stage_config if stage_counts.get(sk, 0) > 0
            ])
            st.markdown(f'<div style="font-size:12px; color:#4B5563; margin-bottom:16px;">{legend_html}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ---- Priority Action Cards ----
    h_info("🎯 Priority Actions", "List of the highest-risk members in this studio currently needing direct staff outreach or campaign interventions.")
    st.caption("Members requiring immediate attention, ranked by risk score.")

    # Pull top 5 highest-risk members with pending actions or high scores
    top_risk_query = """
        SELECT
            s.hashed_member_id, s.churn_probability, s.risk_tier,
            f.home_studio_id, f.membership_tier, f.monthly_price,
            f.tenure_days, f.days_since_last_session,
            f.sessions_attended_30d, f.app_logins_30d,
            f.last_recurring_payment_failed, f.failed_payments_count_30d,
            f.has_cancellation_query_30d
        FROM scores s
        JOIN features f ON s.hashed_member_id = f.hashed_member_id AND s.score_date = f.date_day
        WHERE s.score_date = ?
          AND s.risk_tier IN ('Medium', 'High', 'Critical')
        ORDER BY s.churn_probability DESC
        LIMIT 5
    """
    top_risk = run_secure_query(top_risk_query, (latest_snapshot_date,))

    if top_risk.empty:
        st.info("No at-risk members found for your studio. Your retention looks strong! 💪")
    else:
        # Resolve identity for these members
        import secure_data
        identity_all = secure_data.read_encrypted_parquet(IDENTITY_PATH)
        top_risk = top_risk.merge(identity_all[["hashed_member_id", "member_id", "name", "email", "phone"]], on="hashed_member_id", how="left")

        for card_idx, (_, member) in enumerate(top_risk.iterrows()):
            tier = member["risk_tier"]
            tier_class = tier.lower() if tier in ("Critical", "High", "Medium") else ""
            badge_class = f"badge-{tier.lower()}" if tier in ("Critical", "High", "Medium", "Low") else "badge-medium"

            # Build explanation
            reasons = []
            if member.get("last_recurring_payment_failed"):
                reasons.append("💳 Payment failed — auto-cancel imminent")
            if member.get("has_cancellation_query_30d"):
                reasons.append("💬 Asked about cancellation in chat")
            if member.get("days_since_last_session", 0) > 14:
                reasons.append(f"💤 No sessions in {int(member['days_since_last_session'])} days")
            if member.get("sessions_attended_30d", 0) < 2:
                reasons.append(f"📉 Only {int(member.get('sessions_attended_30d', 0))} sessions in 30d")
            if not reasons:
                reasons.append("📊 Declining engagement pattern")

            reason_text = reasons[0]  # Primary reason for the card

            name = member.get("name", "Unknown")
            member_id = member.get("member_id", "")
            prob = member.get("churn_probability", 0)
            tenure = int(member.get("tenure_days", 0))
            price = member.get("monthly_price", 0)
            m_tier = member.get("membership_tier", "")

            st.markdown(f"""
            <div class="action-card {tier_class}">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div>
                        <span style="font-size: 18px; font-weight: 700; color: #111827;">{name}</span>
                        <span style="font-size: 13px; color: #4B5563; margin-left: 8px;">{member_id} · {m_tier} · ${price:.0f}/mo</span>
                    </div>
                    <span class="priority-badge {badge_class}">{tier} · {prob:.0%}</span>
                </div>
                <div style="font-size: 14px; color: #374151; margin-bottom: 6px; font-weight: 500;">{reason_text}</div>
                <div style="font-size: 12px; color: #6B7280;">
                    Tenure: {tenure:,}d · Last session: {int(member.get('days_since_last_session', 0))}d ago · Sessions (30d): {int(member.get('sessions_attended_30d', 0))}
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Call outcome logging form
        st.markdown("---")
        st.markdown("#### 📞 Log Outreach Outcome")

        # Let GM pick a member from the action cards
        card_members = [f"{row['name']} ({row['member_id']})" for _, row in top_risk.iterrows()]
        selected_action_member = st.selectbox("Select Member:", card_members, key="action_member_select")
        outcome_type = st.selectbox("Outcome:", ["Resolved — Updated Payment", "Resolved — Rebooked Session", "Voicemail Left", "No Answer", "Refused / Declined", "Rescheduled Follow-Up"], key="outcome_select")
        outcome_notes = st.text_area("Notes:", placeholder="Brief summary of the conversation...", key="outcome_notes")

        if oversight_readonly:
            st.caption("👁 Oversight (read-only) — GM outcome logging is disabled while viewing as a studio.")
        elif st.button("Save Outcome", key="save_outcome_btn"):
            selected_mb_id = selected_action_member.split("(")[-1].replace(")", "").strip()
            if os.path.exists(AUDIT_LOG_PATH):
                a_df = pd.read_parquet(AUDIT_LOG_PATH)
                new_audit_rec = {
                    "audit_id": f"MO{int(datetime.datetime.now().timestamp())}",
                    "member_id": selected_mb_id,
                    "hashed_member_id": top_risk[top_risk["member_id"] == selected_mb_id]["hashed_member_id"].iloc[0] if not top_risk[top_risk["member_id"] == selected_mb_id].empty else "",
                    "sent_at": datetime.datetime.now(),
                    "action_type": "Call",
                    "status": "Sent",
                    "why_score": f"Manual Outreach | Outcome: {outcome_type}",
                    "message_body": f"Outcome: {outcome_type} | Notes: {outcome_notes}",
                    "error_message": ""
                }
                a_df = pd.concat([a_df, pd.DataFrame([new_audit_rec])], ignore_index=True)
                a_df.to_parquet(AUDIT_LOG_PATH, index=False)
                st.success(f"✅ Outcome logged for {selected_action_member}")
                st.rerun()

    # ---- Intervention Effectiveness (from outcome tracker) ----
    if os.path.exists(OUTCOMES_PATH):
        st.markdown("---")
        h_info("📊 Intervention Effectiveness (30-Day Outcomes)", "Measures positive outcomes (re-engaged, payment resolved, or still active) 30 days post-intervention.")

        outcomes_all = pd.read_parquet(OUTCOMES_PATH)
        if not outcomes_all.empty:
            eff_col1, eff_col2 = st.columns(2)

            with eff_col1:
                # By channel
                outcomes_all["positive"] = outcomes_all["outcome_30d"].isin(["re_engaged", "payment_resolved", "still_active"])
                by_channel = outcomes_all.groupby("action_type").agg(
                    total=("audit_id", "count"),
                    positive=("positive", "sum"),
                ).reset_index()
                by_channel["rate"] = (by_channel["positive"] / by_channel["total"] * 100).round(1)

                st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">Positive Outcome Rate by Channel {info("Success rate of members who received interventions on each specific channel (Email, SMS, call, etc.) and remained active or re-engaged.")}</div>', unsafe_allow_html=True)
                fig_channel = px.bar(
                    by_channel, x="action_type", y="rate",
                    labels={"action_type": "Channel", "rate": "Success Rate (%)"},
                    color="rate",
                    color_continuous_scale=["#EF4444", "#FBBF24", "#10B981"],
                    text="rate",
                )
                fig_channel.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig_channel.update_layout(
                    paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
                    font_color='#1F2937', showlegend=False, coloraxis_showscale=False,
                    yaxis_range=[0, 110],
                    margin=dict(t=20)
                )
                fig_channel.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
                fig_channel.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
                st.plotly_chart(fig_channel, use_container_width=True, theme=None)

            with eff_col2:
                # Outcome distribution pie
                outcome_counts = outcomes_all["outcome_30d"].value_counts().reset_index()
                outcome_counts.columns = ["outcome", "count"]

                color_map = {
                    "re_engaged": "#10B981", "payment_resolved": "#5F57FF",
                    "still_active": "#A78BFA", "churned": "#EF4444",
                    "no_response": "#8A8F98"
                }
                st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">30-Day Outcome Distribution {info("Breakdown of member statuses 30 days after receiving an intervention.")}</div>', unsafe_allow_html=True)
                fig_outcomes = px.pie(
                    outcome_counts, values="count", names="outcome",
                    color="outcome", color_discrete_map=color_map, hole=0.4,
                )
                fig_outcomes.update_layout(
                    paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
                    font_color='#1F2937',
                    margin=dict(t=20)
                )
                st.plotly_chart(fig_outcomes, use_container_width=True, theme=None)

# ==============================================================================
# VIEW 1: STUDIO OVERVIEW
# ==============================================================================
elif view_selection == "Studio Overview":
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
    tip_active_all = info("Members active in the latest daily scoring snapshot for this scope.")
    tip_risk_all = info("Active members the model flags as Medium, High, or Critical churn risk.")
    tip_forecast_all = info("Expected number of churns = sum of every active member's churn probability. A statistical expectation, not a headcount.")
    tip_mrr_all = info("Total monthly recurring revenue from members above 50% churn probability — the dollars at stake if they cancel.")

    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Total Active Members {tip_active_all}</div>
            <div class="metric-value">{total_active:,}</div>
            <div class="metric-delta delta-down">✓ Managed Slices</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        risk_pct = (total_at_risk / total_active) if total_active > 0 else 0
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Members At-Risk (Med-Critical) {tip_risk_all}</div>
            <div class="metric-value">{total_at_risk:,}</div>
            <div class="metric-delta delta-up">{risk_pct:.1%} of active</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col3:
        forecast_pct = (weekly_forecast / total_active) if total_active > 0 else 0
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Weekly Churn Forecast {tip_forecast_all}</div>
            <div class="metric-value">{weekly_forecast:.1f}</div>
            <div class="metric-delta delta-up">{forecast_pct:.1%} expected loss</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col4:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">MRR Value At-Risk (Score >= 50%) {tip_mrr_all}</div>
            <div class="metric-value">${mrr_at_risk:,.2f}</div>
            <div class="metric-delta delta-up">Requires Immediate Action</div>
        </div>
        """, unsafe_allow_html=True)
        
    h_info("Risk Analytics & Distribution", "Analysis of churn risk distribution (pie chart) and continuous probabilities (histogram) for active members.")
    
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
        st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">Proportional Churn Risk Tiers {info("Active membership count categorized by machine learning model risk tiers (Low/Med/High/Critical).")}</div>', unsafe_allow_html=True)
        fig_pie = px.pie(
            dist_df, 
            values='count', 
            names='risk_tier',
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
            paper_bgcolor='#FFFFFF',
            plot_bgcolor='#FFFFFF',
            font_color='#1F2937',
            legend_title_text='Risk Tier',
            margin=dict(t=20)
        )
        st.plotly_chart(fig_pie, use_container_width=True, theme=None)
        
    with chart_col2:
        st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">Distribution of Member Churn Probabilities {info("Counts of active members across predicted churn probability ranges from 0% to 100%.")}</div>', unsafe_allow_html=True)
        prob_df = run_secure_query("SELECT churn_probability FROM scores WHERE score_date = ?", (latest_snapshot_date,))
        fig_hist = px.histogram(
            prob_df, 
            x="churn_probability", 
            nbins=30,
            labels={'churn_probability': 'Predicted Churn Risk Score'},
            color_discrete_sequence=['#5F57FF']
        )
        fig_hist.update_layout(
            paper_bgcolor='#FFFFFF',
            plot_bgcolor='#FFFFFF',
            font_color='#1F2937',
            xaxis_tickformat='.0%',
            margin=dict(t=20)
        )
        fig_hist.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        fig_hist.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        st.plotly_chart(fig_hist, use_container_width=True, theme=None)
        
    # 3. Studio Breakdown (only relevant for Admins to view comparative performance)
    if user_role == "Admin" and not studio_scoped:
        h_info("Home Studio Risk Breakdown", "Admin comparative table showing size, churn forecast, at-risk headcount, and MRR at risk per studio.")
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

    # 4. Engagement vs. Churn Risk quadrant map (Phase 5)
    if os.path.exists(ENGAGEMENT_PATH):
        h_info("Engagement vs. Churn Risk", "Scatter plot mapping members' weighted Engagement Score (0-100) against Churn Probability (0-100%), grouped by segment.")
        eng_df = pd.read_parquet(ENGAGEMENT_PATH)
        if studio_scoped and effective_studio:
            eng_df = eng_df[eng_df["home_studio_id"] == effective_studio]
        if eng_df.empty:
            st.info("No engagement scores for this scope. Run engagement_scorer.py.")
        else:
            ec1, ec2 = st.columns([2, 1])
            with ec1:
                st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">Engagement vs. Churn Risk Quadrant Map {info("Scatter plot mapping members\' weighted Engagement Score (0-100) against Churn Probability (0-100%), grouped by segment. Helps identify under-engaged payers or upsell candidates.")}</div>', unsafe_allow_html=True)
                plot_df = eng_df.copy()
                plot_df["churn_pct"] = plot_df["churn_probability"].fillna(0) * 100
                fig_q = px.scatter(
                    plot_df, x="engagement_score", y="churn_pct", color="segment",
                    labels={"engagement_score": "Engagement (0-100)", "churn_pct": "Churn risk (%)"},
                    color_discrete_map={
                        "upsell_candidate": "#5F57FF", "champion": "#10B981", "engaged": "#8A8F98",
                        "under_engaged_payer": "#F97316", "at_risk_silent": "#EF4444",
                    },
                    opacity=0.5,
                )
                # Add quadrant boundary lines at 50% / 50 score
                fig_q.add_hline(y=50, line_dash="dash", line_color="rgba(31, 41, 55, 0.4)", line_width=1.5)
                fig_q.add_vline(x=50, line_dash="dash", line_color="rgba(31, 41, 55, 0.4)", line_width=1.5)
                
                # Add quadrant descriptive labels at the corners
                fig_q.add_annotation(
                    x=25, y=95, text="🚨 CRITICAL OUTREACH",
                    showarrow=False, font=dict(size=10, color="#EF4444", family="Oswald"),
                    align="center"
                )
                fig_q.add_annotation(
                    x=75, y=95, text="⚠️ VULNERABLE ENGAGED",
                    showarrow=False, font=dict(size=10, color="#F97316", family="Oswald"),
                    align="center"
                )
                fig_q.add_annotation(
                    x=25, y=5, text="💤 UNDER-ENGAGED / PASSIVE",
                    showarrow=False, font=dict(size=10, color="#4B5563", family="Oswald"),
                    align="center"
                )
                fig_q.add_annotation(
                    x=75, y=5, text="🔥 HEALTHY / CHAMPIONS",
                    showarrow=False, font=dict(size=10, color="#10B981", family="Oswald"),
                    align="center"
                )
                
                fig_q.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                    font_color="#1F2937", legend_title_text="Segment",
                                    margin=dict(t=20))
                fig_q.update_xaxes(range=[-5, 105], gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
                fig_q.update_yaxes(range=[-5, 105], gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
                st.plotly_chart(fig_q, use_container_width=True, theme=None)
            with ec2:
                st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">Segment Summary {info("Aggregate breakdown of total member count, average engagement score, and monthly recurring revenue by cohort segment.")}</div>', unsafe_allow_html=True)
                seg_summary = eng_df.groupby("segment").agg(
                    members=("hashed_member_id", "count"),
                    avg_eng=("engagement_score", "mean"),
                    mrr=("monthly_price", "sum"),
                ).round(1).reset_index().sort_values("members", ascending=False)
                st.dataframe(seg_summary, use_container_width=True, hide_index=True)

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
        h_info("Profile Card", "Detailed membership data, home studio, contact info, and current lifecycle stage.")
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
        
        st.markdown(f'<div style="text-align: center; font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937;">Risk Score: {tier} {info("The model\'s predicted probability (0% to 100%) that this member will cancel their membership in the near term.")}</div>', unsafe_allow_html=True)
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = prob * 100,
            domain = {'x': [0, 1], 'y': [0, 1]},
            number = {'suffix': "%", 'font': {'color': color, 'size': 36}},
            gauge = {
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#6B7280"},
                'bar': {'color': color},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "rgba(0,0,0,0.08)",
                'steps': [
                    {'range': [0, 20], 'color': 'rgba(16, 185, 129, 0.15)'},
                    {'range': [20, 50], 'color': 'rgba(251, 191, 36, 0.15)'},
                    {'range': [50, 85], 'color': 'rgba(249, 115, 22, 0.15)'},
                    {'range': [85, 100], 'color': 'rgba(239, 68, 68, 0.15)'}
                ],
            }
        ))
        
        fig_gauge.update_layout(
            paper_bgcolor='#FFFFFF',
            plot_bgcolor='#FFFFFF',
            font={'color': '#1F2937'},
            height=160,
            margin=dict(l=20, r=20, t=10, b=10)
        )
        st.plotly_chart(fig_gauge, use_container_width=True, theme=None)

        # --- Engagement gauge (dual with churn risk, Phase 5) ---
        if os.path.exists(ENGAGEMENT_PATH):
            _eng_row = pd.read_parquet(ENGAGEMENT_PATH)
            _eng_row = _eng_row[_eng_row["hashed_member_id"] == hashed_id]
            if not _eng_row.empty:
                _e = _eng_row.iloc[0]
                _escore = float(_e["engagement_score"])
                _ecolor = "#10B981" if _escore >= 70 else ("#FBBF24" if _escore >= 40 else "#EF4444")
                st.markdown(f'<div style="text-align: center; font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-top: 10px;">Engagement: {_e["segment"]} {info("Composite score (0-100) reflecting class utilization, app logins, chat, and email open metrics.")}</div>', unsafe_allow_html=True)
                fig_eng = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=_escore,
                    domain={'x': [0, 1], 'y': [0, 1]},
                    number={'font': {'color': _ecolor, 'size': 36}},
                    gauge={
                        'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#6B7280"},
                        'bar': {'color': _ecolor},
                        'bgcolor': "rgba(0,0,0,0)", 'borderwidth': 2, 'bordercolor': "rgba(0,0,0,0.08)",
                        'steps': [
                            {'range': [0, 25], 'color': 'rgba(239, 68, 68, 0.15)'},
                            {'range': [25, 40], 'color': 'rgba(249, 115, 22, 0.15)'},
                            {'range': [40, 70], 'color': 'rgba(251, 191, 36, 0.15)'},
                            {'range': [70, 100], 'color': 'rgba(16, 185, 129, 0.15)'},
                        ],
                    }
                ))
                fig_eng.update_layout(paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
                                      font={'color': '#1F2937'}, height=160, margin=dict(l=20, r=20, t=10, b=10))
                st.plotly_chart(fig_eng, use_container_width=True, theme=None)

    with m_col2:
        h_info("Risk Explanation & Diagnostics", "Human-readable reasons explaining the AI's churn risk calculation alongside Churn Risk & Engagement gauges.")
        
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
        h_info("Historical Activity Trends (Last 90 Days)", "Rolling count of session attendance, app logins, and coach chats over the last 90 snapshot days.", "####")
        
        history_query = """
            SELECT date_day, sessions_attended_30d, app_logins_30d, coach_chat_count_30d
            FROM features
            WHERE hashed_member_id = ?
            ORDER BY date_day
        """
        history_df = run_secure_query(history_query, (hashed_id,))
        
        if not history_df.empty:
            history_df = history_df.tail(90)  # limit to last 90 snapshot days
            st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">30-Day Rolling Behavior Metric History {info("Rolling 30-day totals of classes attended, app logins, and interactive coach chat counts over the last 90 snapshot days.")}</div>', unsafe_allow_html=True)
            fig_trend = px.line(
                history_df,
                x='date_day',
                y=['sessions_attended_30d', 'app_logins_30d', 'coach_chat_count_30d'],
                labels={'value': 'Count / Frequency', 'date_day': 'Date', 'variable': 'Metric'},
                color_discrete_sequence=['#5F57FF', '#10B981', '#FF9F1C']
            )
            fig_trend.update_layout(
                paper_bgcolor='#FFFFFF',
                plot_bgcolor='#FFFFFF',
                font_color='#1F2937',
                legend_title_text='Metric',
                margin=dict(t=20)
            )
            fig_trend.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            fig_trend.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            st.plotly_chart(fig_trend, use_container_width=True, theme=None)
            
    # 4. Intervention History Table
    h_info("Past Campaign & Call Interventions", "Auditable record of all campaigns sent, calls logged, and their delivery status.")
    
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
# VIEW: REVENUE IMPACT ATTRIBUTION (Admin-only)
# ==============================================================================
elif view_selection == "Revenue Impact":
    import tempfile
    import revenue_metrics as rm

    st.title("💰 Revenue Impact Attribution")
    if user_role != "Admin":
        st.warning("Revenue Impact is restricted to Admin accounts.")
        st.stop()
    st.markdown("---")

    summary = rm.compute_revenue_summary()
    st.caption(
        f"Attribution estimate — Saved Revenue = targeted at-risk MRR (model risk × tier price) "
        f"× assumed effectiveness (retention {int(rm.RETENTION_EFFECTIVENESS*100)}%, "
        f"win-back {int(rm.WINBACK_REACTIVATION_RATE*100)}%). Not a measured causal result; "
        f"confirmed re-engagements so far: {summary['confirmed_reengaged']}."
    )

    kpis = [
        ("MRR At Risk (targeted)", f"${summary['mrr_at_risk']:,.0f}", f"{summary['members_treated']:,} treated", "delta-up",
         "Expected at-risk monthly revenue among treated members = sum(churn probability × tier price). Fully data-driven."),
        ("Monthly Saved Revenue", f"${summary['saved_mrr']:,.0f}", f"~{summary['est_members_saved']:,.0f} members", "delta-down",
         "Estimated MRR preserved = at-risk MRR × assumed program effectiveness (retention 25% / win-back 8%). An attribution estimate, not a measured causal result."),
        ("Net Monthly Impact", f"${summary['net_monthly_impact']:,.0f}", f"ROI {summary['roi_ratio']}x", "delta-down",
         "Saved monthly revenue minus the cost of the interventions sent."),
        ("Est. LTV Impact", f"${summary['ltv_impact']:,.0f}", f"{summary['avg_lifetime_months']} mo lifetime", "delta-down",
         "Saved MRR × average member lifetime (months) — lifetime value preserved."),
    ]
    cols = st.columns(4)
    for col, (title, val, delta, cls, tip) in zip(cols, kpis):
        with col:
            st.markdown(
                f'<div class="card"><div class="metric-title">{title} {info(tip)}</div>'
                f'<div class="metric-value">{val}</div>'
                f'<div class="metric-delta {cls}">{delta}</div></div>',
                unsafe_allow_html=True,
            )

    left, right = st.columns(2)
    with left:
        h_info("Cohort Retention Curve", "Plotly line chart showing month-over-month survival/retention rates for monthly sign-up cohorts.")
        ret = rm.get_cohort_retention()
        fig_ret = px.line(ret, x="month", y="retention",
                          labels={"month": "Months since join", "retention": "Retention"},
                          color_discrete_sequence=["#5F57FF"])
        fig_ret.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                              font_color="#1F2937", yaxis_tickformat=".0%")
        fig_ret.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        fig_ret.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        fig_ret.update_yaxes(range=[0, 1])
        st.plotly_chart(fig_ret, use_container_width=True, theme=None)
    with right:
        h_info("Channel ROI", "Compares treatment counts, saved members, intervention costs, and net savings across communication channels.")
        st.dataframe(rm.get_channel_roi(), use_container_width=True, hide_index=True)

    h_info("Studio Leaderboard", "Ranks franchise locations by treated members, saved MRR, and net financial impact to drive performance.")
    board = rm.get_studio_leaderboard()
    st.dataframe(
        board[["rank", "home_studio_id", "members_treated", "est_saved",
               "mrr_at_risk", "saved_mrr", "spend", "net_monthly"]]
        .style.background_gradient(subset=["saved_mrr", "net_monthly"], cmap="Greens"),
        use_container_width=True, hide_index=True,
    )

    h_info("Franchise Owner Report", "Section to compile and download high-contrast PDF monthly reports for business meetings.")
    tmp_pdf = os.path.join(tempfile.gettempdir(), "franchise_revenue_report.pdf")
    rm.generate_franchise_pdf(tmp_pdf)
    with open(tmp_pdf, "rb") as f:
        st.download_button("⬇  Download Franchise PDF", f.read(),
                           file_name="franchise_revenue_report.pdf", mime="application/pdf")

# ==============================================================================
# VIEW: MODEL HEALTH & DRIFT (Admin-only)
# ==============================================================================
elif view_selection == "Model Health":
    import train_model as tm
    import model_monitor as mm

    st.title("🩺 Model Health & Drift")
    if user_role != "Admin":
        st.warning("Model Health is restricted to Admin accounts.")
        st.stop()
    st.markdown("---")

    h_info("Retraining controls", "Controls for retraining the machine learning model based on custom training lookback windows.", level="####")
    window_months = st.slider(
        "Rolling training window (months)",
        min_value=6, max_value=36, value=int(tm.ROLLING_TRAIN_WINDOW_MONTHS), step=1,
        help="The model trains ONLY on this trailing time range; older data is deliberately "
             "excluded so it tracks the current business (range of time > range of data).",
    )
    try:
        _as_of = pd.to_datetime(pd.read_parquet(FEATURES_PATH, columns=["date_day"])["date_day"]).max()
        _start = (_as_of - pd.DateOffset(months=window_months)).date()
        st.caption(f"Would train on **{_start} → {_as_of.date()}** · excludes all data before {_start}.")
    except Exception:
        pass

    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if st.button("▶  Run monitoring check"):
            with st.spinner("Scoring recent window + computing drift..."):
                mm.evaluate()
            st.success("Monitoring check complete.")
    with b2:
        if st.button(f"⟳  Force retrain ({window_months}-mo window)"):
            with st.spinner(f"Retraining on trailing {window_months} months..."):
                rec = tm.train_and_save(window_months=window_months, trigger="manual-dashboard")
            st.success(f"Retrained {rec['version_id']} on {rec['train_window_start']} → {rec['train_window_end']} (val AUC {rec['val_auc']}).")

    reg = tm.load_registry()
    if not reg.empty:
        cur = reg.iloc[0]
        cards = [
            ("Live Model Version", str(cur["version_id"]), str(cur["trigger"]), "The unique identifier of the machine learning model version currently deployed to score member risk."),
            (f"Training Window ({cur['window_months']} mo)", f"{cur['train_window_start']} → {cur['train_window_end']}", "rolling time window", "The lookback period used during training, designed to keep model predictions aligned with recent customer trends."),
            ("Val AUC / PR-AUC", f"{cur['val_auc']} / {cur['val_pr_auc']}", f"{int(cur['train_rows']):,} train rows", "Validation metrics. Area Under ROC curve (AUC) measures risk-ranking capability; Precision-Recall AUC measures precision for high-risk targets."),
            ("Old Rows Dropped", f"{int(cur['rows_discarded_as_old']):,}", "excluded by time window", "Historical member-day rows older than the window setting that were discarded during retraining to prevent model staleness."),
        ]
        for col, (t, v, d, tip) in zip(st.columns(4), cards):
            with col:
                st.markdown(
                    f'<div class="card"><div class="metric-title">{t} {info(tip)}</div>'
                    f'<div class="metric-value" style="font-size:19px">{v}</div>'
                    f'<div class="metric-delta delta-down">{d}</div></div>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("No model registry yet — click 'Force retrain' or run train_model.py.")

    left, right = st.columns(2)
    with left:
        h_info("Calibration (predicted vs. actual)", "Scatter plot showing the model's predicted risk deciles vs. actual observed 30-day churn rates to measure accuracy.")
        if os.path.exists(mm.CALIBRATION_PATH):
            calib = pd.read_parquet(mm.CALIBRATION_PATH)
            hi = float(max(calib["avg_predicted"].max(), calib["actual_rate"].max()))
            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(x=[0, hi], y=[0, hi], mode="lines",
                                       line=dict(dash="dash", color="#8A8F98"), name="Perfect"))
            fig_c.add_trace(go.Scatter(x=calib["avg_predicted"], y=calib["actual_rate"],
                                       mode="markers", marker=dict(size=11, color="#5F57FF"), name="Deciles"))
            fig_c.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                font_color="#1F2937", xaxis_title="Predicted", yaxis_title="Actual")
            fig_c.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            fig_c.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            st.plotly_chart(fig_c, use_container_width=True, theme=None)
        else:
            st.info("Run a monitoring check to populate calibration.")
    with right:
        h_info("Feature Drift (PSI)", "Tracks feature distribution shifts using Population Stability Index (PSI) vs. the training baseline.")
        if os.path.exists(mm.DRIFT_PATH):
            drift = pd.read_parquet(mm.DRIFT_PATH)
            fig_d = px.bar(drift, x="psi", y="feature", orientation="h", color="severity",
                           color_discrete_map={"Stable": "#10B981", "Moderate": "#FBBF24", "Significant": "#EF4444"})
            fig_d.add_vline(x=mm.PSI_RETRAIN, line_dash="dash", line_color="#EF4444")
            fig_d.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                                font_color="#1F2937", yaxis={"categoryorder": "total ascending"})
            fig_d.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            fig_d.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            st.plotly_chart(fig_d, use_container_width=True, theme=None)
        else:
            st.info("Run a monitoring check to populate drift.")

    h_info("Retraining History", "Audit log of model retraining runs, showing validation scores and dataset sizes per version.", level="###")
    if not reg.empty:
        st.dataframe(
            reg[["version_id", "trained_at", "trigger", "train_window_start", "train_window_end",
                 "train_rows", "val_auc", "val_pr_auc"]],
            use_container_width=True, hide_index=True,
        )

    h_info("Monitoring Log", "History of automated system checks assessing feature drift and model performance calibration.", level="###")
    if os.path.exists(mm.MONITOR_LOG_PATH):
        mlog = pd.read_parquet(mm.MONITOR_LOG_PATH).sort_values("checked_at", ascending=False)
        st.dataframe(mlog, use_container_width=True, hide_index=True)
    else:
        st.info("No monitoring runs logged yet.")

# ==============================================================================
# VIEW: WIN-BACK LEADERBOARD & BONUS (Admin-only)
# ==============================================================================
elif view_selection == "Win-Back Leaderboard":
    import winback_leaderboard as wbl

    st.title("🏆 Win-Back Leaderboard & Year-End Bonus")
    if user_role != "Admin":
        st.warning("The win-back leaderboard is an org-wide view (Admin only).")
        st.stop()
    st.markdown("---")

    board = wbl.compute_winback_leaderboard()
    pool = wbl.get_bonus_pool()

    kpis = [
        ("🏆 Win-Back Champion", str(pool["champion_studio"]), f"{pool['champion_rate']:.0%} reactivation rate", "The studio with the highest reactivation success rate among cancelled members."),
        ("Recovered Annual Revenue", f"${pool['total_recovered_annual']:,.0f}", "from reactivated cancellations", "Total annualized revenue recovered from cancelled members who reactivated (Recovered MRR x 12)."),
        (f"Year-End Bonus Pool ({int(wbl.BONUS_POOL_PCT*100)}%)", f"${pool['bonus_pool']:,.0f}", "split by revenue recovered", "Year-end bonus pool allocated to studios based on their share of total recovered annual revenue."),
    ]
    for col, (t, v, d, tip) in zip(st.columns(3), kpis):
        with col:
            st.markdown(
                f'<div class="card"><div class="metric-title">{t} {info(tip)}</div>'
                f'<div class="metric-value">{v}</div>'
                f'<div class="metric-delta delta-down">{d}</div></div>',
                unsafe_allow_html=True,
            )

    st.caption(
        "Rank is by reactivation **rate** (skill at retaining canceled members); the bonus is "
        "proportional to **annual revenue recovered**. Reactivation outcomes are synthetic demo "
        "data — production would use observed cancelled→active transitions."
    )

    disp = board.copy()
    disp["studio"] = disp.apply(
        lambda r: (f"{'🥇🥈🥉'[int(r['rank'])-1]} " if r["rank"] <= 3 else "") + str(r["home_studio_id"]), axis=1
    )

    h_info("Studio Reactivation Performance", "Comparison of win-back reactivation rates and outcomes across studios, tracking cancelled members who rejoin.", level="###")
    
    left, right = st.columns([3, 2])
    with left:
        fig_lb = px.bar(
            board, x="reactivation_rate", y="home_studio_id", orientation="h",
            color="reactivation_rate", color_continuous_scale="Purples",
            labels={"reactivation_rate": "Reactivation rate", "home_studio_id": "Studio"},
        )
        fig_lb.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                             font_color="#1F2937", yaxis={"categoryorder": "total ascending"},
                             coloraxis_showscale=False, xaxis_tickformat=".0%",
                             margin=dict(t=20))
        fig_lb.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        fig_lb.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
        st.plotly_chart(fig_lb, use_container_width=True, theme=None)
    with right:
        st.dataframe(
            disp[["studio", "eligible", "reactivated", "reactivation_rate", "recovered_mrr", "bonus_award"]],
            use_container_width=True, hide_index=True,
        )

    h_info("💰 Year-End Bonus Allocation", "Franchise bonus pool distribution calculated as a share of the total recovered annual revenue.", level="###")
    st.dataframe(
        board[["rank", "home_studio_id", "reactivation_rate", "recovered_annual", "bonus_award"]]
        .style.background_gradient(subset=["bonus_award"], cmap="Greens"),
        use_container_width=True, hide_index=True,
    )

# ==============================================================================
# VIEW 3: INTERVENTION QUEUE & A/B RESULTS
# ==============================================================================
else:
    st.title("📋 Campaign Queue & A/B Validation")
    st.markdown("---")
    
    queue_tab, ab_tab = st.tabs(["Active Intervention Queue", "A/B Test Impact Measurements"])
    
    with queue_tab:
        h_info("Current Queue Action Tasks", "List of queued outreach tasks (such as phone calls or automated emails) scheduled for members in this studio.", level="###")
        st.write("Outlined actions that require staff outreach or automated campaign reviews.")
        
        if os.path.exists(QUEUE_PATH):
            queue_all = pd.read_parquet(QUEUE_PATH)
            
            # Resolve GM row-level filter on Home Studio
            if studio_scoped and effective_studio:
                queue_df = queue_all[queue_all["home_studio_id"] == effective_studio].copy()
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
                h_info("Complete Queued Phone Outreach Call", "Log notes and mark a pending call task as completed to move it from the active queue to history.", level="####")
                pending_calls = filtered_q[(filtered_q["action_type"] == "Call") & (filtered_q["status"] == "Pending")].copy()
                
                if pending_calls.empty:
                    st.info("No pending phone calls found in queue.")
                else:
                    call_options = [f"{row['member_id']} - Action: {row['action_id']}" for _, row in pending_calls.iterrows()]
                    selected_call = st.selectbox("Select Call Action to Update:", call_options)
                    
                    selected_act_id = selected_call.split("- Action: ")[-1].strip()
                    selected_mb_id = selected_call.split("- Action: ")[0].strip()
                    
                    notes = st.text_area("Outreach Notes / Outcome:", placeholder="E.g., Left voicemail. Or: Resolved payment issues, updated CC on file.")
                    
                    if oversight_readonly:
                        st.caption("👁 Oversight (read-only) — call completion disabled while viewing as a studio.")
                    elif st.button("Mark Call as Completed"):
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
        h_info("A/B Test Holdout Performance Impact", "Attribution measurements comparing the churn rate of treated members against a 10% holdout control group to isolate intervention lift.", level="###")
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
            if studio_scoped and effective_studio:
                q_df = q_df[q_df["home_studio_id"] == effective_studio].copy()

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
                    <div class="metric-title">Treatment Churn Rate (Notified) {info("The percentage of members in the intervention group (notified/contacted) who ended up cancelling their membership.")}</div>
                    <div class="metric-value">{rate_treat:.1%}</div>
                    <div class="metric-delta delta-down">Sample Size: {n_treat:,}</div>
                </div>
                """, unsafe_allow_html=True)

            with col_ab2:
                st.markdown(f"""
                <div class="card">
                    <div class="metric-title">Holdout Churn Rate (Control) {info("The percentage of members in the 10% holdout group (not notified/contacted) who ended up cancelling their membership.")}</div>
                    <div class="metric-value">{rate_holdout:.1%}</div>
                    <div class="metric-delta delta-up">Sample Size: {n_holdout:,}</div>
                </div>
                """, unsafe_allow_html=True)

            with col_ab3:
                st.markdown(f"""
                <div class="card">
                    <div class="metric-title">Absolute Churn Reduction {info("The absolute percentage point difference in churn rate between the control group and the treatment group (Holdout Rate - Treatment Rate).")}</div>
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
            st.markdown(f'<div style="font-family:\'Oswald\', sans-serif; font-size:16px; font-weight:bold; text-transform:uppercase; color:#1F2937; margin-bottom:10px;">{chart_title} {info("A visual comparison of the churn rates between the treatment group and the control group.")}</div>', unsafe_allow_html=True)
            fig_ab.update_layout(
                yaxis_title="Churn Rate (%)",
                paper_bgcolor='#FFFFFF',
                plot_bgcolor='#FFFFFF',
                font_color='#1F2937',
                margin=dict(t=20)
            )
            fig_ab.update_xaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            fig_ab.update_yaxes(gridcolor='rgba(0,0,0,0.05)', zerolinecolor='rgba(0,0,0,0.1)')
            st.plotly_chart(fig_ab, use_container_width=True, theme=None)
        else:
            st.info("Data models required for A/B testing measurements are not loaded.")
