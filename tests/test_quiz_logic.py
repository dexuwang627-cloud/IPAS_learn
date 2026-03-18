"""Tests for quiz answer checking logic."""
from routers.quiz import _check_answer


def test_choice_correct():
    assert _check_answer("A", "A", "choice") is True


def test_choice_wrong():
    assert _check_answer("A", "B", "choice") is False


def test_choice_case_insensitive():
    assert _check_answer("a", "A", "choice") is True


def test_choice_with_whitespace():
    assert _check_answer(" A ", "A", "choice") is True


def test_multichoice_correct_sorted():
    assert _check_answer("AC", "AC", "multichoice") is True


def test_multichoice_correct_unsorted():
    assert _check_answer("CA", "AC", "multichoice") is True


def test_multichoice_partial():
    assert _check_answer("A", "AC", "multichoice") is False


def test_multichoice_extra():
    assert _check_answer("ACD", "AC", "multichoice") is False


def test_truefalse_correct():
    assert _check_answer("T", "T", "truefalse") is True


def test_truefalse_wrong():
    assert _check_answer("T", "F", "truefalse") is False


def test_scenario_multichoice():
    assert _check_answer("BA", "AB", "scenario_multichoice") is True


def test_scenario_choice():
    assert _check_answer("B", "B", "scenario_choice") is True
