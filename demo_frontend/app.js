import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.167.1/build/three.module.js";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.167.1/examples/jsm/controls/OrbitControls.js";

const state = {
  socket: null,
  connected: false,
  requestCounter: 1,
  currentAction: "idle",
  currentExpression: "calm",
  currentReply: "",
  currentMusic: null,
  currentSource: "-",
  actionStartedAt: performance.now(),
  ttsChunks: new Map(),
  avatar: null,
};

const ui = {
  wsUrl: document.getElementById("ws-url"),
  sessionId: document.getElementById("session-id"),
  connectionStatus: document.getElementById("connection-status"),
  connectBtn: document.getElementById("connect-btn"),
  disconnectBtn: document.getElementById("disconnect-btn"),
  pingBtn: document.getElementById("ping-btn"),
  songTitle: document.getElementById("song-title"),
  songArtist: document.getElementById("song-artist"),
  songUrl: document.getElementById("song-url"),
  sendSongBtn: document.getElementById("send-song-btn"),
  userText: document.getElementById("user-text"),
  poseLabel: document.getElementById("pose-label"),
  touchEvent: document.getElementById("touch-event"),
  audioFile: document.getElementById("audio-file"),
  sendSignalBtn: document.getElementById("send-signal-btn"),
  presetChorusBtn: document.getElementById("preset-chorus-btn"),
  presetHeartBtn: document.getElementById("preset-heart-btn"),
  replyText: document.getElementById("reply-text"),
  replyAction: document.getElementById("reply-action"),
  replyExpression: document.getElementById("reply-expression"),
  replyTranscript: document.getElementById("reply-transcript"),
  timingJson: document.getElementById("timing-json"),
  musicChip: document.getElementById("music-chip"),
  sourceChip: document.getElementById("source-chip"),
  audioPlayer: document.getElementById("audio-player"),
  clearLogBtn: document.getElementById("clear-log-btn"),
  logOutput: document.getElementById("log-output"),
  canvas: document.getElementById("stage-canvas"),
};

boot();

function boot() {
  setupScene();
  bindEvents();
  logLine("准备完成。先启动后端，再点击连接。");
}

function bindEvents() {
  ui.connectBtn.addEventListener("click", connectSocket);
  ui.disconnectBtn.addEventListener("click", disconnectSocket);
  ui.pingBtn.addEventListener("click", sendPing);
  ui.sendSongBtn.addEventListener("click", sendSongContext);
  ui.sendSignalBtn.addEventListener("click", sendUserSignal);
  ui.clearLogBtn.addEventListener("click", () => {
    ui.logOutput.textContent = "";
  });

  ui.presetChorusBtn.addEventListener("click", () => {
    ui.userText.value = "小K我们一起唱副歌，给我点气氛。";
    ui.poseLabel.value = "arms_up";
    ui.touchEvent.value = "";
    sendUserSignal();
  });

  ui.presetHeartBtn.addEventListener("click", () => {
    ui.userText.value = "这首歌太甜了。";
    ui.poseLabel.value = "";
    ui.touchEvent.value = "heart";
    sendUserSignal();
  });
}

function nextRequestId(prefix = "req") {
  const id = `${prefix}-${String(state.requestCounter).padStart(3, "0")}`;
  state.requestCounter += 1;
  return id;
}

function buildSongPayload() {
  return {
    title: ui.songTitle.value.trim(),
    artist: ui.songArtist.value.trim(),
    url: ui.songUrl.value.trim(),
  };
}

async function sendSongContext() {
  if (!ensureSocket()) return;
  const message = {
    type: "song_context",
    request_id: nextRequestId("song"),
    session_id: ui.sessionId.value.trim() || "booth-demo",
    payload: {
      song: buildSongPayload(),
    },
  };
  sendJson(message);
}

async function sendUserSignal() {
  if (!ensureSocket()) return;

  const audioPayload = await buildAudioPayload();
  const message = {
    type: "user_signal",
    request_id: nextRequestId("turn"),
    session_id: ui.sessionId.value.trim() || "booth-demo",
    payload: {
      audio: audioPayload,
      pose_label: ui.poseLabel.value,
      touch_event: ui.touchEvent.value,
      song: buildSongPayload(),
      user_text: ui.userText.value.trim(),
    },
  };

  sendJson(message);
}

