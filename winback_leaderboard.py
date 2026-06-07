"""
Win-Back Retention Leaderboard & Bonus Engine
=============================================
Ranks studios by how well they RETAIN members who originally cancelled — i.e. win-back
reactivations — and allocates a year-end bonus pool to reward the best performers.

Reactivation signal
-------------------
The base synthetic dataset has no re-joiner cohort yet (the deferred Phase-1 item), so this
module generates a clearly-marked SYNTHETIC reactivation outcome for each win-back-eligible
member, with a per-studio success rate (8–22%) so the leaderboard has a real ranking. In
production this `winback_reactivations.parquet` would instead be built from observed
cancelled→active transitions; the leaderboard/bonus math is unchanged.

Bonus model (assumptions, tunable)
----------------------------------
  BONUS_POOL_PCT of total RECOVERED ANNUAL revenue forms the pool, allocated to studios in
  proportion to the annual revenue each recovered. The #1 studio by reactivation rate is the
  "Win-Back Champion".

Outputs:
  data/winback_reactivations.parquet   (synthetic per-member reactivation outcomes)
  data/winback_leaderboard.parquet     (per-studio ranking + bonus)
"""

import os
import sys
import hashlib
import datetime
import pandas as pd

DATA_DIR = "./data"
LIFECYCLE_PATH = os.path.join(DATA_DIR, "member_lifecycle.parquet")
REACTIVATIONS_PATH = os.path.join(DATA_DIR, "winback_reactivations.parquet")
LEADERBOARD_PATH = os.path.join(DATA_DIR, "winback_leaderboard.parquet")

# The "originally cancelled but winnable" pool that win-back campaigns target.
WINBACK_STAGE = "win_back_eligible"

# Bonus assumptions.
BONUS_POOL_PCT = 0.10           # 10% of recovered ANNUAL revenue funds the bonus pool
MONTHS_PER_YEAR = 12


def _studio_target_rate_pct(studio_id: str) -> int:
    """Deterministic per-studio reactivation success rate in [8, 22] percent."""
    h = int(hashlib.sha256(studio_id.encode()).hexdigest(), 16)
    return 8 + (h % 15)


def _reactivated(member_id: str, rate_pct: int) -> bool:
    """Deterministic Bernoulli(rate) per member (stable, no RNG state)."""
    h = int(hashlib.sha256((str(member_id) + "winback").encode()).hexdigest()[:8], 16)
    return (h % 100) < rate_pct


def ensure_reactivation_data(force: bool = False) -> pd.DataFrame:
    """Build (or load) the synthetic win-back reactivation outcomes."""
    if os.path.exists(REACTIVATIONS_PATH) and not force:
        return pd.read_parquet(REACTIVATIONS_PATH)

    if not os.path.exists(LIFECYCLE_PATH):
        print(f"Error: {LIFECYCLE_PATH} not found. Run lifecycle_stages.py first.")
        sys.exit(1)

    lc = pd.read_parquet(LIFECYCLE_PATH)
    pool = lc[lc["stage"] == WINBACK_STAGE].copy()

    records = []
    for _, m in pool.iterrows():
        studio = str(m["home_studio_id"])
        rate = _studio_target_rate_pct(studio)
        reactivated = _reactivated(m["member_id"], rate)
        records.append({
            "hashed_member_id": m["hashed_member_id"],
            "member_id": m["member_id"],
            "home_studio_id": studio,
            "monthly_price": float(m["monthly_price"]),
            "was_contacted": True,           # win-back campaign targets this whole pool
            "reactivated": bool(reactivated),
            "studio_target_rate_pct": rate,
            "reactivated_at": datetime.date.today().isoformat() if reactivated else None,
            "is_synthetic": True,
        })

    df = pd.DataFrame(records)
    df.to_parquet(REACTIVATIONS_PATH, index=False)
    return df


def compute_winback_leaderboard() -> pd.DataFrame:
    """Per-studio win-back ranking + bonus allocation."""
    react = ensure_reactivation_data()

    board = react.groupby("home_studio_id").agg(
        eligible=("member_id", "count"),
        reactivated=("reactivated", "sum"),
        recovered_mrr=("monthly_price", lambda s: s[react.loc[s.index, "reactivated"]].sum()),
    ).reset_index()

    board["reactivation_rate"] = (board["reactivated"] / board["eligible"].replace(0, pd.NA)).fillna(0).round(3)
    board["recovered_mrr"] = board["recovered_mrr"].round(2)
    board["recovered_annual"] = (board["recovered_mrr"] * MONTHS_PER_YEAR).round(2)

    # Bonus pool = % of total recovered ANNUAL revenue, split by recovered-revenue share.
    total_annual = float(board["recovered_annual"].sum())
    pool = total_annual * BONUS_POOL_PCT
    if total_annual > 0:
        board["bonus_award"] = (board["recovered_annual"] / total_annual * pool).round(2)
    else:
        board["bonus_award"] = 0.0

    # Rank by reactivation rate (normalizes studio size), tie-break by recovered MRR.
    board = board.sort_values(["reactivation_rate", "recovered_mrr"], ascending=False).reset_index(drop=True)
    board.insert(0, "rank", board.index + 1)
    return board


def get_bonus_pool() -> dict:
    board = compute_winback_leaderboard()
    total_annual = float(board["recovered_annual"].sum())
    return {
        "bonus_pool": round(total_annual * BONUS_POOL_PCT, 2),
        "total_recovered_annual": round(total_annual, 2),
        "champion_studio": board.iloc[0]["home_studio_id"] if not board.empty else None,
        "champion_rate": float(board.iloc[0]["reactivation_rate"]) if not board.empty else 0.0,
    }


def get_studio_rank(studio_id: str) -> dict:
    """A single studio's standing (for the GM's own motivation view)."""
    board = compute_winback_leaderboard()
    row = board[board["home_studio_id"] == studio_id]
    if row.empty:
        return {}
    r = row.iloc[0]
    return {
        "rank": int(r["rank"]), "of": len(board),
        "reactivation_rate": float(r["reactivation_rate"]),
        "reactivated": int(r["reactivated"]), "eligible": int(r["eligible"]),
        "recovered_mrr": float(r["recovered_mrr"]), "bonus_award": float(r["bonus_award"]),
    }


def main():
    print("=" * 64)
    print("WIN-BACK RETENTION LEADERBOARD & YEAR-END BONUS")
    print("=" * 64)
    board = compute_winback_leaderboard()
    board.to_parquet(LEADERBOARD_PATH, index=False)

    pool = get_bonus_pool()
    print(f"\nTotal recovered annual revenue : ${pool['total_recovered_annual']:,.2f}")
    print(f"Year-end bonus pool ({int(BONUS_POOL_PCT*100)}%)      : ${pool['bonus_pool']:,.2f}")
    print(f"🏆 Win-Back Champion           : {pool['champion_studio']} "
          f"({pool['champion_rate']:.1%} reactivation)")

    print("\nLEADERBOARD")
    print("-" * 64)
    show = board[["rank", "home_studio_id", "eligible", "reactivated",
                  "reactivation_rate", "recovered_mrr", "recovered_annual", "bonus_award"]]
    print(show.to_string(index=False))
    print(f"\nSaved -> {LEADERBOARD_PATH}")
    print("(Reactivation outcomes are SYNTHETIC demo data; production would use observed "
          "cancelled→active transitions.)")
    print("=" * 64)


if __name__ == "__main__":
    main()
