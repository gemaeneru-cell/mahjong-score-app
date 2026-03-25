const socket = io({ transports: ["websocket", "polling"] });

const state = {
  room: null,
  roomId: "",
  playerId: "",
  playerName: "",
  requestedSeat: "",
  joined: false,
};

const refs = {
  roomMeta: document.getElementById("roomMeta"),
  connectionBadge: document.getElementById("connectionBadge"),
  copyRoomBtn: document.getElementById("copyRoomBtn"),
  setupSection: document.getElementById("setupSection"),
  gameSection: document.getElementById("gameSection"),
  createRoomForm: document.getElementById("createRoomForm"),
  joinRoomForm: document.getElementById("joinRoomForm"),
  roomIdInput: document.getElementById("roomIdInput"),
  requestedSeatSelect: document.getElementById("requestedSeatSelect"),
  scoreboard: document.getElementById("scoreboard"),
  roundLabel: document.getElementById("roundLabel"),
  honbaLabel: document.getElementById("honbaLabel"),
  kyotakuLabel: document.getElementById("kyotakuLabel"),
  statusLabel: document.getElementById("statusLabel"),
  lastEventLabel: document.getElementById("lastEventLabel"),
  pendingPanel: document.getElementById("pendingPanel"),
  reachBtn: document.getElementById("reachBtn"),
  undoBtn: document.getElementById("undoBtn"),
  winForm: document.getElementById("winForm"),
  winTypeSelect: document.getElementById("winTypeSelect"),
  ronTargetField: document.getElementById("ronTargetField"),
  fromPlayerSelect: document.getElementById("fromPlayerSelect"),
  drawBtn: document.getElementById("drawBtn"),
  drawResponsePanel: document.getElementById("drawResponsePanel"),
  tenpaiBtn: document.getElementById("tenpaiBtn"),
  notenBtn: document.getElementById("notenBtn"),
  hostPanel: document.getElementById("hostPanel"),
  hostAdjustForm: document.getElementById("hostAdjustForm"),
  hostAdjustTarget: document.getElementById("hostAdjustTarget"),
  resetScoresBtn: document.getElementById("resetScoresBtn"),
  toast: document.getElementById("toast"),
};

function roomStorageKey(roomId) {
  return `mahjong-score:${roomId}`;
}

function saveIdentity(roomId, payload) {
  localStorage.setItem(roomStorageKey(roomId), JSON.stringify(payload));
}

function loadIdentity(roomId) {
  try {
    return JSON.parse(localStorage.getItem(roomStorageKey(roomId)) || "null");
  } catch {
    return null;
  }
}

function formatScore(score) {
  return new Intl.NumberFormat("ja-JP").format(score);
}

function showToast(message, isError = false) {
  refs.toast.textContent = message;
  refs.toast.classList.remove("hidden");
  refs.toast.classList.toggle("border-red-500", isError);
  refs.toast.classList.toggle("bg-red-950", isError);
  refs.toast.classList.toggle("border-slate-700", !isError);
  refs.toast.classList.toggle("bg-slate-900/95", !isError);
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => refs.toast.classList.add("hidden"), 2600);
}

function setConnectionBadge(connected) {
  refs.connectionBadge.textContent = connected ? "Socket 接続中" : "Socket 再接続中";
  refs.connectionBadge.className = connected
    ? "rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300"
    : "rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs text-amber-300";
}

async function emitAck(event, payload = {}) {
  return new Promise((resolve) => {
    socket.emit(event, payload, (ack) => resolve(ack));
  });
}

function getMe(room = state.room) {
  return room?.players?.find((player) => player.id === state.playerId) || null;
}

function syncWinFormVisibility() {
  refs.ronTargetField.classList.toggle("hidden", refs.winTypeSelect.value !== "ron");
}

function updateUrl(roomId) {
  const url = new URL(window.location.href);
  if (roomId) {
    url.searchParams.set("room", roomId);
  } else {
    url.searchParams.delete("room");
  }
  history.replaceState({}, "", url);
}

function openGameView() {
  refs.setupSection.classList.add("hidden");
  refs.gameSection.classList.remove("hidden");
  refs.gameSection.classList.add("grid");
}

function openSetupView() {
  refs.setupSection.classList.remove("hidden");
  refs.gameSection.classList.add("hidden");
  refs.gameSection.classList.remove("grid");
}