async function buildAudioPayload() {
  const file = ui.audioFile.files[0];
  if (!file) return null;

  const dataUrl = await readFileAsDataUrl(file);
  return {
    content_b64: dataUrl.split(",", 2)[1],
    mime_type: file.type || "audio/wav",
    sample_rate: 16000,
  };
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function connectSocket() {
  disconnectSocket();

  const url = ui.wsUrl.value.trim();
  if (!url) {
    logLine("WebSocket 地址为空。");
    return;
  }

  const socket = new WebSocket(url);
  state.socket = socket;
  setStatus("连接中…", "idle");

  socket.addEventListener("open", () => {
    state.connected = true;
    setStatus("已连接", "connected");
    logLine(`已连接 ${url}`);
  });

  socket.addEventListener("close", () => {
    state.connected = false;
    if (state.socket === socket) state.socket = null;
    setStatus("已断开", "idle");
    logLine("连接已关闭。");
  });

  socket.addEventListener("error", () => {
    setStatus("连接错误", "error");
    logLine("WebSocket 连接出错。");
  });

  socket.addEventListener("message", async (event) => {
    const rawText = typeof event.data === "string" ? event.data : await event.data.text();
    logLine(`← ${rawText}`);
    const message = JSON.parse(rawText);
    handleServerMessage(message);
  });
}

function disconnectSocket() {
  if (state.socket) {
    state.socket.close();
  }
  state.socket = null;
  state.connected = false;
  setStatus("未连接", "idle");
}

function ensureSocket() {
  if (!state.socket || !state.connected) {
    logLine("请先连接后端。");
    return false;
  }
  return true;
}

function sendPing() {
  if (!ensureSocket()) return;
  sendJson({
    type: "ping",
    request_id: nextRequestId("ping"),
    session_id: ui.sessionId.value.trim() || "booth-demo",
  });
}

function sendJson(payload) {
  if (!ensureSocket()) return;
  const text = JSON.stringify(payload);
  state.socket.send(text);
  logLine(`→ ${text}`);
}

function handleServerMessage(message) {
  const type = message.type;
  const payload = message.payload || {};

  if (type === "hello") {
    const caps = payload.capabilities || {};
    const provider = payload.llm_provider || "unknown";
    logLine(`后端能力：${JSON.stringify(caps)} | LLM: ${provider}`);
    return;
  }

  if (type === "song_ready") {
    const music = payload.music || {};
    state.currentMusic = music;
    ui.musicChip.textContent = `music: ${music.mood || "unknown"} / ${music.energy || "unknown"}`;
    logLine("歌曲预热完成。");
    return;
  }

  if (type === "agent_response") {
    applyAgentResponse(payload);
    return;
  }

  if (type === "tts_chunk") {
    collectTtsChunk(message.request_id, payload);
    return;
  }

  if (type === "tts_done") {
    finalizeTts(message.request_id, payload);
    return;
  }

  if (type === "error") {
    setStatus("后端报错", "error");
  }
}

function applyAgentResponse(payload) {
  ui.replyText.textContent = payload.text || "-";
  ui.replyAction.textContent = payload.action || "-";
  ui.replyExpression.textContent = payload.expression || "-";
  ui.replyTranscript.textContent = payload.transcript || "-";
  ui.timingJson.textContent = JSON.stringify(payload.timings_ms || {}, null, 2);

  state.currentReply = payload.text || "";
  state.currentAction = payload.action || "idle";
  state.currentExpression = payload.expression || "calm";
  state.currentSource = payload.source || "-";
  state.actionStartedAt = performance.now();

  const music = payload.music || {};
  ui.musicChip.textContent = `music: ${music.mood || "unknown"} / ${music.energy || "unknown"}`;
  ui.sourceChip.textContent = `source: ${state.currentSource}`;
  updateAvatarExpression(state.currentExpression);
}

function collectTtsChunk(requestId, payload) {
  if (!requestId) return;
  const current = state.ttsChunks.get(requestId) || {
    format: payload.format || "audio/mpeg",
    parts: [],
  };
  if (payload.audio_b64) {
    current.parts.push(base64ToUint8(payload.audio_b64));
  }
  state.ttsChunks.set(requestId, current);
}

function finalizeTts(requestId, payload) {
  const current = state.ttsChunks.get(requestId);
  if (!current) return;
  const mimeType = payload.format === "audio/wav" ? "audio/wav" : "audio/mpeg";
  const blob = new Blob(current.parts, { type: mimeType });
  const url = URL.createObjectURL(blob);
  ui.audioPlayer.src = url;
  ui.audioPlayer.play().catch(() => {
    logLine("浏览器阻止了自动播放，点一下播放器就能听。");
  });
  state.ttsChunks.delete(requestId);
}

function base64ToUint8(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function setStatus(text, kind) {
  ui.connectionStatus.textContent = text;
  ui.connectionStatus.className = `status-pill ${kind}`;
}

function logLine(line) {
  const stamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  ui.logOutput.textContent += `[${stamp}] ${line}\n`;
  ui.logOutput.scrollTop = ui.logOutput.scrollHeight;
}

function setupScene() {
  const renderer = new THREE.WebGLRenderer({
    canvas: ui.canvas,
    antialias: true,
    alpha: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  camera.position.set(0, 1.8, 7.8);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 4.2;
  controls.maxDistance = 12;
  controls.target.set(0, 1.8, 0);

  const hemi = new THREE.HemisphereLight(0xf9d8bb, 0x2d1f1a, 1.3);
  scene.add(hemi);

  const spot = new THREE.SpotLight(0xfff2d4, 2.3, 30, Math.PI / 5, 0.35, 1.2);
  spot.position.set(0, 9, 8);
  spot.target.position.set(0, 1.2, 0);
  scene.add(spot);
  scene.add(spot.target);

  const rim = new THREE.PointLight(0x56e3df, 0.8, 20);
  rim.position.set(-5, 4, -4);
  scene.add(rim);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(4.8, 64),
    new THREE.MeshStandardMaterial({
      color: 0xb07034,
      roughness: 0.85,
      metalness: 0.05,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -1.45;
  scene.add(floor);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(4.05, 0.08, 16, 64),
    new THREE.MeshBasicMaterial({ color: 0xffc56d }),
  );
  ring.rotation.x = Math.PI / 2;
  ring.position.y = -1.43;
  scene.add(ring);

  state.avatar = createAvatar();
  scene.add(state.avatar.root);
  updateAvatarExpression("calm");

  function resize() {
    const width = ui.canvas.clientWidth;
    const height = ui.canvas.clientHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  window.addEventListener("resize", resize);
  resize();

  const clock = new THREE.Clock();

  function tick() {
    const elapsed = clock.getElapsedTime();
    updateAvatarPose(elapsed);
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }

  tick();
}

function createAvatar() {
  const root = new THREE.Group();
  root.position.y = -0.05;

  const palette = {
    coat: new THREE.MeshStandardMaterial({ color: 0xff865c, roughness: 0.55 }),
    skin: new THREE.MeshStandardMaterial({ color: 0xffd0b0, roughness: 0.9 }),
    pants: new THREE.MeshStandardMaterial({ color: 0x20445b, roughness: 0.8 }),
    glow: new THREE.MeshStandardMaterial({ color: 0xffdd8b, emissive: 0x000000, roughness: 0.3 }),
  };

  const hips = new THREE.Group();
  hips.position.y = 0;
  root.add(hips);

  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.46, 1.25, 6, 12), palette.coat);
  torso.position.y = 1.05;
  hips.add(torso);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.42, 32, 32), palette.skin);
  head.position.y = 2.25;
  hips.add(head);

  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.45, 32, 32), new THREE.MeshStandardMaterial({
    color: 0x30211d,
    roughness: 0.65,
  }));
  hair.scale.set(1.02, 0.88, 1.02);
  hair.position.set(0, 0.12, -0.02);
  head.add(hair);

  const facePlate = new THREE.Mesh(
    new THREE.CircleGeometry(0.23, 24),
    palette.glow,
  );
  facePlate.position.set(0, 0.02, 0.34);
  head.add(facePlate);

  const eyes = new THREE.Group();
  head.add(eyes);
  eyes.position.set(0, 0.04, 0.38);

  const leftEye = new THREE.Mesh(
    new THREE.SphereGeometry(0.045, 16, 16),
    new THREE.MeshBasicMaterial({ color: 0x241d16 }),
  );
  const rightEye = leftEye.clone();
  leftEye.position.x = -0.09;
  rightEye.position.x = 0.09;
  eyes.add(leftEye, rightEye);

  const mouth = new THREE.Mesh(
    new THREE.TorusGeometry(0.06, 0.012, 8, 18, Math.PI),
    new THREE.MeshBasicMaterial({ color: 0xb53c3c }),
  );
  mouth.rotation.z = Math.PI;
  mouth.position.set(0, -0.1, 0.38);
  head.add(mouth);

  const leftArm = createLimb(palette.coat, palette.skin);
  const rightArm = createLimb(palette.coat, palette.skin);
  leftArm.root.position.set(-0.6, 1.55, 0);
  rightArm.root.position.set(0.6, 1.55, 0);
  hips.add(leftArm.root, rightArm.root);

  const leftLeg = createLimb(palette.pants, palette.skin, true);
  const rightLeg = createLimb(palette.pants, palette.skin, true);
  leftLeg.root.position.set(-0.22, 0.36, 0);
  rightLeg.root.position.set(0.22, 0.36, 0);
  hips.add(leftLeg.root, rightLeg.root);

  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(0.95, 0.04, 12, 48),
    new THREE.MeshBasicMaterial({ color: 0xffdf88 }),
  );
  halo.position.y = 3.05;
  halo.rotation.x = Math.PI / 2;
  root.add(halo);

  return {
    root,
    hips,
    torso,
    head,
    facePlate,
    eyes,
    mouth,
    leftArm,
    rightArm,
    leftLeg,
    rightLeg,
    halo,
  };
}

