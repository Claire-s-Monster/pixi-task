"""Unit tests for core.conda_smithy.parse_recipe_lint (issue #44)."""

from __future__ import annotations

from core.conda_smithy import parse_recipe_lint

CLEAN = "recipe is in fine form\n"

# Verbatim conda-smithy 2026.9.23 output, including a whitespace-only line and
# multi-line continuation inside the second hint.
LINT_AND_HINTS = "\n".join(
    [
        "recipe has some lint:",
        "  The license item is expected in the about section.",
        "  The recipe must have some tests.",
        "recipe also has some suggestions:",
        "  No valid build backend found for Python recipe for package `Bad_Name` using `pip`."
        " Python recipes using `pip` need ...",
        "  `noarch: python` recipes should usually follow the syntax in our"
        " [documentation](https://...) for specifying the Python version.",
        "    ",
        "       - For the `host` section of the recipe, you should usually use the pin"
        " python ${{ python_min }}.* for the `python` entry.",
        "       - For the `run` section ...",
        "    - If the package requires a newer Python version ...",
        "",
    ]
)


def test_clean():
    assert parse_recipe_lint(CLEAN) == {
        "lints": [],
        "hints": [],
        "fine": True,
        "unparsed": [],
    }


def test_lint_and_hints_with_continuations():
    out = parse_recipe_lint(LINT_AND_HINTS)
    assert out["fine"] is False
    assert out["unparsed"] == []
    assert out["lints"] == [
        "The license item is expected in the about section.",
        "The recipe must have some tests.",
    ]
    assert len(out["hints"]) == 2
    assert out["hints"][0].startswith("No valid build backend found")
    assert out["hints"][0].endswith("need ...")
    assert out["hints"][1] == "\n".join(
        [
            "`noarch: python` recipes should usually follow the syntax in our"
            " [documentation](https://...) for specifying the Python version.",
            "",
            "       - For the `host` section of the recipe, you should usually use the pin"
            " python ${{ python_min }}.* for the `python` entry.",
            "       - For the `run` section ...",
            "    - If the package requires a newer Python version ...",
        ]
    )


def test_hints_only_header():
    out = parse_recipe_lint("my-recipe has some suggestions:\n  Consider X.\n")
    assert out == {"lints": [], "hints": ["Consider X."], "fine": False, "unparsed": []}


def test_lint_only_header_label_is_arbitrary():
    out = parse_recipe_lint("foo/bar has some lint:\n  Bad thing.\n")
    assert out["lints"] == ["Bad thing."]
    assert out["hints"] == []


def test_trailing_blank_lines_of_item_stripped():
    out = parse_recipe_lint("recipe has some lint:\n  Item one.\n    \n\n")
    assert out["lints"] == ["Item one."]


def test_unparsed_lines_collected():
    text = "warning: something odd\nrecipe has some lint:\n  Real lint.\nTrailing chatter\n"
    out = parse_recipe_lint(text)
    assert out["lints"] == ["Real lint."]
    assert out["unparsed"] == ["warning: something odd", "Trailing chatter"]


def test_item_before_any_header_is_unparsed():
    out = parse_recipe_lint("  orphan item\n")
    assert out["lints"] == [] and out["hints"] == []
    assert out["unparsed"] == ["  orphan item"]


def test_empty_output():
    assert parse_recipe_lint("") == {"lints": [], "hints": [], "fine": False, "unparsed": []}
