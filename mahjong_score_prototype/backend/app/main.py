from __future__ import annotations

import copy
import random
import string
import uuid
from pathlib import Path
from typing import Any, Optional

import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import DrawContext, PendingAction, PlayerState, RoomSettings, RoomState, WIND_NAMES
from .scoring import ScoreCalculationError, settle_exhaustive_draw, settle_win


ROOMS: dict[str, RoomState] = {}
SID_TO_PLAYER: dict[str, tuple[str, str]] = {}

STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Realtime Mahjong Scoreboard Prototype")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)


class CreateRoomRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    seats: int = Field(default=4)
    initial_points: int = Field(default=25000, ge=-999999, le=999999)
    approval_enabled: bool = False
    requested_seat: Optional[str] = Field(default="")


class RoomResponse(BaseModel):
    room_id: str
    player_id: str
    join_url: str


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def new_room_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(alphabet) for _ in range(length))
        if code not in ROOMS:
            return code


def get_room_or_raise(room_id: str) -> RoomState:
    room = ROOMS.get(room_id)
    if room is None:
        raise ValueError("ルームが見つかりません。")
    return room


def get_player_or_raise(room: RoomState, player_id: str) -> PlayerState:
    player = room.players.get(player_id)
    if player is None:
        raise ValueError("プレイヤーが見つかりません。")
    return player


def get_context_by_sid(sid: str) -> tuple[RoomState, PlayerState]:
    if sid not in SID_TO_PLAYER:
        raise ValueError("先にルームへ参加してください。")
    room_id, player_id = SID_TO_PLAYER[sid]
    room = get_room_or_raise(room_id)
    player = get_player_or_raise(room, player_id)
    return room, player


def choose_seat(room: RoomState, requested_seat: Optional[int]) -> int:
    occupied = room.occupied_seats()
    if requested_seat is not None and 0 <= requested_seat < room.settings.seats and requested_seat not in occupied:
        return requested_seat
    for seat in range(room.settings.seats):
        if seat not in occupied:
            return seat
    raise ValueError("空いている席がありません。")


def ensure_room_ready(room: RoomState) -> None:
    if len(room.players) != room.settings.seats:
        raise ValueError(f"{room.settings.seats}人そろってから開始してください。")


def ensure_no_pending_action(room: RoomState) -> None:
    if room.pending_action is not None:
        raise ValueError("未承認の操作があります。")


def ensure_not_in_draw_input(room: RoomState) -> None:
    if room.draw_context.active:
        raise ValueError("流局入力の受付中です。")


def ensure_game_not_finished(room: RoomState) -> None:
    if room.finished:
        raise ValueError("このゲームは終了しています。原点戻しで再開できます。")


def require_host(room: RoomState, player: PlayerState) -> None:
    if player.id != room.host_player_id:
        raise ValueError("この操作はホストのみ実行できます。")


def require_dealer(room: RoomState, player: PlayerState) -> None:
    if player.seat != room.dealer_seat:
        raise ValueError("流局入力の開始は現在の親のみ実行できます。")


def push_undo_snapshot(room: RoomState) -> None:
    snapshot = copy.deepcopy(room)
    snapshot.history = []
    room.history = [snapshot]


def restore_last_snapshot(room_id: str) -> RoomState:
    room = get_room_or_raise(room_id)
    if not room.history:
        raise ValueError("Undoできる履歴がありません。")
    restored = copy.deepcopy(room.history[-1])
    restored.history = []
    ROOMS[room_id] = restored
    return restored


def current_round_label(room: RoomState) -> str:
    wind = WIND_NAMES[min(room.current_wind_index, 1)]
    return f"{wind}{room.hand_number}局"


def is_final_hand(room: RoomState) -> bool:
    return room.current_wind_index >= 1 and room.hand_number >= room.settings.seats


def advance_hand(room: RoomState, dealer_continues: bool) -> None:
    if dealer_continues:
        room.honba += 1
        return

    if is_final_hand(room):
        room.finished = True
        room.kyotaku = 0  # オーラス終了で残供託は消滅
        return

    room.honba = 0
    room.dealer_seat = (room.dealer_seat + 1) % room.settings.seats
    room.hand_number += 1
    if room.hand_number > room.settings.seats:
        room.hand_number = 1
        room.current_wind_index += 1


def distance_from_initial_dealer(room: RoomState, seat: int) -> int:
    return (seat - room.initial_dealer_seat) % room.settings.seats


def current_player_wind(room: RoomState, seat: int) -> str:
    order = WIND_NAMES[: room.settings.seats]
    return order[(seat - room.dealer_seat) % room.settings.seats]