function createLimb(mainMaterial, endMaterial, isLeg = false) {
  const root = new THREE.Group();
  const upperPivot = new THREE.Group();
  const lowerPivot = new THREE.Group();

  root.add(upperPivot);
  upperPivot.add(lowerPivot);

  const upper = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.12, 0.52, 4, 8),
    mainMaterial,
  );
  upper.rotation.z = Math.PI / 2;
  upper.position.x = isLeg ? 0 : (mainMaterial.color.getHex() ? 0.28 : 0.28);
  upperPivot.add(upper);

  lowerPivot.position.x = isLeg ? 0 : 0.55;
  lowerPivot.position.y = isLeg ? -0.58 : 0;
  upperPivot.add(lowerPivot);

  const lower = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.1, 0.48, 4, 8),
    mainMaterial,
  );
  if (!isLeg) {
    lower.rotation.z = Math.PI / 2;
    lower.position.x = 0.25;
  } else {
    lower.position.y = -0.28;
  }
  lowerPivot.add(lower);

  const handOrFoot = new THREE.Mesh(
    new THREE.SphereGeometry(isLeg ? 0.12 : 0.1, 16, 16),
    endMaterial,
  );
  if (!isLeg) {
    handOrFoot.position.x = 0.55;
  } else {
    handOrFoot.scale.set(1.1, 0.6, 1.5);
    handOrFoot.position.set(0, -0.58, 0.12);
  }
  lowerPivot.add(handOrFoot);

  return { root, upperPivot, lowerPivot };
}

