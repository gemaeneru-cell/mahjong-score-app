const socket = io({ 
  transports: ["websocket", "polling"],
  reconnection: true,
  reconnectionAttempts: Infinity, // 無限に再接続を試みる
  reconnectionDelay: 1000,
});

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

// 音声ファイルの読み込み（前回の修正分）
const reachSound = new Audio('/assets/sounds/reach.mp3');

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

function setConnectionBadge(status) {
  const b = refs.connectionBadge;
  if (status === "connected") {
    b.textContent = "Socket 接続中";
    b.className = "rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300";
  } else if (status === "reconnecting") {
    b.textContent = "再接続・復帰中...";
    b.className = "rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs text-amber-300 animate-pulse";
  } else {
    b.textContent = "切断されました";
    b.className = "rounded-full border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs text-red-300";
  }
}

async function emitAck(event, payload = {}) {
  return new Promise((resolve) => {
    if (!socket.connected) {
      showToast("接続が切れています。復帰をお待ちください。", true);
      resolve({ ok: false, error: "Disconnected" });
      return;
    }
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

// 描画ロジック等は変更なし（中略）

function renderRoom(room) {
  state.room = room;
  const me = getMe(room);

  refs.roomMeta.textContent = `部屋 ${room.id} / ${me?.name || "未参加"} / ${room.settings.seats}人打ち / 承認 ${room.settings.approval_enabled ? "ON" : "OFF"}`;
  refs.roundLabel.textContent = room.current_round;
  refs.honbaLabel.textContent = String(room.honba);
  refs.kyotakuLabel.textContent = String(room.kyotaku);
  refs.lastEventLabel.textContent = room.last_event || "-";
  refs.statusLabel.textContent = room.finished ? "終了" : room.pending_action ? "承認待ち" : room.draw_context?.active ? "流局入力中" : room.ready ? "進行中" : `待機 ${room.players_joined}/${room.settings.seats}`;

  refs.scoreboard.className = room.settings.seats === 4 ? "grid min-h-0 flex-1 grid-cols-2 grid-rows-2 gap-3 md:gap-4" : "grid min-h-0 flex-1 grid-cols-3 gap-3 md:gap-4";
  refs.scoreboard.innerHTML = room.players.map((player) => buildScoreCard(player, state.playerId)).join("");

  // リーチ音のトリガー
  if (room.last_event && room.last_event.includes("リーチ") && !renderRoom._lastHandledEvent?.includes(room.last_event)) {
    reachSound.play().catch(() => {});
  }
  renderRoom._lastHandledEvent = room.last_event;

  refs.fromPlayerSelect.innerHTML = room.players.filter((p) => p.id !== state.playerId).map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  refs.hostAdjustTarget.innerHTML = room.players.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");

  const targetPlayer = room.players.find((p) => p.id === refs.hostAdjustTarget.value) || room.players[0];
  if (targetPlayer) refs.hostAdjustForm.elements.new_score.value = String(targetPlayer.score);

  // 承認パネルや流局パネルの描画（既存の関数を呼び出し）
  if (window.renderPendingPanel) renderPendingPanel(room);
  if (window.renderDrawPanel) renderDrawPanel(room);

  const disableScoreActions = !room.ready || room.finished || Boolean(room.pending_action) || Boolean(room.draw_context?.active);
  refs.reachBtn.disabled = disableScoreActions;
  refs.undoBtn.disabled = !room.has_undo || Boolean(room.pending_action) || Boolean(room.draw_context?.active);
  refs.drawBtn.disabled = disableScoreActions || !me?.is_dealer;
  refs.winForm.querySelector("button[type='submit']").disabled = disableScoreActions;
  refs.hostPanel.classList.toggle("hidden", !me?.is_host);
  refs.copyRoomBtn.disabled = !room.id;
}

// 修正：joinRoom 関数を強化し、成功時に state を確実に更新するように
async function joinRoom({ roomId, name, playerId = "", requestedSeat = "", silent = false }) {
  const normalizedRoomId = roomId.trim().toUpperCase();
  if (!normalizedRoomId) return;

  const identity = playerId ? { playerId, name } : loadIdentity(normalizedRoomId);
  const ack = await emitAck("join_room", {
    room_id: normalizedRoomId,
    name,
    player_id: playerId || identity?.playerId || "",
    requested_seat: requestedSeat,
  });

  if (!ack?.ok) {
    if (!silent) showToast(ack?.error || "部屋参加に失敗しました。", true);
    return;
  }

  // クライアント側状態の確定
  state.roomId = normalizedRoomId;
  state.playerId = ack.player_id;
  state.playerName = name;
  state.joined = true;
  
  saveIdentity(normalizedRoomId, { playerId: ack.player_id, name });
  updateUrl(normalizedRoomId);
  openGameView();
  renderRoom(ack.room);
  if (!silent) showToast(`復帰しました：${normalizedRoomId}`);
}

// --- 再接続・復帰ロジックの強化 ---

socket.on("connect", async () => {
  console.log("Connected to server. Socket ID:", socket.id);
  setConnectionBadge("connected");

  // もし参加済み（joined）なら、IDが変わっていても自動的に元のルームへ復帰する
  if (state.joined && state.roomId && state.playerId) {
    setConnectionBadge("reconnecting");
    await joinRoom({
      roomId: state.roomId,
      name: state.playerName,
      playerId: state.playerId,
      silent: true,
    });
  }
});

socket.on("disconnect", (reason) => {
  console.warn("Disconnected:", reason);
  setConnectionBadge("disconnected");
});

// Renderのスリープ防止（5分おきにサーバーへ信号を送る）
setInterval(() => {
  if (socket.connected) {
    socket.emit("ping_keepalive", { t: Date.now() });
  }
}, 300000);

// 以下、イベントリスナー等は既存通り（中略）

refs.createRoomForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(refs.createRoomForm);
    const reqSeat = formData.get("requested_seat") || "";
    const payload = {
      name: formData.get("name"),
      seats: Number(formData.get("seats")),
      initial_points: Number(formData.get("initial_points")),
      approval_enabled: formData.get("approval_enabled") === "on",
      requested_seat: reqSeat,
    };
    const response = await fetch("/api/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) return showToast(result.detail, true);
    refs.roomIdInput.value = result.room_id;
    await joinRoom({ roomId: result.room_id, name: payload.name, playerId: result.player_id, requestedSeat: reqSeat });
});

refs.joinRoomForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(refs.joinRoomForm);
  await joinRoom({
    roomId: formData.get("room_id"),
    name: formData.get("name"),
    requestedSeat: formData.get("requested_seat"),
  });
});

refs.winForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(refs.winForm);
  const payload = {
    win_type: formData.get("win_type"),
    han: Number(formData.get("han")),
    fu: Number(formData.get("fu")),
    from_player_id: formData.get("from_player_id")
  };
  await emitAck("submit_win", payload);
});

refs.reachBtn.addEventListener("click", () => {
    reachSound.play().catch(() => {});
    socket.emit("submit_reach", {});
});

socket.on("room_state", (room) => {
  if (state.roomId && room.id === state.roomId) renderRoom(room);
});

socket.on("toast", (p) => p?.message && showToast(p.message));

(function init() {
  syncWinFormVisibility();
  openSetupView();
  setConnectionBadge(socket.connected ? "connected" : "disconnected");
  const rid = new URL(window.location.href).searchParams.get("room");
  if (rid) {
    const iden = loadIdentity(rid.toUpperCase());
    if (iden) {
        state.roomId = rid.toUpperCase();
        state.playerId = iden.playerId;
        state.playerName = iden.name;
        state.joined = true;
        // 初期読み込み時の復帰
        joinRoom({ roomId: state.roomId, name: state.playerName, playerId: state.playerId, silent: true });
    }
  }
})();
