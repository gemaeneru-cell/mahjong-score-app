from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


WIND_NAMES = ["東", "南", "西", "北"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlayerState:
    id: str
    name: str
    seat: int
    score: int
    connected: bool = False


@dataclass
class RoomSettings:
    seats: int = 4
    initial_points: int = 25000
    approval_enabled: bool = False


@dataclass
class PendingAction:
    id: str
    action_type: str
    proposer_id: str
    description: str
    payload: dict
    approvals: set[str] = field(default_factory=set)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self, all_player_ids: list[str]) -> dict:
        remaining_ids = [pid for pid in all_player_ids if pid not in self.approvals]
        return {
            "id": self.id,
            "action_type": self.action_type,
            "proposer_id": self.proposer_id,
            "description": self.description,
            "payload": self.payload,
            "approvals": list(self.approvals),
            "remaining_approver_ids": remaining_ids,
            "created_at": self.created_at,
        }


@dataclass
class DrawContext:
    active: bool = False
    initiator_id: Optional[str] = None
    responses: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "initiator_id": self.initiator_id,
            "responses": self.responses,
        }


@dataclass
class RoomState:
    id: str
    settings: RoomSettings
    host_player_id: str
    players: dict[str, PlayerState] = field(default_factory=dict)
    current_wind_index: int = 0  # 東=0, 南=1
    hand_number: int = 1
    honba: int = 0
    kyotaku: int = 0
    initial_dealer_seat: int = 0
    dealer_seat: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    pending_action: Optional[PendingAction] = None
    draw_context: DrawContext = field(default_factory=DrawContext)
    history: list["RoomState"] = field(default_factory=list)
    finished: bool = False
    last_event: str = "ゲーム開始"

    def occupied_seats(self) -> set[int]:
        return {player.seat for player in self.players.values()}

    def sorted_players(self) -> list[PlayerState]:
        return sorted(self.players.values(), key=lambda player: player.seat)

    def player_ids_in_seat_order(self) -> list[str]:
        return [player.id for player in self.sorted_players()]