function updateAvatarExpression(expression) {
  if (!state.avatar) return;

  const faceColorByExpression = {
    calm: 0xffdd8b,
    excited: 0xff8f54,
    love: 0xff73a8,
    playful: 0x6adad4,
    supportive: 0x88c0ff,
    cool: 0xc69aff,
    focused: 0x9dd272,
  };

  const emissiveByExpression = {
    calm: 0x4d3518,
    excited: 0xa84d14,
    love: 0x9b214f,
    playful: 0x1f7974,
    supportive: 0x2f5794,
    cool: 0x564499,
    focused: 0x446b18,
  };

  state.avatar.facePlate.material.color.setHex(faceColorByExpression[expression] || 0xffdd8b);
  state.avatar.facePlate.material.emissive.setHex(emissiveByExpression[expression] || 0x4d3518);
}

function updateAvatarPose(time) {
  if (!state.avatar) return;

  const avatar = state.avatar;
  const action = state.currentAction || "idle";
  const beat = time * 2.2;
  const bounce = Math.sin(beat) * 0.05;
  const sway = Math.sin(time * 1.6) * 0.18;

  avatar.root.position.y = bounce;
  avatar.root.rotation.y = Math.sin(time * 0.8) * 0.05;
  avatar.halo.rotation.z += 0.006;

  resetLimbPose(avatar);

  avatar.leftLeg.upperPivot.rotation.x = Math.sin(beat) * 0.12;
  avatar.rightLeg.upperPivot.rotation.x = Math.sin(beat + Math.PI) * 0.12;
  avatar.leftLeg.lowerPivot.rotation.x = Math.max(0, Math.sin(beat + Math.PI) * 0.16);
  avatar.rightLeg.lowerPivot.rotation.x = Math.max(0, Math.sin(beat) * 0.16);

  if (action === "wave") {
    avatar.rightArm.upperPivot.rotation.z = -0.9;
    avatar.rightArm.lowerPivot.rotation.z = -0.35 + Math.sin(time * 7) * 0.35;
  } else if (action === "high_five") {
    avatar.rightArm.upperPivot.rotation.z = -1.2;
    avatar.rightArm.upperPivot.rotation.x = -0.6;
    avatar.leftArm.upperPivot.rotation.z = 0.2;
  } else if (action === "mirror_pose") {
    avatar.leftArm.upperPivot.rotation.z = 1.25;
    avatar.rightArm.upperPivot.rotation.z = -1.25;
  } else if (action === "heart_pose") {
    avatar.leftArm.upperPivot.rotation.z = 0.8;
    avatar.rightArm.upperPivot.rotation.z = -0.8;
    avatar.leftArm.lowerPivot.rotation.z = -0.9;
    avatar.rightArm.lowerPivot.rotation.z = 0.9;
  } else if (action === "cheer") {
    avatar.root.position.y = Math.abs(Math.sin(time * 5)) * 0.16;
    avatar.leftArm.upperPivot.rotation.z = 1.35;
    avatar.rightArm.upperPivot.rotation.z = -1.35;
  } else if (action === "sing_along") {
    avatar.leftArm.upperPivot.rotation.z = 0.35 + sway * 0.4;
    avatar.rightArm.upperPivot.rotation.z = -0.45;
    avatar.rightArm.lowerPivot.rotation.z = 0.35;
    avatar.head.rotation.y = Math.sin(time * 2.5) * 0.18;
  } else if (action === "dance_soft") {
    avatar.root.rotation.y = sway * 0.5;
    avatar.leftArm.upperPivot.rotation.z = 0.25 + sway * 0.4;
    avatar.rightArm.upperPivot.rotation.z = -0.25 - sway * 0.4;
  } else if (action === "dance_groove") {
    avatar.root.position.y = Math.sin(time * 4) * 0.09;
    avatar.root.rotation.y = sway * 0.85;
    avatar.leftArm.upperPivot.rotation.z = 0.6 + Math.sin(time * 4) * 0.35;
    avatar.rightArm.upperPivot.rotation.z = -0.6 - Math.sin(time * 4) * 0.35;
  } else if (action === "dance_fast") {
    avatar.root.position.y = Math.abs(Math.sin(time * 8)) * 0.18;
    avatar.root.rotation.y = Math.sin(time * 6) * 0.35;
    avatar.leftArm.upperPivot.rotation.z = 1.0 + Math.sin(time * 8) * 0.2;
    avatar.rightArm.upperPivot.rotation.z = -1.0 - Math.sin(time * 8) * 0.2;
  } else if (action === "clap") {
    avatar.leftArm.upperPivot.rotation.z = 0.75;
    avatar.rightArm.upperPivot.rotation.z = -0.75;
    avatar.leftArm.lowerPivot.rotation.z = -0.9 + Math.sin(time * 10) * 0.25;
    avatar.rightArm.lowerPivot.rotation.z = 0.9 - Math.sin(time * 10) * 0.25;
  }

  avatar.head.rotation.z = Math.sin(time * 2.2) * 0.03;
  avatar.mouth.scale.y = state.currentReply ? 1 + Math.abs(Math.sin(time * 9)) * 0.45 : 1;
}

function resetLimbPose(avatar) {
  avatar.head.rotation.set(0, 0, 0);
  avatar.leftArm.upperPivot.rotation.set(0, 0, 0.38);
  avatar.rightArm.upperPivot.rotation.set(0, 0, -0.38);
  avatar.leftArm.lowerPivot.rotation.set(0, 0, 0.18);
  avatar.rightArm.lowerPivot.rotation.set(0, 0, -0.18);
  avatar.leftLeg.upperPivot.rotation.set(0, 0, 0);
  avatar.rightLeg.upperPivot.rotation.set(0, 0, 0);
  avatar.leftLeg.lowerPivot.rotation.set(0, 0, 0);
  avatar.rightLeg.lowerPivot.rotation.set(0, 0, 0);
}
