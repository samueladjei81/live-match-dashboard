# Shared tools for reading the NBA 2K scoreboard.
# Other files use these with:  from scoreboard import ...

import cv2
import pytesseract
import joblib

VIDEO_FILE = "data/nba2k26.mp4"

# Where each number is on the normal bar: (top, bottom, left, right)
BOXES = {
    "home_score": (532, 555, 108, 165),
    "away_score": (532, 555, 250, 310),
    "game_clock": (530, 563, 375, 432),
    "shot_clock": (538, 556, 449, 472),
    "quarter":    (530, 563, 480, 518),
}

# Which characters Tesseract is allowed to see in each box
ALLOWED = {
    "home_score": "0123456789",
    "away_score": "0123456789",
    "game_clock": "0123456789:.",
    "shot_clock": "0123456789",
    "quarter":    "1234stndrhOT",
}


# Read one frame by its number
def read_frame(video, n):
    video.set(cv2.CAP_PROP_POS_FRAMES, n)
    ok, frame = video.read()
    return ok, frame


# Cut out the NBA logo corner, in black and white
def logo_corner(frame):
    return cv2.cvtColor(frame[535:562, 8:48], cv2.COLOR_BGR2GRAY)


# Is the normal scoreboard bar showing? (compares the corner with the NBA logo)
def normal_bar_showing(frame, nba_logo):
    result = cv2.matchTemplate(logo_corner(frame), nba_logo, cv2.TM_CCOEFF_NORMED)
    return float(result[0][0]) > 0.7


# Clean up a cut-out so Tesseract can read it
def clean_up(piece):
    gray = cv2.cvtColor(piece, cv2.COLOR_BGR2GRAY)
    bigger = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    ok, black_white = cv2.threshold(bigger, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if cv2.countNonZero(black_white) < black_white.size / 2:
        black_white = 255 - black_white
    return cv2.copyMakeBorder(black_white, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


# Read every number in one frame
def read_numbers(frame):
    results = {}
    for name in BOXES:
        top, bottom, left, right = BOXES[name]
        piece = frame[top:bottom, left:right]
        settings = "--psm 7 -c tessedit_char_whitelist=" + ALLOWED[name]
        text = pytesseract.image_to_string(clean_up(piece), config=settings)
        results[name] = text.strip()
    return results

# Split a cut-out into single digits, left to right.
# Each digit comes back as a small 20 x 30 black-and-white picture (white digit on black).
def split_digits(piece):
    ink = 255 - clean_up(piece)          # flip so the digits are white
    count, labels, boxes, centres = cv2.connectedComponentsWithStats(ink)

    # Every separate white blob: (left, top, width, height, size)
    blobs = [boxes[i] for i in range(1, count)]
    if not blobs:
        return []

    tallest = max(blob[3] for blob in blobs)
    height, width = ink.shape
    digits = []
    for left, top, w, h, size in blobs:
        too_short = h < 0.6 * tallest                      # dots in "1:58" and "28.1"
        touches_edge = (left < 20 or top < 20 or
                        left + w > width - 20 or top + h > height - 20)
        if too_short or touches_edge:
            continue
        digits.append((left, ink[top:top + h, left:left + w]))

    digits.sort(key=lambda d: d[0])                         # left to right
    return [cv2.resize(picture, (20, 30)) for left, picture in digits]

# Count the small blobs in a cut-out: 2 for ":" (like "1:58"), 1 for "." (like "28.1")
def count_dots(piece):
    ink = 255 - clean_up(piece)
    count, labels, boxes, centres = cv2.connectedComponentsWithStats(ink)
    blobs = [boxes[i] for i in range(1, count)]
    if not blobs:
        return 0
    tallest = max(blob[3] for blob in blobs)
    dots = 0
    for left, top, w, h, size in blobs:
        if h < 0.6 * tallest and size > 50:
            dots = dots + 1
    return dots


# The trained model is loaded the first time the fast reader is used
digit_model = None


# The fast reader: split into digits and let your model recognise them
def read_numbers_fast(frame):
    global digit_model
    if digit_model is None:
        digit_model = joblib.load("digit_model.joblib")

    fields = ["home_score", "away_score", "game_clock", "shot_clock"]

    # 1. Split every number into digit pictures, and remember which number each belongs to
    all_pictures = []
    belongs_to = []
    for name in fields:
        top, bottom, left, right = BOXES[name]
        for picture in split_digits(frame[top:bottom, left:right]):
            all_pictures.append(picture.flatten() / 255)
            belongs_to.append(name)

    # 2. Ask the model about ALL the digits at once
    if all_pictures:
        answers = digit_model.predict(all_pictures)
    else:
        answers = []

    # 3. Put the digits back together, number by number
    results = {name: "" for name in fields}
    for name, digit in zip(belongs_to, answers):
        results[name] = results[name] + digit

    # 4. Put the ":" or "." back into the game clock
    digits = results["game_clock"]
    if len(digits) >= 3:
        top, bottom, left, right = BOXES["game_clock"]
        if count_dots(frame[top:bottom, left:right]) >= 2:
            results["game_clock"] = digits[:-2] + ":" + digits[-2:]
        else:
            results["game_clock"] = digits[:-1] + "." + digits[-1:]

    results["quarter"] = "4th"     # the fast reader does not read the quarter
    return results