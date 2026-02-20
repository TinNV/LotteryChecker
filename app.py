from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request

from lottery_checker import (
    LotteryDataError,
    MizuhoLotteryClient,
    TicketValidationError,
    check_ticket,
    check_traditional_ticket,
    get_game_spec,
    get_traditional_type,
    list_game_specs,
    list_traditional_types,
    parse_ticket_numbers,
    parse_traditional_ticket,
)

app = Flask(__name__)
client = MizuhoLotteryClient(timeout_seconds=15)


def _number_specs_payload() -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    for spec in list_game_specs():
        payload[f"number:{spec.key}"] = asdict(spec)
    return payload


def _build_game_options() -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    for spec in list_game_specs():
        options.append(
            {
                "value": f"number:{spec.key}",
                "label": f"{spec.label} (xổ số chọn số)",
            }
        )
    for lottery_type in list_traditional_types():
        options.append(
            {
                "value": f"traditional:{lottery_type.key}",
                "label": f"{lottery_type.label} ({lottery_type.jp_label})",
            }
        )
    return options


def _split_selected_game(selected_value: str) -> Tuple[str, str]:
    if ":" not in selected_value:
        return "traditional", "zenkoku"
    mode, key = selected_value.split(":", 1)
    if mode not in {"number", "traditional"}:
        return "traditional", "zenkoku"
    return mode, key


def _extract_number_ticket_rows() -> List[str]:
    rows = [item.strip() for item in request.form.getlist("tickets[]")]
    return rows if rows else [""]


def _extract_traditional_ticket_rows() -> List[Dict[str, str]]:
    groups = request.form.getlist("ticket_groups[]")
    numbers = request.form.getlist("ticket_numbers[]")
    row_count = max(len(groups), len(numbers), 1)
    rows: List[Dict[str, str]] = []
    for i in range(row_count):
        group = groups[i].strip() if i < len(groups) else ""
        number = numbers[i].strip() if i < len(numbers) else ""
        rows.append({"group": group, "number": number})
    return rows


def _sum_known_traditional_payout(results: List[Dict[str, Any]]) -> str:
    total = 0
    unknown = 0
    for row in results:
        if not row.get("winning"):
            continue
        value = row.get("payout_yen")
        if value is None:
            unknown += 1
        else:
            total += int(value)
    if unknown:
        return f"{total:,}円 + {unknown} vé chưa xác định"
    return f"{total:,}円"


