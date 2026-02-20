from __future__ import annotations

import re
from typing import Iterable, List

from .models import (
    DrawResult,
    GameSpec,
    TicketCheckResult,
    TraditionalDrawResult,
    TraditionalTicketCheckResult,
    TraditionalTicketMatch,
)

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
LOSING_RANK = "Không trúng"


class TicketValidationError(ValueError):
    pass


def _normalize_number_token(token: str) -> int:
    normalized = token.translate(FULLWIDTH_DIGITS)
    match = re.search(r"\d+", normalized)
    if not match:
        raise TicketValidationError(f"Không đọc được số từ: {token}")
    return int(match.group(0))


def parse_ticket_numbers(
    raw_input: str,
    expected_count: int,
    min_number: int,
    max_number: int,
) -> List[int]:
    if not raw_input.strip():
        raise TicketValidationError("Bạn chưa nhập dãy số vé.")

    tokens = [token for token in re.split(r"[\s,;/]+", raw_input.strip()) if token]
    if len(tokens) != expected_count:
        raise TicketValidationError(f"Cần nhập đúng {expected_count} số.")

    numbers = [_normalize_number_token(token) for token in tokens]
    if len(set(numbers)) != len(numbers):
        raise TicketValidationError("Dãy số có số bị trùng lặp.")

    out_of_range = [n for n in numbers if n < min_number or n > max_number]
    if out_of_range:
        raise TicketValidationError(
            f"Số hợp lệ trong khoảng {min_number}-{max_number}. Lỗi: {out_of_range}"
        )

    return sorted(numbers)


def _find_payout(draw: DrawResult, rank: str) -> tuple[str, str]:
    for tier in draw.prize_tiers:
        if tier.rank == rank:
            return tier.winners, tier.amount
    return "-", "-"


def _determine_rank(game: str, main_hits: int, bonus_hits: int) -> str:
    if game == "miniloto":
        if main_hits == 5:
            return "1等"
        if main_hits == 4 and bonus_hits == 1:
            return "2等"
        if main_hits == 4:
            return "3等"
        if main_hits == 3:
            return "4等"
        return LOSING_RANK

    if game == "loto6":
        if main_hits == 6:
            return "1等"
        if main_hits == 5 and bonus_hits == 1:
            return "2等"
        if main_hits == 5:
            return "3等"
        if main_hits == 4:
            return "4等"
        if main_hits == 3:
            return "5等"
        return LOSING_RANK

    if game == "loto7":
        if main_hits == 7:
            return "1等"
        if main_hits == 6 and bonus_hits >= 1:
            return "2等"
        if main_hits == 6:
            return "3等"
        if main_hits == 5:
            return "4等"
        if main_hits == 4:
            return "5等"
        if main_hits == 3 and bonus_hits >= 1:
            return "6等"
        return LOSING_RANK

    raise ValueError(f"Loại xổ số chưa hỗ trợ: {game}")


def _intersection(first: Iterable[int], second: Iterable[int]) -> List[int]:
    return sorted(set(first).intersection(second))


def check_ticket(game_spec: GameSpec, draw: DrawResult, ticket_numbers: List[int]) -> TicketCheckResult:
    matched_main = _intersection(ticket_numbers, draw.main_numbers)
    matched_bonus = _intersection(ticket_numbers, draw.bonus_numbers)
    rank = _determine_rank(game_spec.key, len(matched_main), len(matched_bonus))
    winning = rank != LOSING_RANK
    winners, amount = _find_payout(draw, rank) if winning else ("-", "-")

    return TicketCheckResult(
        ticket_numbers=ticket_numbers,
        matched_main=matched_main,
        matched_bonus=matched_bonus,
        rank=rank,
        winning=winning,
        payout_winners=winners,
        payout_amount=amount,
    )


def parse_traditional_ticket(group_raw: str, number_raw: str) -> tuple[str, str]:
    group = _digits_only(group_raw)
    number = _digits_only(number_raw)
    if not group:
        raise TicketValidationError("Bạn chưa nhập số tổ.")
    if not number:
        raise TicketValidationError("Bạn chưa nhập số vé.")
    return group, number


def check_traditional_ticket(
    draw: TraditionalDrawResult,
    ticket_group: str,
    ticket_number: str,
) -> TraditionalTicketCheckResult:
    matches: List[TraditionalTicketMatch] = []
    for row in draw.prize_rows:
        if _traditional_row_match(
            draw=draw,
            row_rank=row.rank,
            row_group=row.group,
            row_number=row.number,
            ticket_group=ticket_group,
            ticket_number=ticket_number,
        ):
            matches.append(
                TraditionalTicketMatch(
                    rank=row.rank,
                    amount=row.amount,
                    group_condition=row.group,
                    number_condition=row.number,
                )
            )

    winning = len(matches) > 0
    total_yen, total_display = _sum_payout(matches)

    return TraditionalTicketCheckResult(
        ticket_group=ticket_group,
        ticket_number=ticket_number,
        winning=winning,
        total_payout_yen=total_yen,
        total_payout_display=total_display,
        matches=matches,
    )


