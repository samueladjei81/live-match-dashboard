import time
import sqlite3
import cv2
from scoreboard import VIDEO_FILE, read_frame, logo_corner, normal_bar_showing, read_numbers_fast

HOME = "USA"
AWAY = "PHI"
NEEDED = 10        # a new score must be read the same way on 10 frames in a row
SPEED = 1          # 1 = normal speed (like live). 4 = four times faster, for quick tests

# 1. Set up the database
db = sqlite3.connect("live.db")
db.execute("PRAGMA journal_mode=WAL")      # lets the dashboard read while we write
db.execute("DROP TABLE IF EXISTS events")
db.execute("DROP TABLE IF EXISTS live_state")
db.execute("""
    CREATE TABLE events (
        event_number   INTEGER PRIMARY KEY,
        video_seconds  REAL,
        game_clock     TEXT,
        team           TEXT,
        points         INTEGER,
        home_score     INTEGER,
        away_score     INTEGER,
        delay_ms       REAL      -- from new score first on screen, to saved here
    )
""")
db.execute("""
    CREATE TABLE live_state (
        id             INTEGER PRIMARY KEY,
        video_seconds  REAL,
        scoreboard     TEXT,     -- 'showing' or 'not showing'
        home_score     INTEGER,
        away_score     INTEGER,
        game_clock     TEXT,
        read_ms        REAL      -- how long reading the last frame took
    )
""")
db.execute("INSERT INTO live_state VALUES (1, 0, 'not showing', NULL, NULL, '', 0)")
db.commit()

# 2. Open the video and take the NBA logo from frame 300
video = cv2.VideoCapture(VIDEO_FILE)
fps = video.get(cv2.CAP_PROP_FPS)
ok, frame = read_frame(video, 300)
nba_logo = logo_corner(frame)
read_numbers_fast(frame)                   # warm-up: loads the model before the live clock starts
video.set(cv2.CAP_PROP_POS_FRAMES, 0)

# 3. Keep track of the score
confirmed = None
candidate = None
times_seen = 0
first_seen_frame = 0
first_seen_clock = ""
last_good_clock = ""
event_number = 0
n = -1
start = time.time()

print("Live feed started. Press Control + C to stop.")

# 4. Play the video frame by frame, at normal speed
while True:
    ok, frame = video.read()
    if not ok:
        break
    n = n + 1

    # Wait until this frame's moment comes, so it plays like a live broadcast
    frame_due = start + n / fps / SPEED
    wait = frame_due - time.time()
    if wait > 0:
        time.sleep(wait)

    read_start = time.time()
    showing = normal_bar_showing(frame, nba_logo)
    numbers = read_numbers_fast(frame) if showing else None
    read_ms = (time.time() - read_start) * 1000

    # Update the live state 3 times per second
    if n % 10 == 0:
        if showing:
            db.execute("UPDATE live_state SET video_seconds=?, scoreboard='showing', home_score=?, "
                       "away_score=?, game_clock=?, read_ms=? WHERE id=1",
                       (round(n / fps, 1), confirmed[0] if confirmed else None,
                        confirmed[1] if confirmed else None, last_good_clock, round(read_ms, 1)))
        else:
            db.execute("UPDATE live_state SET video_seconds=?, scoreboard='not showing', read_ms=? WHERE id=1",
                       (round(n / fps, 1), round(read_ms, 1)))
        db.commit()

    if not showing:
        continue

    try:
        score = (int(numbers["home_score"]), int(numbers["away_score"]))
    except ValueError:
        continue

    if score == confirmed and len(numbers["game_clock"]) >= 4:
        last_good_clock = numbers["game_clock"]

    if score == candidate:
        times_seen = times_seen + 1
    else:
        candidate = score
        times_seen = 1
        first_seen_frame = n
        first_seen_clock = last_good_clock

    if times_seen < NEEDED or score == confirmed:
        continue

    if confirmed is None:
        print("Starting score:", HOME, score[0], "-", score[1], AWAY)
        db.execute("INSERT INTO events VALUES (0, ?, ?, 'START', 0, ?, ?, NULL)",
                   (round(first_seen_frame / fps, 2), last_good_clock, score[0], score[1]))
        db.commit()
        confirmed = score
        continue

    home_change = score[0] - confirmed[0]
    away_change = score[1] - confirmed[1]
    home_scored = home_change in (1, 2, 3) and away_change == 0
    away_scored = away_change in (1, 2, 3) and home_change == 0
    if not home_scored and not away_scored:
        continue

    team, points = (HOME, home_change) if home_scored else (AWAY, away_change)

    # How long since the new score first appeared on screen?
    shown_at = start + first_seen_frame / fps / SPEED
    delay_ms = (time.time() - shown_at) * 1000 * SPEED

    event_number = event_number + 1
    db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (event_number, round(first_seen_frame / fps, 2), first_seen_clock, team, points,
                score[0], score[1], round(delay_ms)))
    db.commit()
    print("Event", event_number, ":", team, "+" + str(points), "->", score[0], "-", score[1],
          "| clock", first_seen_clock, "| saved", round(delay_ms), "ms after it appeared")
    confirmed = score

video.release()
db.close()
print("Live feed finished.")