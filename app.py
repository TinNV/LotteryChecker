from __future__ import annotations

from dataclasses import asdict
import os
from time import perf_counter
from typing import Any, Dict, List, Tuple

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency fallback
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False
from flask import Flask, Response, render_template, request

from lottery_checker.analytics import TrafficTracker, create_search_store_from_env

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

app = Flask(__name__)
client = MizuhoLotteryClient(timeout_seconds=15)
traffic_tracker = TrafficTracker(max_recent=500)
search_store = create_search_store_from_env()


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"


def _is_local_admin_request() -> bool:
    host = (request.host or "").split(":", 1)[0].strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _admin_auth_guard() -> Response | None:
    expected_user = os.environ.get("ADMIN_USER", "admin").strip() or "admin"
    expected_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if (not expected_password) and _is_local_admin_request():
        expected_password = "admin_P@ssw0rd"

    if not expected_password:
        return Response("Admin password is not configured.", status=503, mimetype="text/plain")

    auth = request.authorization
    if auth and auth.username == expected_user and auth.password == expected_password:
        return None

    response = Response("Authentication required.", status=401, mimetype="text/plain")
    response.headers["WWW-Authenticate"] = 'Basic realm="LotteryChecker Admin"'
    return response


def _persist_search_history(
    *,
    history_entry: Dict[str, Any] | None,
    number_ticket_results: List[Dict[str, Any]],
    traditional_ticket_results: List[Dict[str, Any]],
) -> None:
    if search_store is None or history_entry is None:
        return

    mode = str(history_entry.get("mode", ""))
    game = str(history_entry.get("game", ""))
    draw_number = str(history_entry.get("draw_number", ""))
    summary = str(history_entry.get("summary", ""))
    ticket_count = len(history_entry.get("tickets") or [])
    if mode == "number":
        winning_count = sum(1 for row in number_ticket_results if row.get("winning"))
    else:
        winning_count = sum(1 for row in traditional_ticket_results if row.get("winning"))

    try:
        search_store.save_search(
            mode=mode,
            game=game,
            draw_number=draw_number,
            summary=summary,
            ticket_count=ticket_count,
            winning_count=winning_count,
            client_ip=_client_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
    except Exception:
        # Search persistence should never break the page response.
        return


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


def _extract_yen_amount(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _format_payout_summary(total: int, unknown: int) -> str:
    if unknown:
        return f"{total:,}円 + {unknown} vé chưa xác định"
    return f"{total:,}円"


def _sum_known_number_payout(results: List[Dict[str, Any]]) -> str:
    total = 0
    unknown = 0
    for row in results:
        if not row.get("winning"):
            continue
        value = _extract_yen_amount(row.get("payout"))
        if value is None:
            unknown += 1
        else:
            total += value
    return _format_payout_summary(total, unknown)


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
    return _format_payout_summary(total, unknown)


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
        ticket_total = len(non_empty_rows)
        win_count = sum(1 for row in number_ticket_results if row.get("winning"))
        payout_summary = _sum_known_number_payout(number_ticket_results)
        return {
            "mode": "number",
            "game": selected_game,
            "draw_number": str(draw_no),
            "tickets": [{"raw": row} for row in non_empty_rows],
            "summary": f"{ticket_total} vé | {win_count} trúng | Thưởng: {payout_summary}",
        }

    non_empty_rows = [row for row in traditional_ticket_rows if row["group"] or row["number"]]
    if not non_empty_rows:
        return None
    draw_no = traditional_draw_result.draw_order if traditional_draw_result else ""
    ticket_total = len(non_empty_rows)
    win_count = sum(1 for row in traditional_ticket_results if row.get("winning"))
    payout_summary = _sum_known_traditional_payout(traditional_ticket_results)
    return {
        "mode": "traditional",
        "game": selected_game,
        "draw_number": str(draw_no),
        "tickets": [{"group": row["group"], "number": row["number"]} for row in non_empty_rows],
        "summary": f"{ticket_total} vé | {win_count} trúng | Thưởng: {payout_summary}",
    }


@app.before_request
def _track_request_start() -> None:
    request.environ["lottery_checker.request_start"] = perf_counter()


@app.after_request
def _track_request_end(response: Response) -> Response:
    start = request.environ.get("lottery_checker.request_start")
    duration_ms = int((perf_counter() - start) * 1000) if isinstance(start, float) else 0
    traffic_tracker.record(
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        ip=_client_ip(),
        duration_ms=duration_ms,
        accept=request.headers.get("Accept", ""),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return response


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

    if request.method == "POST" and not error:
        _persist_search_history(
            history_entry=history_entry,
            number_ticket_results=number_ticket_results,
            traditional_ticket_results=traditional_ticket_results,
        )

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


@app.get("/admin")
def admin() -> Response | str:
    auth_failed = _admin_auth_guard()
    if auth_failed is not None:
        return auth_failed

    traffic = traffic_tracker.snapshot(top_paths=15, recent_limit=80)
    recent_searches = search_store.list_recent_searches(limit=100) if search_store else []
    search_store_enabled = bool(search_store and search_store.enabled)
    dynamo_status_detail = ""
    if not search_store:
        table_name = os.environ.get("DYNAMODB_SEARCH_TABLE", "").strip()
        if not table_name:
            dynamo_status_detail = "DYNAMODB_SEARCH_TABLE is empty"
        else:
            region_name = os.environ.get("AWS_REGION", "").strip() or os.environ.get("AWS_DEFAULT_REGION", "").strip()
            if not region_name:
                region_name = "ap-northeast-1"
            dynamo_status_detail = f"Failed to initialize store (table={table_name}, region={region_name})"
    elif not search_store.enabled:
        dynamo_status_detail = str(getattr(search_store, "last_error", "")).strip()

    return render_template(
        "admin.html",
        traffic=traffic,
        recent_searches=recent_searches,
        search_store_enabled=search_store_enabled,
        dynamo_table_name=search_store.table_name if search_store else "",
        search_ttl_days=search_store.ttl_days if search_store else 0,
        dynamo_status_detail=dynamo_status_detail,
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
