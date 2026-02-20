from __future__ import annotations

import csv
import io
import re
from typing import List

import requests

from .models import (
    DrawResult,
    PrizeTier,
    TraditionalDrawResult,
    TraditionalPrizeRow,
    get_game_spec,
    get_traditional_type,
)

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
FULLWIDTH_SPACE = "\u3000"

BONUS_MARKER = "ボーナス数字"
CARRYOVER_LABEL = "キャリーオーバー"
SALES_LABEL = "販売実績額"
PAYMENT_LABEL = "支払期間"
SECTION_MARKER = "A01"


class LotteryDataError(RuntimeError):
    pass


class MizuhoLotteryClient:
    BASE_URL = "https://www.mizuhobank.co.jp"

    def __init__(self, timeout_seconds: int = 10):
        self._timeout = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
        )

    def get_latest_draw(self, game: str) -> DrawResult:
        filenames = self.get_recent_filenames(game, limit=1)
        if not filenames:
            raise LotteryDataError(f"Không tìm thấy kỳ quay mới nhất cho {game}")
        return self.get_draw_by_filename(game, filenames[0])

    def get_draw(self, game: str, draw_number: int) -> DrawResult:
        spec = get_game_spec(game)
        filename = f"A10{spec.prefix}{draw_number:04d}.CSV"
        return self.get_draw_by_filename(game, filename)

    def get_recent_filenames(self, game: str, limit: int = 10) -> List[str]:
        get_game_spec(game)
        url = f"{self.BASE_URL}/takarakuji/apl/txt/{game}/name.txt"
        text = self._download_text(url)
        rows = [line.strip() for line in text.splitlines() if line.strip()]
        filenames: List[str] = []
        for row in rows:
            match = re.search(r"(A\d+\.CSV)", row, flags=re.IGNORECASE)
            if match:
                filenames.append(match.group(1).upper())
            if len(filenames) >= limit:
                break
        return filenames

    def get_draw_by_filename(self, game: str, filename: str) -> DrawResult:
        get_game_spec(game)
        file_name = filename.upper().strip()
        if not re.fullmatch(r"A\d+\.CSV", file_name, flags=re.IGNORECASE):
            raise LotteryDataError(f"Tên file kỳ quay không hợp lệ: {filename}")

        source_url = f"{self.BASE_URL}/retail/takarakuji/loto/{game}/csv/{file_name}"
        text = self._download_text(source_url)
        return self._parse_loto_draw_csv(game=game, content=text, source_url=source_url)

    def extract_draw_number(self, filename: str) -> int:
        cleaned = filename.strip().upper()
        match = re.fullmatch(r"A10\d(\d{4})\.CSV", cleaned)
        if not match:
            raise LotteryDataError(f"Không tách được số kỳ quay từ filename: {filename}")
        return int(match.group(1))

    def get_latest_traditional_draw(self, lottery_type: str) -> TraditionalDrawResult:
        draws = self.get_traditional_draws(lottery_type=lottery_type, limit=1)
        if not draws:
            raise LotteryDataError(f"Không tìm thấy kết quả cho loại {lottery_type}")
        return draws[0]

    def get_traditional_draw(self, lottery_type: str, draw_order: int) -> TraditionalDrawResult:
        draws = self.get_traditional_draws(lottery_type=lottery_type)
        for draw in draws:
            if draw.draw_order == draw_order:
                return draw
        raise LotteryDataError(f"Không tìm thấy kỳ {draw_order} của loại {lottery_type}")

    def get_traditional_draws(self, lottery_type: str, limit: int | None = None) -> List[TraditionalDrawResult]:
        get_traditional_type(lottery_type)
        source_url = f"{self.BASE_URL}/retail/takarakuji/tsujyo/{lottery_type}/csv/{lottery_type}.csv"
        text = self._download_text(source_url)
        draws = self._parse_traditional_csv(lottery_type=lottery_type, content=text, source_url=source_url)
        return draws if limit is None else draws[:limit]

    def _download_text(self, url: str) -> str:
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LotteryDataError(f"Tải dữ liệu thất bại: {url}") from exc

        content = response.content
        for encoding in ("shift_jis", "cp932", "utf-8"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise LotteryDataError(f"Không giải mã được dữ liệu nguồn: {url}")

    def _parse_loto_draw_csv(self, game: str, content: str, source_url: str) -> DrawResult:
        rows = self._parse_csv_rows(content)
        if len(rows) < 4:
            raise LotteryDataError("Định dạng CSV loto không hợp lệ.")

        header = rows[1]
        draw_title = header[0] if len(header) > 0 else ""
        draw_date_jp = header[2] if len(header) > 2 else ""
        venue = header[3] if len(header) > 3 else ""
        draw_number = self._parse_draw_number_from_title(draw_title)
        payment_period = rows[2][1] if len(rows[2]) > 1 else ""

        numbers_line = rows[3]
        if BONUS_MARKER not in numbers_line:
            raise LotteryDataError("Không tìm thấy cột số bonus trong CSV.")
        bonus_index = numbers_line.index(BONUS_MARKER)
        main_numbers = [self._parse_number_token(token) for token in numbers_line[1:bonus_index]]
        bonus_numbers = [self._parse_number_token(token) for token in numbers_line[bonus_index + 1 :]]

        prize_tiers: List[PrizeTier] = []
        carryover = "-"
        sales_amount = "-"

        for row in rows[4:]:
            label = self._normalize_rank_label(row[0]) if row else ""
            if not label:
                continue
            if label == CARRYOVER_LABEL and len(row) > 1:
                carryover = row[1]
                continue
            if label == SALES_LABEL and len(row) > 1:
                sales_amount = row[1]
                continue

            if re.fullmatch(r"\d+等", label) and len(row) >= 3:
                if "申込数字" in (row[1] if len(row) > 1 else ""):
                    continue
                prize_tiers.append(
                    PrizeTier(
                        rank=label,
                        winners=row[-2],
                        amount=row[-1],
                    )
                )

        if not prize_tiers:
            raise LotteryDataError("Không parse được bảng hạng thưởng từ CSV loto.")

        return DrawResult(
            game=game,
            draw_number=draw_number,
            draw_title=draw_title,
            draw_date_jp=draw_date_jp,
            venue=venue,
            main_numbers=main_numbers,
            bonus_numbers=bonus_numbers,
            payment_period=payment_period,
            carryover=carryover,
            sales_amount=sales_amount,
            prize_tiers=prize_tiers,
            source_url=source_url,
        )

    def _parse_traditional_csv(
        self,
        lottery_type: str,
        content: str,
        source_url: str,
    ) -> List[TraditionalDrawResult]:
        rows = self._parse_csv_rows(content)
        sections: List[List[List[str]]] = []
        current: List[List[str]] = []

        for row in rows:
            first = row[0] if row else ""
            if first == SECTION_MARKER:
                if current:
                    sections.append(current)
                    current = []
                continue
            current.append(row)
        if current:
            sections.append(current)

        draws: List[TraditionalDrawResult] = []
        for section in sections:
            if len(section) < 2:
                continue
            header = section[0]
            draw_title = header[0] if len(header) > 0 else ""
            draw_subtitle = header[1] if len(header) > 1 else ""
            draw_date_jp = header[2] if len(header) > 2 else ""
            venue = header[3] if len(header) > 3 else ""
            draw_order = self._parse_draw_number_from_title(draw_title)

            payment_period = ""
            prize_rows: List[TraditionalPrizeRow] = []

            for row in section[1:]:
                if not row:
                    continue
                label = row[0]
                if label == PAYMENT_LABEL:
                    payment_period = row[1] if len(row) > 1 else ""
                    continue

                rank = row[0] if len(row) > 0 else ""
                amount = row[1] if len(row) > 1 else ""
                group = row[2] if len(row) > 2 else ""
                number = row[3] if len(row) > 3 else ""
                if rank:
                    prize_rows.append(
                        TraditionalPrizeRow(
                            rank=rank,
                            amount=amount,
                            group=group,
                            number=number,
                        )
                    )

            draws.append(
                TraditionalDrawResult(
                    lottery_type=lottery_type,
                    draw_order=draw_order,
                    draw_title=draw_title,
                    draw_subtitle=draw_subtitle,
                    draw_date_jp=draw_date_jp,
                    venue=venue,
                    payment_period=payment_period,
                    prize_rows=prize_rows,
                    source_url=source_url,
                )
            )
        return draws

    @staticmethod
    def _parse_csv_rows(content: str) -> List[List[str]]:
        reader = csv.reader(io.StringIO(content))
        rows: List[List[str]] = []
        for row in reader:
            cleaned_row = [MizuhoLotteryClient._normalize_cell(cell) for cell in row]
            if any(cleaned_row):
                rows.append(cleaned_row)
        return rows

    @staticmethod
    def _normalize_cell(cell: str) -> str:
        text = cell.replace(FULLWIDTH_SPACE, " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _normalize_rank_label(label: str) -> str:
        normalized = label.translate(FULLWIDTH_DIGITS)
        normalized = re.sub(r"\s+", "", normalized)
        return normalized

    @staticmethod
    def _parse_draw_number_from_title(draw_title: str) -> int:
        normalized = draw_title.translate(FULLWIDTH_DIGITS)
        match = re.search(r"第0*(\d+)回", normalized)
        if not match:
            raise LotteryDataError(f"Không parse được số kỳ từ tiêu đề: {draw_title}")
        return int(match.group(1))

    @staticmethod
    def _parse_number_token(token: str) -> int:
        normalized = token.translate(FULLWIDTH_DIGITS)
        match = re.search(r"\d+", normalized)
        if not match:
            raise LotteryDataError(f"Không parse được số trong CSV: {token}")
        return int(match.group(0))