function buildScoreCard(player, meId) {
  const badges = [
    `<span class="score-badge">${player.rank}位</span>`,
    `<span class="score-badge">${player.current_wind}</span>`,
    player.is_dealer ? `<span class="score-badge text-amber-200 border-amber-500/50">親</span>` : "",
    player.is_host ? `<span class="score-badge opacity-75">HOST</span>` : "",
    !player.connected ? `<span class="score-badge text-red-400">切断</span>` : "",
  ].join("");

  const extraClasses = [
    player.id === meId ? "is-me" : "",
    player.is_dealer ? "is-dealer" : "",
    player.rank === 1 ? "is-top" : "",
    !player.connected ? "disconnected" : "",
  ].join(" ");

  // 席番号を名称に変換する配列
  const seatNames = ["起家", "南家", "西家", "北家"];

  return `
    <article class="score-card ${extraClasses}">
      <div class="score-header">
        <div class="score-name">${player.name}</div>
        <div class="score-meta">${badges}</div>
      </div>
      <div class="score-value">${formatScore(player.score)}</div>
      <div class="score-sub">
        <span>トップ差: ${formatScore(player.gap_to_top)}</span>
        <span>${seatNames[player.seat] || "席" + player.seat}</span>
      </div>
    </article>
  `;
}

function renderPendingPanel(room) {
  const pending = room.pending_action;
  if (!pending) {
    refs.pendingPanel.classList.add("hidden");
    refs.pendingPanel.innerHTML = "";
    return;
  }

  const remainingNames = pending.remaining_approver_ids
    .map((pid) => room.players.find((player) => player.id === pid)?.name || pid)
    .join(" / ");
  const shouldApprove = pending.remaining_approver_ids.includes(state.playerId);

  refs.pendingPanel.classList.remove("hidden");
  refs.pendingPanel.innerHTML = `
    <h3 class="panel-title">承認待ち</h3>
    <div class="rounded-2xl border border-blue-500/20 bg-blue-500/10 p-3">
      <p class="font-semibold text-blue-200">${pending.description}</p>
      <p class="mt-2 text-sm text-slate-300">残り承認: ${remainingNames || "なし"}</p>
      ${
        shouldApprove
          ? `<div class="mt-3 grid grid-cols-2 gap-3">
               <button id="approveActionBtn" class="accent-btn" type="button">承認</button>
               <button id="rejectActionBtn" class="secondary-btn" type="button">差し戻し</button>
             </div>`
          : `<p class="mt-3 text-sm text-slate-400">あなたは承認済み、または承認対象外です。</p>`
      }
    </div>
  `;

  const approveBtn = document.getElementById("approveActionBtn");
  const rejectBtn = document.getElementById("rejectActionBtn");
  if (approveBtn) {
    approveBtn.addEventListener("click", async () => {
      const ack = await emitAck("approve_action", {});
      if (!ack?.ok) showToast(ack?.error || "承認に失敗しました。", true);
    });
  }
  if (rejectBtn) {
    rejectBtn.addEventListener("click", async () => {
      const ack = await emitAck("reject_action", {});
      if (!ack?.ok) showToast(ack?.error || "差し戻しに失敗しました。", true);
    });
  }
}

function renderDrawPanel(room) {
  if (!room.draw_context?.active) {
    refs.drawResponsePanel.classList.add("hidden");
    return;
  }

  const alreadyAnswered = Object.prototype.hasOwnProperty.call(room.draw_context.responses, state.playerId);
  refs.drawResponsePanel.classList.remove("hidden");

  if (alreadyAnswered) {
    refs.drawResponsePanel.innerHTML = `
      <p class="font-semibold text-amber-200">あなたの入力は送信済みです</p>
      <p class="mt-2 text-sm text-slate-300">全員の入力完了を待っています。</p>
    `;
    return;
  }

  refs.drawResponsePanel.innerHTML = `
    <p class="font-semibold text-amber-200">あなたの流局入力</p>
    <div class="mt-3 grid grid-cols-2 gap-3">
      <button id="tenpaiBtnInner" class="accent-btn" type="button">テンパイ</button>
      <button id="notenBtnInner" class="secondary-btn" type="button">ノーテン</button>
    </div>
  `;

  document.getElementById("tenpaiBtnInner")?.addEventListener("click", () => submitDrawStatus(true));
  document.getElementById("notenBtnInner")?.addEventListener("click", () => submitDrawStatus(false));
}

