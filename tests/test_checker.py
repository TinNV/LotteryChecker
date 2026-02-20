from lottery_checker.checker import LOSING_RANK, check_ticket, parse_ticket_numbers
from lottery_checker.models import DrawResult, PrizeTier, get_game_spec


def _draw(game: str, main: list[int], bonus: list[int], max_rank: int) -> DrawResult:
    tiers = [
        PrizeTier(rank=f"{rank}等", winners="1口", amount=f"{rank * 1000}円")
        for rank in "123456"[:max_rank]
    ]
    return DrawResult(
        game=game,
        draw_number=1,
        draw_title="test",
        draw_date_jp="令和8年2月20日",
        venue="Tokyo",
        main_numbers=main,
        bonus_numbers=bonus,
        payment_period="-",
        carryover="-",
        sales_amount="-",
        prize_tiers=tiers,
        source_url="https://example.com",
    )


def test_parse_ticket_numbers_sorts_and_validates():
    numbers = parse_ticket_numbers("9, 1, 3, 2, 5, 4", expected_count=6, min_number=1, max_number=43)
    assert numbers == [1, 2, 3, 4, 5, 9]


def test_miniloto_rank_2():
    spec = get_game_spec("miniloto")
    draw = _draw("miniloto", [1, 2, 3, 4, 5], [6], max_rank=4)
    result = check_ticket(spec, draw, [1, 2, 3, 4, 6])
    assert result.rank == "2等"
    assert result.winning is True


def test_loto6_rank_2():
    spec = get_game_spec("loto6")
    draw = _draw("loto6", [1, 2, 3, 4, 5, 6], [7], max_rank=5)
    result = check_ticket(spec, draw, [1, 2, 3, 4, 5, 7])
    assert result.rank == "2等"
    assert result.winning is True


def test_loto7_rank_6():
    spec = get_game_spec("loto7")
    draw = _draw("loto7", [1, 2, 3, 4, 5, 6, 7], [8, 9], max_rank=6)
    result = check_ticket(spec, draw, [1, 2, 3, 8, 30, 31, 32])
    assert result.rank == "6等"
    assert result.winning is True


def test_loto7_not_winning():
    spec = get_game_spec("loto7")
    draw = _draw("loto7", [1, 2, 3, 4, 5, 6, 7], [8, 9], max_rank=6)
    result = check_ticket(spec, draw, [1, 2, 30, 31, 32, 33, 34])
    assert result.rank == LOSING_RANK
    assert result.winning is False
