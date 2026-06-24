from utils import formatting


def test_parse_page_args_all_last_invalid_and_bounds():
    assert formatting.parse_page_args([]) == formatting.PageRequest(page=1, all=False)
    assert formatting.parse_page_args(["all"]) == formatting.PageRequest(page=1, all=True)
    assert formatting.parse_page_args(["last"]) == formatting.PageRequest(page=-1, all=False)
    assert formatting.parse_page_args(["0"]) == formatting.PageRequest(page=1, all=False)
    assert formatting.parse_page_args(["bad"], default_page=3) == formatting.PageRequest(page=3, all=False)


def test_paginate_and_format_pages():
    lines = [f"line {idx}" for idx in range(5)]
    page, current, total = formatting.paginate_lines(lines, page=-1, page_size=2)
    assert page == ["line 4"]
    assert current == 3
    assert total == 3

    page, current, total = formatting.paginate_lines(lines, page=99, page_size=0)
    assert page == lines
    assert current == 1
    assert total == 1

    assert formatting.format_page("Title", [], command_hint=",cmd") == ["Title", "—"]
    all_page = formatting.format_page(
        "Title",
        ["a", "b"],
        page_request=formatting.PageRequest(all=True),
    )
    assert all_page == ["Title", "a", "b"]

    paged = formatting.format_page(
        "Title",
        lines,
        page_request=formatting.PageRequest(page=1),
        page_size=2,
        command_hint=",cmd",
    )
    assert paged[0] == "Title (page 1/3)"
    assert paged[-1] == "Use ,cmd <page|last|all> for more."
    assert formatting.bool_label(False) == "disabled"