function renderRoom(room) {
  state.room = room;
  const me = getMe(room);

  refs.roomMeta.textContent = `部屋 ${room.id} / ${me?.name || "未参加"} / ${room.settings.seats}人打ち / 承認 ${room.settings.approval_enabled ? "ON" : "OFF"}`;
  refs.roundLabel.textContent = room.current_round;
  refs.honbaLabel.textContent = String(room.honba);
  refs.kyotakuLabel.textContent = String(room.kyotaku);
  refs.lastEventLabel.textContent = room.last_event || "-";
  refs.statusLabel.textContent = room.finished
    ? "終了"
    : room.pending_action
      ? "承認待ち"
      : room.draw_context?.active
        ? "流局入力中"
        : room.ready
          ? "進行中"
          : `待機 ${room.players_joined}/${room.settings.seats}`;

  refs.scoreboard.className = room.settings.seats === 4 ? "grid min-h-0 flex-1 grid-cols-2 grid-rows-2 gap-3 md:gap-4" : "grid min-h-0 flex-1 grid-cols-3 gap-3 md:gap-4";
  refs.scoreboard.innerHTML = room.players.map((player) => buildScoreCard(player, state.playerId)).join("");

  refs.fromPlayerSelect.innerHTML = room.players
    .filter((player) => player.id !== state.playerId)
    .map((player) => `<option value="${player.id}">${player.name}</option>`)
    .join("");

  refs.hostAdjustTarget.innerHTML = room.players
    .map((player) => `<option value="${player.id}">${player.name}</option>`)
    .join("");

  const targetValue = refs.hostAdjustTarget.value || room.players[0]?.id;
  const targetPlayer = room.players.find((player) => player.id === targetValue) || room.players[0];
  if (targetPlayer) {
    refs.hostAdjustForm.elements.new_score.value = String(targetPlayer.score);
    refs.hostAdjustTarget.value = targetPlayer.id;
  }

  renderPendingPanel(room);
  renderDrawPanel(room);
  syncWinFormVisibility();

  const disableScoreActions = !room.ready || room.finished || Boolean(room.pending_action) || Boolean(room.draw_context?.active);
  refs.reachBtn.disabled = disableScoreActions;
  refs.undoBtn.disabled = !room.has_undo || Boolean(room.pending_action) || Boolean(room.draw_context?.active);
  refs.drawBtn.disabled = disableScoreActions || !me?.is_dealer;
  refs.winForm.querySelector("button[type='submit']").disabled = disableScoreActions;

  refs.hostPanel.classList.toggle("hidden", !me?.is_host);
  refs.copyRoomBtn.disabled = !room.id;
}

async function joinRoom({ roomId, name, playerId = "", requestedSeat = "", silent = false }) {
  const normalizedRoomId = roomId.trim().toUpperCase();
  if (!normalizedRoomId) {
    showToast("部屋IDを入力してください。", true);
    return;
  }
  const identity = playerId ? { playerId, name } : loadIdentity(normalizedRoomId);
  const ack = await emitAck("join_room", {
    room_id: normalizedRoomId,
    name,
    player_id: playerId || identity?.playerId || "",
    requested_seat: requestedSeat,
  });

  if (!ack?.ok) {
    showToast(ack?.error || "部屋参加に失敗しました。", true);
    return;
  }

  state.roomId = normalizedRoomId;
  state.playerId = ack.player_id;
  state.playerName = name;
  state.requestedSeat = requestedSeat;
  state.joined = true;
  saveIdentity(normalizedRoomId, { playerId: ack.player_id, name });
  updateUrl(normalizedRoomId);
  openGameView();
  renderRoom(ack.room);
  if (!silent) showToast(`部屋 ${normalizedRoomId} に参加しました。`);
}

