from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class GameSpec:
    key: str
    label: str
    picks: int
    min_number: int
    max_number: int
    bonus_count: int
    prefix: str


@dataclass(frozen=True)
class PrizeTier:
    rank: str
    winners: str
    amount: str


@dataclass(frozen=True)
class DrawResult:
    game: str
    draw_number: int
    draw_title: str
    draw_date_jp: str
    venue: str
    main_numbers: List[int]
    bonus_numbers: List[int]
    payment_period: str
    carryover: str
    sales_amount: str
    prize_tiers: List[PrizeTier]
    source_url: str


@dataclass(frozen=True)
class TicketCheckResult:
    ticket_numbers: List[int]
    matched_main: List[int]
    matched_bonus: List[int]
    rank: str
    winning: bool
    payout_winners: str
    payout_amount: str


@dataclass(frozen=True)
class TraditionalType:
    key: str
    label: str
    jp_label: str


@dataclass(frozen=True)
class TraditionalPrizeRow:
    rank: str
    amount: str
    group: str
    number: str


@dataclass(frozen=True)
class TraditionalDrawResult:
    lottery_type: str
    draw_order: int
    draw_title: str
    draw_subtitle: str
    draw_date_jp: str
    venue: str
    payment_period: str
    prize_rows: List[TraditionalPrizeRow]
    source_url: str


@dataclass(frozen=True)
class TraditionalTicketMatch:
    rank: str
    amount: str
    group_condition: str
    number_condition: str


@dataclass(frozen=True)
class TraditionalTicketCheckResult:
    ticket_group: str
    ticket_number: str
    winning: bool
    total_payout_yen: int | None
    total_payout_display: str
    matches: List[TraditionalTicketMatch]


GAME_SPECS: Dict[str, GameSpec] = {
    "miniloto": GameSpec(
        key="miniloto",
        label="Mini Loto",
        picks=5,
        min_number=1,
        max_number=31,
        bonus_count=1,
        prefix="1",
    ),
    "loto6": GameSpec(
        key="loto6",
        label="Loto 6",
        picks=6,
        min_number=1,
        max_number=43,
        bonus_count=1,
        prefix="2",
    ),
    "loto7": GameSpec(
        key="loto7",
        label="Loto 7",
        picks=7,
        min_number=1,
        max_number=37,
        bonus_count=2,
        prefix="3",
    ),
}

TRADITIONAL_TYPES: Dict[str, TraditionalType] = {
    "zenkoku": TraditionalType(
        key="zenkoku",
        label="Toàn quốc",
        jp_label="全国自治",
    ),
    "jumbo": TraditionalType(
        key="jumbo",
        label="Jumbo",
        jp_label="ジャンボ",
    ),
    "tokyo": TraditionalType(
        key="tokyo",
        label="Tokyo",
        jp_label="東京都",
    ),
    "kinki": TraditionalType(
        key="kinki",
        label="Kinki",
        jp_label="近畿",
    ),
    "chiiki": TraditionalType(
        key="chiiki",
        label="Khu vực y tế",
        jp_label="地域医療等振興自治",
    ),
    "kct": TraditionalType(
        key="kct",
        label="Kanto/Chubu/Tohoku",
        jp_label="関東・中部・東北自治",
    ),
    "nishinihon": TraditionalType(
        key="nishinihon",
        label="Tây Nhật Bản",
        jp_label="西日本",
    ),
}


def get_game_spec(game: str) -> GameSpec:
    spec = GAME_SPECS.get(game)
    if not spec:
        raise KeyError(f"Unsupported game: {game}")
    return spec


def list_game_specs() -> List[GameSpec]:
    return [GAME_SPECS["miniloto"], GAME_SPECS["loto6"], GAME_SPECS["loto7"]]


def get_traditional_type(type_key: str) -> TraditionalType:
    lottery_type = TRADITIONAL_TYPES.get(type_key)
    if not lottery_type:
        raise KeyError(f"Unsupported traditional type: {type_key}")
    return lottery_type


def list_traditional_types() -> List[TraditionalType]:
    return [
        TRADITIONAL_TYPES["zenkoku"],
        TRADITIONAL_TYPES["jumbo"],
        TRADITIONAL_TYPES["tokyo"],
        TRADITIONAL_TYPES["kinki"],
        TRADITIONAL_TYPES["chiiki"],
        TRADITIONAL_TYPES["kct"],
        TRADITIONAL_TYPES["nishinihon"],
    ]
