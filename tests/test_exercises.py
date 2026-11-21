import pytest

from app.exercises import parse_description, parse_line


@pytest.mark.parametrize("line, exercise, sets, reps, kg", [
    ("Bench Press: 3 x 10 @ 60 kg", "Bench Press", 3, 10, 60.0),
    ("Bench Press - 3 sets x 10 reps - 60 kg", "Bench Press", 3, 10, 60.0),
    ("3x10 Bench Press 60kg", "Bench Press", 3, 10, 60.0),
    ("Lat Pulldown 3×12 50 kg", "Lat Pulldown", 3, 12, 50.0),
    ("Pull-ups 3 x 8 (bodyweight)", "Pull-ups", 3, 8, None),
    ("Dumbbell Row 4 x 12 @ 45 lb", "Dumbbell Row", 4, 12, 20.4),
    ("- Goblet Squat 3 x 15 @ 24kg", "Goblet Squat", 3, 15, 24.0),
])
def test_parse_common_formats(line, exercise, sets, reps, kg):
    ex = parse_line(line)
    assert ex is not None, line
    assert (ex.exercise, ex.sets, ex.reps, ex.weight_kg) == (exercise, sets, reps, kg)


def test_rep_list_and_volume():
    ex = parse_line("Squat 10, 10, 8 @ 80 kg")
    assert ex.exercise == "Squat" and ex.sets == 3 and ex.reps is None and ex.reps_list == "10, 10, 8"
    assert ex.volume_kg == 80 * 28


def test_uniform_rep_list_collapses():
    ex = parse_line("Leg Press 12, 12, 12 @ 120 kg")
    assert ex.sets == 3 and ex.reps == 12 and ex.reps_list is None and ex.volume_kg == 120 * 36


def test_timed_hold():
    ex = parse_line("Plank 3 x 60s")
    assert ex.exercise == "Plank" and ex.sets == 3 and ex.seconds == 60 and ex.reps is None


def test_description_keeps_unparsed_lines_as_notes():
    text = "Strength Trainer\nBench Press: 3 x 10 @ 60 kg\nFelt strong today\nFace Pull 3 x 15 @ 20 kg\n"
    exercises, notes = parse_description(text)
    assert [e["exercise"] for e in exercises] == ["Bench Press", "Face Pull"]
    assert exercises[0]["volume_kg"] == 1800.0
    assert notes == ["Felt strong today"]


def test_empty_description():
    assert parse_description(None) == ([], [])
    assert parse_description("Morning lift") == ([], ["Morning lift"])
