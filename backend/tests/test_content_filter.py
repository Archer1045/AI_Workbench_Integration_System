from content_filter import is_always_blocked, is_hard_blocked


def test_lolita_fashion_terms_do_not_match_loli_substring() -> None:
    assert is_always_blocked("gothic_lolita") is False
    assert is_always_blocked("gothic lolita fashion") is False


def test_standalone_or_delimited_blocked_terms_still_match() -> None:
    assert is_always_blocked("loli walking") is True
    assert is_always_blocked("loli_girl") is True
    assert is_always_blocked("underage-girl") is True
    assert is_always_blocked("萝莉") is True
    assert is_hard_blocked("animal sex") is True
