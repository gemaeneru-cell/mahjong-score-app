from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Optional


LIMIT_NAMES = {
    2000: "満貫",
    3000: "跳満",
    4000: "倍満",
    6000: "三倍満",
    8000: "数え役満",
}


@dataclass(frozen=True)
class ScoreBreakdown:
    """4人麻雀基準の点数内訳。

    * ron_value: ロン時に放銃者が支払う点数
    * tsumo_child_payment: ツモ時に子が支払う点数（親アガリ時は全員この値）
    * tsumo_dealer_payment: 子アガリ時に親が支払う点数

    3人打ちのツモ損は、実在する支払者だけにこの標準支払額を適用することで表現する。
    つまり「北家分」は補填しない。
    """

    han: int
    fu: int
    base_points: int
    limit_name: Optional[str]
    winner_is_dealer: bool
    ron_value: int
    tsumo_child_payment: int
    tsumo_dealer_payment: int


@dataclass(frozen=True)
class SettlementResult:
    transfers: dict[int, int]
    breakdown: ScoreBreakdown


class ScoreCalculationError(ValueError):
    pass


def round_up_100(value: int) -> int:
    return int(math.ceil(value / 100.0) * 100)


def calculate_base_points(han: int, fu: int) -> tuple[int, Optional[str]]:
    if han <= 0:
        raise ScoreCalculationError("翻数は1以上である必要があります。")
    if fu <= 0:
        raise ScoreCalculationError("符は1以上である必要があります。")

    # 制限役
    if han >= 13:
        return 8000, LIMIT_NAMES[8000]
    if han >= 11:
        return 6000, LIMIT_NAMES[6000]
    if han >= 8:
        return 4000, LIMIT_NAMES[4000]
    if han >= 6:
        return 3000, LIMIT_NAMES[3000]
    if han == 5 or (han == 4 and fu >= 40) or (han == 3 and fu >= 70):
        return 2000, LIMIT_NAMES[2000]

    base_points = fu * (2 ** (han + 2))
    return min(base_points, 2000), LIMIT_NAMES[2000] if base_points >= 2000 else None


def calculate_hand_score(han: int, fu: int, winner_is_dealer: bool) -> ScoreBreakdown:
    """翻・符からリーチ麻雀の標準支払点を計算する。"""

    base_points, limit_name = calculate_base_points(han, fu)

    if winner_is_dealer:
        ron_value = round_up_100(base_points * 6)
        tsumo_each = round_up_100(base_points * 2)
        return ScoreBreakdown(
            han=han,
            fu=fu,
            base_points=base_points,
            limit_name=limit_name,
            winner_is_dealer=True,
            ron_value=ron_value,
            tsumo_child_payment=tsumo_each,
            tsumo_dealer_payment=tsumo_each,
        )

    ron_value = round_up_100(base_points * 4)
    tsumo_child_payment = round_up_100(base_points)
    tsumo_dealer_payment = round_up_100(base_points * 2)
    return ScoreBreakdown(
        han=han,
        fu=fu,
        base_points=base_points,
        limit_name=limit_name,
        winner_is_dealer=False,
        ron_value=ron_value,
        tsumo_child_payment=tsumo_child_payment,
        tsumo_dealer_payment=tsumo_dealer_payment,
    )


def settle_win(
    *,
    player_count: int,
    winner_seat: int,
    dealer_seat: int,
    han: int,
    fu: int,
    win_type: str,
    honba: int,
    kyotaku: int,
    ron_from_seat: Optional[int] = None,
) -> SettlementResult:
    """アガリ時の点数移動を seat -> delta の辞書で返す。"""

    if player_count not in (3, 4):
        raise ScoreCalculationError("player_count は 3 または 4 のみ対応です。")
    if win_type not in {"ron", "tsumo"}:
        raise ScoreCalculationError("win_type は 'ron' または 'tsumo' を指定してください。")
    if win_type == "ron" and ron_from_seat is None:
        raise ScoreCalculationError("ロン時は放銃者の seat が必要です。")
    if win_type == "ron" and ron_from_seat == winner_seat:
        raise ScoreCalculationError("放銃者とアガリ者は同一にできません。")

    breakdown = calculate_hand_score(han=han, fu=fu, winner_is_dealer=(winner_seat == dealer_seat))
    transfers = defaultdict(int)

    if win_type == "ron":
        amount = breakdown.ron_value + honba * 300
        transfers[winner_seat] += amount
        transfers[ron_from_seat] -= amount
    else:
        # 4人打ちでは通常のツモ支払い、3人打ちでは実在する2人だけが支払う。
        # これにより「北家分は引かれる」= ツモ損を表現している。
        for payer_seat in range(player_count):
            if payer_seat == winner_seat:
                continue
            if winner_seat == dealer_seat:
                amount = breakdown.tsumo_child_payment + honba * 100
            else:
                amount = (
                    breakdown.tsumo_dealer_payment + honba * 100
                    if payer_seat == dealer_seat
                    else breakdown.tsumo_child_payment + honba * 100
                )
            transfers[winner_seat] += amount
            transfers[payer_seat] -= amount

    if kyotaku > 0:
        transfers[winner_seat] += kyotaku * 1000

    return SettlementResult(transfers=dict(transfers), breakdown=breakdown)


def settle_exhaustive_draw(*, player_count: int, tenpai_seats: list[int]) -> dict[int, int]:
    """流局時のノーテン罰符（合計3000点）を seat -> delta で返す。"""

    if player_count not in (3, 4):
        raise ScoreCalculationError("player_count は 3 または 4 のみ対応です。")

    tenpai_set = set(tenpai_seats)
    all_seats = set(range(player_count))
    noten_set = all_seats - tenpai_set

    if not tenpai_set or not noten_set:
        return {seat: 0 for seat in range(player_count)}

    total = 3000
    receive_each = total // len(tenpai_set)
    pay_each = total // len(noten_set)
    transfers = {seat: 0 for seat in range(player_count)}

    for seat in tenpai_set:
        transfers[seat] += receive_each
    for seat in noten_set:
        transfers[seat] -= pay_each

    return transfers