def rank_map(room: RoomState) -> dict[str, int]:
    ordered = sorted(
        room.players.values(),
        key=lambda p: (-p.score, distance_from_initial_dealer(room, p.seat)),
    )
    return {player.id: index + 1 for index, player in enumerate(ordered)}


def action_description(room: RoomState, action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "reach":
        player = get_player_or_raise(room, payload["player_id"])
        return f"{player.name} がリーチ"
    if action_type == "win":
        winner = get_player_or_raise(room, payload["winner_id"])
        han = payload["han"]
        fu = payload["fu"]
        if payload["win_type"] == "ron":
            loser = get_player_or_raise(room, payload["from_player_id"])
            return f"{winner.name} が {loser.name} からロン（{han}翻 {fu}符）"
        return f"{winner.name} がツモ（{han}翻 {fu}符）"
    if action_type == "host_adjust":
        target = get_player_or_raise(room, payload["target_player_id"])
        return f"{target.name} の点数を {payload['new_score']} 点へ修正"
    if action_type == "reset_scores":
        return "原点戻し"
    if action_type == "draw_settlement":
        tenpai_ids = payload["tenpai_player_ids"]
        names = [get_player_or_raise(room, pid).name for pid in tenpai_ids]
        return f"流局精算（聴牌: {', '.join(names) if names else 'なし'}）"
    return action_type


def apply_transfers_by_seat(room: RoomState, transfers_by_seat: dict[int, int]) -> None:
    seat_to_player = {player.seat: player for player in room.players.values()}
    for seat, delta in transfers_by_seat.items():
        seat_to_player[seat].score += delta


def apply_action(room: RoomState, action_type: str, payload: dict[str, Any], actor_id: str) -> str:
    push_undo_snapshot(room)

    if action_type == "reach":
        player = get_player_or_raise(room, payload["player_id"])
        player.score -= 1000
        room.kyotaku += 1
        room.last_event = f"{player.name} がリーチ"
        return room.last_event

    if action_type == "win":
        winner = get_player_or_raise(room, payload["winner_id"])
        from_player_id = payload.get("from_player_id")
        from_player = get_player_or_raise(room, from_player_id) if from_player_id else None
        settlement = settle_win(
            player_count=room.settings.seats,
            winner_seat=winner.seat,
            dealer_seat=room.dealer_seat,
            han=int(payload["han"]),
            fu=int(payload["fu"]),
            win_type=payload["win_type"],
            honba=room.honba,
            kyotaku=room.kyotaku,
            ron_from_seat=from_player.seat if from_player else None,
        )
        apply_transfers_by_seat(room, settlement.transfers)
        room.kyotaku = 0
        dealer_continues = winner.seat == room.dealer_seat
        label = settlement.breakdown.limit_name or f"{settlement.breakdown.han}翻 {settlement.breakdown.fu}符"
        room.last_event = (
            f"{winner.name} が {from_player.name} からロン（{label}）"
            if from_player
            else f"{winner.name} がツモ（{label}）"
        )
        advance_hand(room, dealer_continues=dealer_continues)
        return room.last_event

    if action_type == "host_adjust":
        target = get_player_or_raise(room, payload["target_player_id"])
        target.score = int(payload["new_score"])
        room.last_event = f"{target.name} の点数を {target.score} 点に修正"
        return room.last_event

    if action_type == "reset_scores":
        for player in room.players.values():
            player.score = room.settings.initial_points
        room.current_wind_index = 0
        room.hand_number = 1
        room.honba = 0
        room.kyotaku = 0
        room.initial_dealer_seat = 0
        room.dealer_seat = 0
        room.pending_action = None
        room.draw_context = DrawContext()
        room.finished = False
        room.last_event = "原点戻しを実行"
        return room.last_event

    if action_type == "draw_settlement":
        tenpai_player_ids: list[str] = payload["tenpai_player_ids"]
        tenpai_seats = [get_player_or_raise(room, pid).seat for pid in tenpai_player_ids]
        transfers = settle_exhaustive_draw(player_count=room.settings.seats, tenpai_seats=tenpai_seats)
        apply_transfers_by_seat(room, transfers)
        dealer_player = next(player for player in room.players.values() if player.seat == room.dealer_seat)
        dealer_continues = dealer_player.id in tenpai_player_ids
        names = [get_player_or_raise(room, pid).name for pid in tenpai_player_ids]
        room.last_event = f"流局精算（聴牌: {', '.join(names) if names else 'なし'}）"
        room.draw_context = DrawContext()
        advance_hand(room, dealer_continues=dealer_continues)
        return room.last_event

    raise ValueError(f"未対応の action_type です: {action_type}")


def room_to_dict(room: RoomState) -> dict[str, Any]:
    players = room.sorted_players()
    ranks = rank_map(room)
    top_score = max((player.score for player in players), default=0)
    all_player_ids = room.player_ids_in_seat_order()

    return {
        "id": room.id,
        "settings": {
            "seats": room.settings.seats,
            "initial_points": room.settings.initial_points,
            "approval_enabled": room.settings.approval_enabled,
        },
        "ready": len(players) == room.settings.seats,
        "players_joined": len(players),
        "players_needed": max(0, room.settings.seats - len(players)),
        "current_round": current_round_label(room),
        "current_wind_index": room.current_wind_index,
        "hand_number": room.hand_number,
        "honba": room.honba,
        "kyotaku": room.kyotaku,
        "dealer_seat": room.dealer_seat,
        "initial_dealer_seat": room.initial_dealer_seat,
        "finished": room.finished,
        "has_undo": bool(room.history),
        "last_event": room.last_event,
        "available_seats": [seat for seat in range(room.settings.seats) if seat not in room.occupied_seats()],
        "players": [
            {
                "id": player.id,
                "name": player.name,
                "seat": player.seat,
                "score": player.score,
                "rank": ranks[player.id],
                "gap_to_top": top_score - player.score,
                "connected": player.connected,
                "is_host": player.id == room.host_player_id,
                "is_dealer": player.seat == room.dealer_seat,
                "current_wind": current_player_wind(room, player.seat),
                "tie_break_order": distance_from_initial_dealer(room, player.seat),
            }
            for player in players
        ],
        "host_player_id": room.host_player_id,
        "pending_action": room.pending_action.to_dict(all_player_ids) if room.pending_action else None,
        "draw_context": room.draw_context.to_dict(),
    }


async def emit_room_state(room: RoomState) -> None:
    await sio.emit("room_state", room_to_dict(room), room=room.id)


async def emit_toast(room: RoomState, message: str) -> None:
    await sio.emit("toast", {"message": message}, room=room.id)


async def queue_or_apply_action(
    room: RoomState,
    proposer: PlayerState,
    action_type: str,
    payload: dict[str, Any],
    *,
    bypass_approval: bool = False,
) -> dict[str, Any]:
    description = action_description(room, action_type, payload)

    if room.settings.approval_enabled and not bypass_approval:
        if room.pending_action is not None:
            raise ValueError("未承認の操作があります。")
        room.pending_action = PendingAction(
            id=new_id("pending"),
            action_type=action_type,
            proposer_id=proposer.id,
            description=description,
            payload=payload,
            approvals={proposer.id},
        )
        room.last_event = f"承認待ち: {description}"
        await emit_room_state(room)
        await emit_toast(room, f"承認待ち: {description}")
        return {"queued": True, "pending_action_id": room.pending_action.id}

    message = apply_action(room, action_type, payload, proposer.id)
    await emit_room_state(room)
    await emit_toast(room, message)
    return {"queued": False, "message": message}


@app.get("/")
async def index() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html が見つかりません。")
    return FileResponse(index_file)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/rooms", response_model=RoomResponse)
async def create_room(payload: CreateRoomRequest) -> RoomResponse:
    if payload.seats not in (3, 4):
        raise HTTPException(status_code=400, detail="人数は3人または4人を指定してください。")

    room_id = new_room_code()
    host_player_id = new_id("player")
    
    req_seat_int = int(payload.requested_seat) if payload.requested_seat and payload.requested_seat.isdigit() else 0

    room = RoomState(
        id=room_id,
        settings=RoomSettings(
            seats=payload.seats,
            initial_points=payload.initial_points,
            approval_enabled=payload.approval_enabled,
        ),
        host_player_id=host_player_id,
        initial_dealer_seat=0,
        dealer_seat=0,
        last_event="ゲーム作成完了",
    )
    room.players[host_player_id] = PlayerState(
        id=host_player_id,
        name=payload.name.strip(),
        seat=req_seat_int,
        score=payload.initial_points,
        connected=False,
    )
    ROOMS[room_id] = room
    return RoomResponse(room_id=room_id, player_id=host_player_id, join_url=f"/?room={room_id}")


@app.get("/api/rooms/{room_id}")
async def get_room(room_id: str) -> dict[str, Any]:
    try:
        room = get_room_or_raise(room_id)
        return room_to_dict(room)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@sio.event
async def connect(sid: str, environ: dict, auth: Optional[dict]) -> None:
    return None


@sio.event
async def disconnect(sid: str) -> None:
    context = SID_TO_PLAYER.pop(sid, None)
    if not context:
        return
    room_id, player_id = context
    room = ROOMS.get(room_id)
    if room and player_id in room.players:
        room.players[player_id].connected = False
        await emit_room_state(room)


@sio.event
async def join_room(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room_id = str(data.get("room_id", "")).strip().upper()
        room = get_room_or_raise(room_id)
        name = str(data.get("name", "")).strip() or "Player"
        requested_seat = data.get("requested_seat")
        requested_seat = int(requested_seat) if requested_seat not in (None, "") else None
        existing_player_id = data.get("player_id")

        if existing_player_id and existing_player_id in room.players:
            player = room.players[existing_player_id]
            player.name = name or player.name
        else:
            if len(room.players) >= room.settings.seats:
                raise ValueError("このルームは満席です。")
            seat = choose_seat(room, requested_seat)
            player = PlayerState(
                id=new_id("player"),
                name=name,
                seat=seat,
                score=room.settings.initial_points,
                connected=True,
            )
            room.players[player.id] = player

        player.connected = True
        SID_TO_PLAYER[sid] = (room.id, player.id)
        await sio.enter_room(sid, room.id)
        await emit_room_state(room)
        return {"ok": True, "player_id": player.id, "room": room_to_dict(room)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def submit_reach(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_game_not_finished(room)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)
        result = await queue_or_apply_action(room, player, "reach", {"player_id": player.id})
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def submit_win(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_game_not_finished(room)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)

        payload = {
            "winner_id": player.id,
            "win_type": str(data.get("win_type", "")).lower(),
            "han": int(data.get("han")),
            "fu": int(data.get("fu")),
        }
        from_player_id = data.get("from_player_id")
        if payload["win_type"] == "ron":
            if not from_player_id:
                raise ValueError("ロン時は放銃者を選択してください。")
            if from_player_id == player.id:
                raise ValueError("放銃者に自分は選べません。")
            payload["from_player_id"] = from_player_id
        result = await queue_or_apply_action(room, player, "win", payload)
        return {"ok": True, **result}
    except (ValueError, ScoreCalculationError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def start_draw(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_game_not_finished(room)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)
        require_dealer(room, player)
        room.draw_context = DrawContext(active=True, initiator_id=player.id, responses={})
        room.last_event = f"{player.name} が流局入力を開始"
        await emit_room_state(room)
        await emit_toast(room, room.last_event)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def submit_draw_status(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_game_not_finished(room)
        if not room.draw_context.active:
            raise ValueError("現在、流局入力は開始されていません。")

        tenpai = bool(data.get("tenpai"))
        room.draw_context.responses[player.id] = tenpai

        if len(room.draw_context.responses) == room.settings.seats:
            tenpai_player_ids = [pid for pid, is_tenpai in room.draw_context.responses.items() if is_tenpai]
            message = apply_action(
                room,
                "draw_settlement",
                {"tenpai_player_ids": tenpai_player_ids},
                actor_id=player.id,
            )
            await emit_room_state(room)
            await emit_toast(room, message)
            return {"ok": True, "completed": True, "message": message}

        await emit_room_state(room)
        return {"ok": True, "completed": False}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def approve_action(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        if room.pending_action is None:
            raise ValueError("承認待ちの操作はありません。")

        room.pending_action.approvals.add(player.id)
        all_player_ids = set(room.players.keys())
        if room.pending_action.approvals >= all_player_ids:
            pending = room.pending_action
            room.pending_action = None
            message = apply_action(room, pending.action_type, pending.payload, actor_id=pending.proposer_id)
            await emit_room_state(room)
            await emit_toast(room, f"承認完了: {message}")
            return {"ok": True, "applied": True, "message": message}

        await emit_room_state(room)
        return {"ok": True, "applied": False}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def reject_action(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        if room.pending_action is None:
            raise ValueError("承認待ちの操作はありません。")
        description = room.pending_action.description
        room.pending_action = None
        room.last_event = f"{player.name} が操作を差し戻し: {description}"
        await emit_room_state(room)
        await emit_toast(room, room.last_event)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def undo_last(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)
        restored = restore_last_snapshot(room.id)
        restored.last_event = f"{player.name} が1手戻しました"
        await emit_room_state(restored)
        await emit_toast(restored, restored.last_event)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def host_adjust(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_room_ready(room)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)
        require_host(room, player)
        target_player_id = str(data.get("target_player_id", ""))
        payload = {
            "target_player_id": target_player_id,
            "new_score": int(data.get("new_score")),
        }
        result = await queue_or_apply_action(room, player, "host_adjust", payload, bypass_approval=True)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@sio.event
async def reset_scores(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        room, player = get_context_by_sid(sid)
        ensure_no_pending_action(room)
        ensure_not_in_draw_input(room)
        require_host(room, player)
        result = await queue_or_apply_action(room, player, "reset_scores", {}, bypass_approval=True)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}