def _build_history_entry(
    mode: str,
    selected_game: str,
    number_draw_result: Any,
    traditional_draw_result: Any,
    number_ticket_rows: List[str],
    traditional_ticket_rows: List[Dict[str, str]],
    number_ticket_results: List[Dict[str, Any]],
    traditional_ticket_results: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    if mode == "number":
        non_empty_rows = [row for row in number_ticket_rows if row.strip()]
        if not non_empty_rows:
            return None
        draw_no = number_draw_result.draw_number if number_draw_result else ""
        win_count = sum(1 for row in number_ticket_results if row.get("winning"))
        return {
            "mode": "number",
            "game": selected_game,
            "draw_number": str(draw_no),
            "tickets": [{"raw": row} for row in non_empty_rows],
            "summary": f"{win_count}/{len(non_empty_rows)} vé trúng",
        }

    non_empty_rows = [row for row in traditional_ticket_rows if row["group"] or row["number"]]
    if not non_empty_rows:
        return None
    draw_no = traditional_draw_result.draw_order if traditional_draw_result else ""
    win_count = sum(1 for row in traditional_ticket_results if row.get("winning"))
    return {
        "mode": "traditional",
        "game": selected_game,
        "draw_number": str(draw_no),
        "tickets": [{"group": row["group"], "number": row["number"]} for row in non_empty_rows],
        "summary": f"{win_count}/{len(non_empty_rows)} vé trúng",
    }


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    game_options = _build_game_options()
    selected_game = request.values.get("game", "traditional:zenkoku")
    draw_number_input = request.values.get("draw_number", "").strip()
    number_ticket_rows = _extract_number_ticket_rows() if request.method == "POST" else [""]
    traditional_ticket_rows = (
        _extract_traditional_ticket_rows() if request.method == "POST" else [{"group": "", "number": ""}]
    )

    mode, game_key = _split_selected_game(selected_game)
    error = ""
    number_draw_result = None
    traditional_draw_result = None
    number_ticket_results: List[Dict[str, Any]] = []
    traditional_ticket_results: List[Dict[str, Any]] = []
    recent_draw_numbers: List[int] = []
    win_popup_lines: List[str] = []
    history_entry: Dict[str, Any] | None = None

    try:
        if mode == "number":
            game_spec = get_game_spec(game_key)

            recent_files = client.get_recent_filenames(game_key, limit=10)
            for name in recent_files:
                try:
                    recent_draw_numbers.append(client.extract_draw_number(name))
                except LotteryDataError:
                    continue

            if draw_number_input:
                draw_number = int(draw_number_input)
                if draw_number <= 0:
                    raise ValueError
                number_draw_result = client.get_draw(game_key, draw_number)
            else:
                number_draw_result = client.get_latest_draw(game_key)

            for index, raw_ticket in enumerate(number_ticket_rows, start=1):
                if not raw_ticket:
                    continue
                try:
                    ticket_numbers = parse_ticket_numbers(
                        raw_input=raw_ticket,
                        expected_count=game_spec.picks,
                        min_number=game_spec.min_number,
                        max_number=game_spec.max_number,
                    )
                    checked = check_ticket(
                        game_spec=game_spec,
                        draw=number_draw_result,
                        ticket_numbers=ticket_numbers,
                    )
                    row_data = {
                        "index": index,
                        "raw": raw_ticket,
                        "rank": checked.rank,
                        "winning": checked.winning,
                        "matched_main": checked.matched_main,
                        "matched_bonus": checked.matched_bonus,
                        "payout": checked.payout_amount,
                        "error": "",
                    }
                    number_ticket_results.append(row_data)
                    if checked.winning:
                        win_popup_lines.append(
                            f"Vé #{index} trúng {checked.rank} ({checked.payout_amount})"
                        )
                except TicketValidationError as exc:
                    number_ticket_results.append(
                        {
                            "index": index,
                            "raw": raw_ticket,
                            "rank": "-",
                            "winning": False,
                            "matched_main": [],
                            "matched_bonus": [],
                            "payout": "-",
                            "error": str(exc),
                        }
                    )
        else:
            get_traditional_type(game_key)
            recent_draws = client.get_traditional_draws(game_key, limit=10)
            recent_draw_numbers = [draw.draw_order for draw in recent_draws]

            if draw_number_input:
                draw_number = int(draw_number_input)
                if draw_number <= 0:
                    raise ValueError
                traditional_draw_result = client.get_traditional_draw(game_key, draw_number)
            else:
                traditional_draw_result = (
                    recent_draws[0] if recent_draws else client.get_latest_traditional_draw(game_key)
                )

            for index, row in enumerate(traditional_ticket_rows, start=1):
                raw_group = row["group"]
                raw_number = row["number"]
                if not raw_group and not raw_number:
                    continue
                try:
                    ticket_group, ticket_number = parse_traditional_ticket(
                        group_raw=raw_group,
                        number_raw=raw_number,
                    )
                    checked = check_traditional_ticket(
                        draw=traditional_draw_result,
                        ticket_group=ticket_group,
                        ticket_number=ticket_number,
                    )
                    row_data = {
                        "index": index,
                        "group": ticket_group,
                        "number": ticket_number,
                        "winning": checked.winning,
                        "payout_display": checked.total_payout_display,
                        "payout_yen": checked.total_payout_yen,
                        "matches": checked.matches,
                        "error": "",
                    }
                    traditional_ticket_results.append(row_data)
                    if checked.winning:
                        win_popup_lines.append(
                            f"Vé #{index} (tổ {ticket_group}, số {ticket_number}) trúng {checked.total_payout_display}"
                        )
                except TicketValidationError as exc:
                    traditional_ticket_results.append(
                        {
                            "index": index,
                            "group": raw_group,
                            "number": raw_number,
                            "winning": False,
                            "payout_display": "-",
                            "payout_yen": 0,
                            "matches": [],
                            "error": str(exc),
                        }
                    )

        if request.method == "POST":
            history_entry = _build_history_entry(
                mode=mode,
                selected_game=selected_game,
                number_draw_result=number_draw_result,
                traditional_draw_result=traditional_draw_result,
                number_ticket_rows=number_ticket_rows,
                traditional_ticket_rows=traditional_ticket_rows,
                number_ticket_results=number_ticket_results,
                traditional_ticket_results=traditional_ticket_results,
            )

    except ValueError:
        error = "Kỳ quay phải là số nguyên dương."
    except LotteryDataError as exc:
        error = f"Không tải được dữ liệu từ web: {exc}"
    except Exception as exc:  # pragma: no cover
        error = f"Lỗi không xác định: {exc}"

    show_win_popup = request.method == "POST" and len(win_popup_lines) > 0 and not error

    return render_template(
        "index.html",
        game_options=game_options,
        selected_game=selected_game,
        selected_mode=mode,
        draw_number_input=draw_number_input,
        number_ticket_rows=number_ticket_rows,
        traditional_ticket_rows=traditional_ticket_rows,
        number_draw_result=number_draw_result,
        traditional_draw_result=traditional_draw_result,
        number_ticket_results=number_ticket_results,
        traditional_ticket_results=traditional_ticket_results,
        number_win_count=sum(1 for row in number_ticket_results if row["winning"]),
        traditional_win_count=sum(1 for row in traditional_ticket_results if row["winning"]),
        traditional_total_payout=_sum_known_traditional_payout(traditional_ticket_results),
        error=error,
        recent_draw_numbers=recent_draw_numbers,
        number_specs=_number_specs_payload(),
        show_win_popup=show_win_popup,
        win_popup_lines=win_popup_lines,
        history_entry=history_entry,
    )


@app.get("/health")
def health() -> tuple[Dict[str, str], int]:
    return {"status": "ok"}, 200


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "5000"))
    except ValueError:
        port = 5000
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
