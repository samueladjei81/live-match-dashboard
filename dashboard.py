import time
import sqlite3
import pandas as pd
import streamlit as st

HOME = "USA"
AWAY = "PHI"

st.set_page_config(page_title="Live match dashboard", layout="wide")
st.title(HOME + " vs " + AWAY + ": live match dashboard")
st.caption("NBA 2K26 gameplay clip, replayed as if live. The page updates every second.")

# 1. Read the latest data from the database
try:
    db = sqlite3.connect("live.db")
    state = pd.read_sql("SELECT * FROM live_state", db)
    events = pd.read_sql("SELECT * FROM events ORDER BY event_number", db)
    db.close()
except Exception:
    st.info("Waiting for the live feed to start...")
    time.sleep(1)
    st.rerun()

now = state.iloc[0]

# The starting score (event 0) is used for the lead chart only, not counted as an event
lead_rows = events.copy()
events = events[events["team"] != "START"]

# 2. The scoreboard
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric(HOME, "-" if pd.isna(now["home_score"]) else int(now["home_score"]))
col2.metric(AWAY, "-" if pd.isna(now["away_score"]) else int(now["away_score"]))
col3.metric("Game clock", now["game_clock"] or "-")
col4.metric("Scoreboard", now["scoreboard"])
col5.metric("Video time", str(now["video_seconds"]) + " s")

# 3. Speed
col1, col2, col3 = st.columns(3)
col1.metric("Events so far", len(events))
col2.metric("Average time to save an event",
            "-" if events.empty else str(round(events["delay_ms"].mean())) + " ms")
col3.metric("Time to read the last frame", str(now["read_ms"]) + " ms")

# 4. Events, newest first
st.subheader("Events")
if events.empty:
    st.write("No events yet.")
else:
    st.dataframe(events.sort_values("event_number", ascending=False), hide_index=True,
                 use_container_width=True)

    # 5. Team stats and the lead after each event
    left, right = st.columns(2)
    with left:
        st.subheader("Points by team")
        stats = events.groupby("team").agg(points=("points", "sum"), scores=("points", "count"))
        st.dataframe(stats, use_container_width=True)
    with right:
        st.subheader(HOME + " lead after each event")
        lead = lead_rows.set_index("video_seconds")
        lead = (lead["home_score"] - lead["away_score"]).rename(HOME + " lead")
        st.line_chart(lead, x_label="video time (seconds)", y_label="points")
        st.caption("Largest " + HOME + " lead: " + str(lead.max()) + " points")

# 6. Wait one second, then refresh the page
time.sleep(1)
st.rerun()