def _sum_payout(matches: List[TraditionalTicketMatch]) -> tuple[int | None, str]:
    if not matches:
        return 0, "0円"

    parsed_values: List[int] = []
    unknown_count = 0
    for match in matches:
        yen = _parse_amount_to_yen(match.amount)
        if yen is None:
            unknown_count += 1
        else:
            parsed_values.append(yen)

    if not parsed_values:
        return None, "Không xác định"

    total = sum(parsed_values)
    if unknown_count:
        return total, f"{total:,}円 (chưa tính {unknown_count} giải không parse được)"
    return total, f"{total:,}円"


def _parse_amount_to_yen(raw_amount: str) -> int | None:
    text = raw_amount.translate(FULLWIDTH_DIGITS)
    text = re.sub(r"\s+", "", text)
    if not text or "該当なし" in text:
        return None
    text = text.replace(",", "")
    tokens = re.findall(r"(\d+(?:\.\d+)?)(億|万|円)", text)
    if not tokens:
        return None
    scale = {"億": 100_000_000, "万": 10_000, "円": 1}
    total = 0.0
    for number, unit in tokens:
        total += float(number) * scale[unit]
    return int(round(total))


def _traditional_row_match(
    draw: TraditionalDrawResult,
    row_rank: str,
    row_group: str,
    row_number: str,
    ticket_group: str,
    ticket_number: str,
) -> bool:
    group_cond = _normalize_text(row_group)
    if not group_cond:
        return False

    if "前後の番号" in group_cond:
        return _match_adjacent_prize(draw, group_cond, ticket_group, ticket_number)

    if "組違い同番号" in group_cond:
        return _match_different_group_same_number(draw, group_cond, ticket_group, ticket_number)

    return _match_group_condition(group_cond, ticket_group) and _match_number_condition(
        group_cond=group_cond,
        row_number=row_number,
        ticket_number=ticket_number,
    )


def _match_adjacent_prize(
    draw: TraditionalDrawResult,
    group_cond: str,
    ticket_group: str,
    ticket_number: str,
) -> bool:
    base_rank = _extract_base_rank(group_cond)
    if not base_rank:
        return False

    for row in draw.prize_rows:
        if _normalize_rank(row.rank) != base_rank:
            continue
        if not _match_group_condition(_normalize_text(row.group), ticket_group):
            continue
        win_number = _digits_only(row.number)
        if not win_number:
            continue
        width = max(len(ticket_number), len(win_number))
        ticket_value = int(ticket_number.zfill(width))
        win_value = int(win_number.zfill(width))
        if abs(ticket_value - win_value) == 1:
            return True
    return False


def _match_different_group_same_number(
    draw: TraditionalDrawResult,
    group_cond: str,
    ticket_group: str,
    ticket_number: str,
) -> bool:
    base_rank = _extract_base_rank(group_cond)
    if not base_rank:
        return False

    for row in draw.prize_rows:
        if _normalize_rank(row.rank) != base_rank:
            continue
        win_number = _digits_only(row.number)
        if not win_number or not _match_exact_number(ticket_number, win_number):
            continue
        if not _match_group_condition(_normalize_text(row.group), ticket_group):
            return True
    return False


def _extract_base_rank(condition_text: str) -> str | None:
    normalized = _normalize_text(condition_text)
    match = re.search(r"(\d+等)", normalized)
    return match.group(1) if match else None


def _normalize_rank(rank: str) -> str:
    return _normalize_text(rank)


def _normalize_text(text: str) -> str:
    normalized = text.translate(FULLWIDTH_DIGITS)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _digits_only(text: str) -> str:
    normalized = text.translate(FULLWIDTH_DIGITS)
    return "".join(ch for ch in normalized if ch.isdigit())


def _match_group_condition(group_cond: str, ticket_group: str) -> bool:
    if not group_cond:
        return False
    if "各組共通" in group_cond:
        return True
    if "下" in group_cond and "ケタ" in group_cond:
        return True

    suffix_match = re.search(r"組下(\d+)ケタ(\d+)組", group_cond)
    if suffix_match:
        width = int(suffix_match.group(1))
        target_group = suffix_match.group(2)
        return ticket_group.zfill(width)[-width:] == target_group.zfill(width)[-width:]

    exact_match = re.fullmatch(r"(\d+)組", group_cond)
    if exact_match:
        return int(ticket_group) == int(exact_match.group(1))

    # Nhãn đặc biệt, xử lý ở các nhánh riêng.
    if "前後の番号" in group_cond or "組違い同番号" in group_cond:
        return False

    # Trường hợp chưa nhận diện được điều kiện tổ.
    return False


def _match_number_condition(group_cond: str, row_number: str, ticket_number: str) -> bool:
    winning_digits = _digits_only(row_number)
    if not winning_digits:
        return False

    tail_match = re.search(r"下(\d+)ケタ", group_cond)
    if tail_match:
        width = int(tail_match.group(1))
        target = winning_digits.zfill(width)[-width:]
        return ticket_number.zfill(width)[-width:] == target

    return _match_exact_number(ticket_number, winning_digits)


def _match_exact_number(ticket_number: str, winning_number: str) -> bool:
    width = max(len(ticket_number), len(winning_number))
    return ticket_number.zfill(width) == winning_number.zfill(width)
