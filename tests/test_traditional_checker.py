from lottery_checker.checker import check_traditional_ticket, parse_traditional_ticket
from lottery_checker.models import TraditionalDrawResult, TraditionalPrizeRow


def _draw(rows: list[TraditionalPrizeRow]) -> TraditionalDrawResult:
    return TraditionalDrawResult(
        lottery_type="zenkoku",
        draw_order=1090,
        draw_title="第1090回 全国自治宝くじ",
        draw_subtitle="test",
        draw_date_jp="令和8年2月20日",
        venue="東京",
        payment_period="令和8年2月26日から令和9年2月25日まで",
        prize_rows=rows,
        source_url="https://example.com",
    )


def test_parse_traditional_ticket():
    group, number = parse_traditional_ticket("１６組", " 139476 ")
    assert group == "16"
    assert number == "139476"


def test_check_traditional_exact_group_and_number():
    draw = _draw(
        [
            TraditionalPrizeRow(rank="１等", amount="1000万円", group="16組", number="139476"),
        ]
    )
    result = check_traditional_ticket(draw, ticket_group="16", ticket_number="139476")
    assert result.winning is True
    assert result.total_payout_yen == 10_000_000


def test_check_traditional_tail_prize():
    draw = _draw(
        [
            TraditionalPrizeRow(rank="３等", amount="3万円", group="下４ケタ", number="0229"),
        ]
    )
    result = check_traditional_ticket(draw, ticket_group="88", ticket_number="140229")
    assert result.winning is True
    assert result.total_payout_yen == 30_000


def test_check_traditional_adjacent_and_different_group():
    draw = _draw(
        [
            TraditionalPrizeRow(rank="１等", amount="1000万円", group="16組", number="139476"),
            TraditionalPrizeRow(rank="１等の前後賞", amount="250万円", group="１等の前後の番号", number=""),
            TraditionalPrizeRow(rank="１等の組違い賞", amount="10万円", group="１等の組違い同番号", number=""),
        ]
    )

    around = check_traditional_ticket(draw, ticket_group="16", ticket_number="139477")
    assert around.winning is True
    assert around.total_payout_yen == 2_500_000

    diff_group = check_traditional_ticket(draw, ticket_group="99", ticket_number="139476")
    assert diff_group.winning is True
    assert diff_group.total_payout_yen == 100_000
