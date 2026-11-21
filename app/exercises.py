"""Parse the free-text exercise list WHOOP writes into a Strava activity description.

Formats seen in the wild vary; this is deliberately tolerant and never drops a line: anything that
doesn't look like an exercise comes back as a note. Examples it handles:

    Bench Press: 3 x 10 @ 60 kg          Bench Press - 3 sets x 10 reps - 60 kg
    3x10 Bench Press 60kg                 Squat 10, 10, 8 @ 80 kg
    Deadlift 100kg x 5 x 3                Pull-ups 3 x 8 (bodyweight)
    Lat Pulldown 3×12 50 kg               Plank 3 x 60s
"""
import re
from dataclasses import asdict, dataclass

X = r"[x×\*]"
WEIGHT = re.compile(r"(?:@\s*)?(\d+(?:[.,]\d+)?)\s*(kg|kgs|lb|lbs)\b", re.I)
SETS_REPS = re.compile(rf"(\d+)\s*(?:sets?)?\s*{X}\s*(\d+)\s*(?:reps?)?", re.I)
REP_LIST = re.compile(r"\b(\d{1,3}(?:\s*,\s*\d{1,3}){1,9})\b")
TIME_REPS = re.compile(rf"(\d+)\s*{X}\s*(\d+)\s*(s|sec|secs|seconds|min)\b", re.I)
SKIP = re.compile(r"^(workout|strength|strength trainer|whoop|total|duration|muscular load|notes?)\b[:\s]*", re.I)
NOISE = re.compile(r"\b(sets?|reps?|bodyweight|bw)\b|@|[:()\[\]]|(?<!\S)[-–](?!\S)", re.I)  # keeps hyphens inside words


@dataclass
class Exercise:
    exercise: str
    sets: int | None = None
    reps: int | None = None          # reps per set when uniform, else None (see reps_list)
    reps_list: str | None = None     # "10, 10, 8" when sets differ
    weight_kg: float | None = None
    seconds: int | None = None       # timed holds, e.g. plank 3 x 60s
    raw: str = ""

    @property
    def volume_kg(self) -> float | None:
        if self.weight_kg is None:
            return None
        if self.reps_list:
            return round(self.weight_kg * sum(int(r) for r in self.reps_list.split(",")), 1)
        if self.sets and self.reps:
            return round(self.weight_kg * self.sets * self.reps, 1)
        return None


def _to_kg(value: str, unit: str) -> float:
    v = float(value.replace(",", "."))
    return round(v * 0.45359237, 1) if unit.lower().startswith("lb") else round(v, 1)


def parse_line(line: str) -> Exercise | None:
    """One description line -> Exercise, or None if it carries no sets/reps/weight at all."""
    text = line.strip().lstrip("-•*·").strip()
    if not text or SKIP.match(text):
        return None
    ex = Exercise(exercise="", raw=line.strip())
    rest = text

    if m := WEIGHT.search(rest):
        ex.weight_kg = _to_kg(m.group(1), m.group(2))
        rest = rest[:m.start()] + " " + rest[m.end():]
    if m := TIME_REPS.search(rest):
        ex.sets, ex.seconds = int(m.group(1)), int(m.group(2)) * (60 if m.group(3).lower().startswith("min") else 1)
        rest = rest[:m.start()] + " " + rest[m.end():]
    elif m := SETS_REPS.search(rest):
        a, b = int(m.group(1)), int(m.group(2))
        # "100kg x 5 x 3" style puts reps before sets; prefer the smaller number as sets when ambiguous
        ex.sets, ex.reps = (a, b) if a <= b or a <= 10 else (b, a)
        rest = rest[:m.start()] + " " + rest[m.end():]
        if m2 := re.search(rf"^\s*{X}\s*(\d+)", rest[m.start():]):  # trailing "x 3" after "100kg x 5"
            ex.sets, ex.reps = int(m2.group(1)), ex.reps
    elif m := REP_LIST.search(rest):
        reps = [int(r) for r in re.split(r"\s*,\s*", m.group(1))]
        ex.sets, ex.reps_list = len(reps), ", ".join(str(r) for r in reps)
        if len(set(reps)) == 1:
            ex.reps, ex.reps_list = reps[0], None
        rest = rest[:m.start()] + " " + rest[m.end():]

    if ex.sets is None and ex.weight_kg is None and ex.seconds is None:
        return None
    name = NOISE.sub(" ", rest)
    name = re.sub(r"\s+", " ", name).strip(" .,-–:")
    ex.exercise = name.title() if name and name.islower() else (name or "Exercise")
    return ex


def parse_description(description: str | None) -> tuple[list[dict], list[str]]:
    """Returns (exercises, notes). Notes are lines that weren't parseable, kept so nothing is lost."""
    exercises, notes = [], []
    for line in (description or "").splitlines():
        if not line.strip():
            continue
        ex = parse_line(line)
        if ex:
            d = asdict(ex)
            d["volume_kg"] = ex.volume_kg
            exercises.append(d)
        elif not SKIP.match(line.strip()):
            notes.append(line.strip())
    return exercises, notes