async function createRoom(event) {
  event.preventDefault();
  const formData = new FormData(refs.createRoomForm);
  
  // 修正：フォームから希望席を取得し、送信データに含める
  const requestedSeat = formData.get("requested_seat") || "";
  
  const payload = {
    name: formData.get("name"),
    seats: Number(formData.get("seats")),
    initial_points: Number(formData.get("initial_points")),
    approval_enabled: formData.get("approval_enabled") === "on",
    requested_seat: requestedSeat,
  };

  const response = await fetch("/api/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const result = await response.json();
  if (!response.ok) {
    showToast(result.detail || "部屋作成に失敗しました。", true);
    return;
  }

  refs.roomIdInput.value = result.room_id;
  await joinRoom({ roomId: result.room_id, name: payload.name, playerId: result.player_id, requestedSeat: requestedSeat });
}

async function joinRoomFromForm(event) {
  event.preventDefault();
  const formData = new FormData(refs.joinRoomForm);
  await joinRoom({
    roomId: formData.get("room_id"),
    name: formData.get("name"),
    requestedSeat: formData.get("requested_seat"),
  });
}

async function submitWin(event) {
  event.preventDefault();
  const formData = new FormData(refs.winForm);
  const payload = {
    win_type: formData.get("win_type"),
    han: Number(formData.get("han")),
    fu: Number(formData.get("fu")),
  };
  if (payload.win_type === "ron") {
    payload.from_player_id = formData.get("from_player_id");
  }

  const ack = await emitAck("submit_win", payload);
  if (!ack?.ok) {
    showToast(ack?.error || "和了送信に失敗しました。", true);
  }
}

async function submitDrawStatus(tenpai) {
  const ack = await emitAck("submit_draw_status", { tenpai });
  if (!ack?.ok) {
    showToast(ack?.error || "流局入力に失敗しました。", true);
  }
}

async function callSimpleAction(eventName) {
  const ack = await emitAck(eventName, {});
  if (!ack?.ok) {
    showToast(ack?.error || "操作に失敗しました。", true);
  }
}

socket.on("connect", async () => {
  setConnectionBadge(true);
  if (state.joined && state.roomId && state.playerName) {
    await joinRoom({
      roomId: state.roomId,
      name: state.playerName,
      playerId: state.playerId,
      requestedSeat: state.requestedSeat,
      silent: true,
    });
  }
});

socket.on("disconnect", () => {
  setConnectionBadge(false);
});

socket.on("room_state", (room) => {
  if (!state.roomId || room.id !== state.roomId) return;
  renderRoom(room);
});

socket.on("toast", (payload) => {
  if (payload?.message) showToast(payload.message);
});

refs.createRoomForm.addEventListener("submit", createRoom);
refs.joinRoomForm.addEventListener("submit", joinRoomFromForm);
refs.winForm.addEventListener("submit", submitWin);
refs.winTypeSelect.addEventListener("change", syncWinFormVisibility);
refs.reachBtn.addEventListener("click", () => callSimpleAction("submit_reach"));
refs.undoBtn.addEventListener("click", () => callSimpleAction("undo_last"));
refs.drawBtn.addEventListener("click", () => callSimpleAction("start_draw"));
refs.tenpaiBtn.addEventListener("click", () => submitDrawStatus(true));
refs.notenBtn.addEventListener("click", () => submitDrawStatus(false));
refs.hostAdjustTarget.addEventListener("change", () => {
  const target = state.room?.players?.find((player) => player.id === refs.hostAdjustTarget.value);
  if (target) refs.hostAdjustForm.elements.new_score.value = String(target.score);
});
refs.hostAdjustForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(refs.hostAdjustForm);
  const ack = await emitAck("host_adjust", {
    target_player_id: formData.get("target_player_id"),
    new_score: Number(formData.get("new_score")),
  });
  if (!ack?.ok) {
    showToast(ack?.error || "点数調整に失敗しました。", true);
  }
});
refs.resetScoresBtn.addEventListener("click", () => callSimpleAction("reset_scores"));
refs.copyRoomBtn.addEventListener("click", async () => {
  if (!state.room?.id) {
    showToast("先に部屋へ参加してください。", true);
    return;
  }
  await navigator.clipboard.writeText(state.room.id);
  showToast(`部屋ID ${state.room.id} をコピーしました。`);
});

(function init() {
  syncWinFormVisibility();
  openSetupView();
  setConnectionBadge(socket.connected);

  const roomId = new URL(window.location.href).searchParams.get("room");
  if (roomId) {
    refs.roomIdInput.value = roomId.toUpperCase();
    const identity = loadIdentity(roomId.toUpperCase());
    if (identity?.playerId && identity?.name) {
      refs.joinRoomForm.elements.name.value = identity.name;
      joinRoom({ roomId: roomId.toUpperCase(), name: identity.name, playerId: identity.playerId, silent: true });
    }
  }
})();