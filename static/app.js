/* CameraTest UI — polls status and wires controls. */

const $ = (sel) => document.querySelector(sel);

const simBadge = $("#sim-badge");
const streamOverlay = $("#stream-overlay");
const hdmiStats = $("#hdmi-stats");
const usbOverlay = $("#usb-overlay");
const usbStats = $("#usb-stats");
const usbStream = $("#usb-stream");
const camStats = $("#cam-stats");
const deviceSelect = $("#device-select");
const exposureControls = $("#exposure-controls");
const actionControls = $("#action-controls");
const eventLog = $("#event-log");
const lastCapture = $("#last-capture");

let lastCapsKey = "";
let seenEventCount = 0;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || res.statusText || "Request failed");
  }
  return data;
}

function fmtAge(age) {
  if (age == null) return "—";
  return `${age.toFixed(2)}s`;
}

function stateDot(state) {
  if (state === "streaming" || state === true) return "ok";
  if (state === "stale" || state === "no_signal") return "warn";
  if (state === "stopped" || state === false) return "bad";
  return "unknown";
}

function renderDl(el, rows) {
  el.innerHTML = rows
    .map(
      ([k, v]) =>
        `<dt>${k}</dt><dd>${v}</dd>`
    )
    .join("");
}

function updateSimBadge(status) {
  const hdmi = status.hdmi;
  const cam = status.camera;
  if (hdmi.alive && cam.connected) {
    simBadge.className = "badge ok";
    simBadge.textContent = "Simultaneous OK — HDMI + USB";
  } else if (cam.connected && !hdmi.alive && hdmi.streaming) {
    simBadge.className = "badge bad";
    simBadge.textContent = "USB connected — HDMI lost";
  } else if (cam.connected && !hdmi.streaming) {
    simBadge.className = "badge warn";
    simBadge.textContent = "USB connected — HDMI not started";
  } else if (hdmi.alive && !cam.connected) {
    simBadge.className = "badge warn";
    simBadge.textContent = "HDMI only — USB not connected";
  } else {
    simBadge.className = "badge unknown";
    simBadge.textContent = "Neither active yet";
  }
}

function updateHdmi(hdmi) {
  const aliveClass = stateDot(hdmi.state);
  streamOverlay.classList.toggle("hidden", hdmi.state === "streaming");
  streamOverlay.textContent = {
    streaming: "",
    stopped: "Stream stopped",
    no_signal: "Device open — no HDMI signal",
    stale: "Signal lost / stale frames",
  }[hdmi.state] || hdmi.state;

  renderDl(hdmiStats, [
    ["State", `<span class="dot ${aliveClass}"></span>${hdmi.state}`],
    ["Device", String(hdmi.device)],
    ["Input", hdmi.width && hdmi.height ? `${hdmi.width}×${hdmi.height} @ ${hdmi.requested_fps} fps requested` : "—"],
    ["Picture aspect", hdmi.content_aspect ? hdmi.content_aspect.toFixed(2) : "—"],
    ["Preview", fmtSize(hdmi.output_width, hdmi.output_height)],
    ["FPS", hdmi.fps.toFixed(1)],
    ["Frames", String(hdmi.frames_received)],
    ["Last frame", fmtAge(hdmi.last_frame_age_s)],
    ["Error", hdmi.error || "—"],
  ]);
}

function fmtSize(w, h) {
  return w && h ? `${w}×${h}` : "—";
}

function updateUsbLive(usb) {
  usbOverlay.classList.toggle("hidden", usb.state === "streaming");
  usbOverlay.textContent = {
    stopped: "USB live view stopped",
    starting: "Starting USB live view…",
    stale: "USB live view paused / stale",
  }[usb.state] || usb.state;
  if (!usb.enabled && usbStream.getAttribute("src")) {
    usbStream.removeAttribute("src");
  } else if (usb.enabled && !usbStream.getAttribute("src")) {
    usbStream.src = `/usb_stream?t=${Date.now()}`;
  }

  renderDl(usbStats, [
    ["State", `<span class="dot ${stateDot(usb.state)}"></span>${usb.state}`],
    ["Camera frame", fmtSize(usb.source_width, usb.source_height)],
    ["Preview", fmtSize(usb.output_width, usb.output_height)],
    ["FPS", usb.fps.toFixed(1)],
    ["Frames", String(usb.frames_received)],
    ["Last frame", fmtAge(usb.last_frame_age_s)],
    ["Error", usb.error || "—"],
  ]);
}

function updateCamera(cam) {
  renderDl(camStats, [
    ["USB / gphoto2", `<span class="dot ${stateDot(cam.connected)}"></span>${cam.connected ? "connected" : "disconnected"}`],
    ["Model", cam.model || "—"],
    ["Error", cam.error || "—"],
  ]);

  const caps = cam.capabilities || {};
  const key = JSON.stringify(caps);
  if (key !== lastCapsKey) {
    lastCapsKey = key;
    renderExposure(caps.exposure || {});
    renderActions(caps.actions || {});
  }

  if (cam.last_capture && cam.last_capture.filename) {
    lastCapture.innerHTML = `
      Last: ${cam.last_capture.filename}
      (${cam.last_capture.elapsed_s}s)
      <img src="/captures/${encodeURIComponent(cam.last_capture.filename)}" alt="Last capture">
    `;
  }
}

function renderExposure(exposure) {
  const names = Object.keys(exposure);
  if (!names.length) {
    exposureControls.innerHTML =
      '<p class="unsupported">No exposure settings detected (connect camera first).</p>';
    return;
  }

  exposureControls.innerHTML = names
    .map((name) => {
      const info = exposure[name];
      const choices = info.choices || [];
      let input;
      if (choices.length) {
        input = `<select data-setting="${name}">${choices
          .map(
            (c) =>
              `<option value="${c}" ${String(c) === String(info.current) ? "selected" : ""}>${c}</option>`
          )
          .join("")}</select>`;
      } else {
        input = `<input type="text" data-setting="${name}" value="${info.current ?? ""}">`;
      }
      return `
        <div class="control-row">
          <span class="name">${name}</span>
          ${input}
          <button data-apply="${name}">Apply</button>
        </div>`;
    })
    .join("");

  exposureControls.querySelectorAll("[data-apply]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-apply");
      const field = exposureControls.querySelector(`[data-setting="${name}"]`);
      btn.disabled = true;
      try {
        await api(`/api/camera/setting/${encodeURIComponent(name)}`, {
          method: "POST",
          body: JSON.stringify({ value: field.value }),
        });
        await refresh();
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function renderActions(actions) {
  const labels = ["autofocus", "zoom", "viewfinder"];
  actionControls.innerHTML = labels
    .map((label) => {
      const info = actions[label];
      if (!info || !info.supported) {
        return `<div class="control-row"><span class="name">${label}</span><span class="unsupported">not supported</span><span></span></div>`;
      }
      const cfg = info.config || {};
      if (label === "zoom" && (cfg.choices || []).length) {
        return `
          <div class="control-row">
            <span class="name">zoom (${cfg.name})</span>
            <select data-zoom="1">
              ${(cfg.choices || [])
                .map(
                  (c) =>
                    `<option value="${c}" ${String(c) === String(cfg.current) ? "selected" : ""}>${c}</option>`
                )
                .join("")}
            </select>
            <button data-action="zoom">Apply</button>
          </div>`;
      }
      if (label === "zoom") {
        return `
          <div class="control-row">
            <span class="name">zoom (${cfg.name})</span>
            <input type="text" data-zoom="1" value="${cfg.current ?? ""}">
            <button data-action="zoom">Apply</button>
          </div>`;
      }
      return `
        <div class="control-row">
          <span class="name">${label} (${cfg.name})</span>
          <span class="unsupported">current: ${cfg.current ?? "—"}</span>
          <button data-action="${label}">Trigger</button>
        </div>`;
    })
    .join("");

  actionControls.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const label = btn.getAttribute("data-action");
      const body = {};
      if (label === "zoom") {
        const field = actionControls.querySelector("[data-zoom]");
        body.value = field.value;
      }
      btn.disabled = true;
      try {
        await api(`/api/camera/action/${encodeURIComponent(label)}`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        await refresh();
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function renderEvents(events) {
  if (!events || events.length < seenEventCount) {
    eventLog.innerHTML = "";
    seenEventCount = 0;
  }
  const fresh = events.slice(seenEventCount);
  seenEventCount = events.length;
  for (const ev of fresh) {
    const li = document.createElement("li");
    li.className = ev.level || "info";
    const ts = new Date((ev.t || 0) * 1000).toLocaleTimeString();
    li.innerHTML = `<span class="ts">${ts}</span>${ev.message}`;
    eventLog.appendChild(li);
  }
  if (fresh.length) {
    eventLog.scrollTop = eventLog.scrollHeight;
  }
}

async function refreshDevices() {
  const data = await api("/api/devices");
  const current = deviceSelect.value;
  deviceSelect.innerHTML = (data.video_devices || [])
    .map(
      (d) =>
        `<option value="${d.index}">${d.index} (${d.width}×${d.height})</option>`
    )
    .join("");
  if (![...deviceSelect.options].some((o) => o.value === current) && deviceSelect.options.length) {
    // keep first
  } else if (current) {
    deviceSelect.value = current;
  }
}

async function refresh() {
  const status = await api("/api/status");
  updateSimBadge(status);
  updateHdmi(status.hdmi);
  updateUsbLive(status.usb_live);
  updateCamera(status.camera);
  renderEvents(status.events || []);
  if (status.hdmi && deviceSelect.options.length) {
    deviceSelect.value = String(status.hdmi.device);
  }
}

function wireButtons() {
  $("#btn-scan").onclick = () => refreshDevices().catch((e) => alert(e.message));
  $("#btn-hdmi-start").onclick = async () => {
    try {
      const body = deviceSelect.value ? { device: Number(deviceSelect.value) } : {};
      await api("/api/hdmi/start", { method: "POST", body: JSON.stringify(body) });
      // Bust img cache so the multipart stream reconnects cleanly.
      $("#stream").src = `/stream?t=${Date.now()}`;
      await refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  $("#btn-hdmi-stop").onclick = async () => {
    await api("/api/hdmi/stop", { method: "POST", body: "{}" });
    await refresh();
  };
  $("#btn-hdmi-restart").onclick = async () => {
    try {
      await api("/api/hdmi/restart", { method: "POST", body: "{}" });
      $("#stream").src = `/stream?t=${Date.now()}`;
      await refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  $("#btn-usb-start").onclick = async () => {
    try {
      await api("/api/usb-live/start", { method: "POST", body: "{}" });
      usbStream.src = `/usb_stream?t=${Date.now()}`;
      await refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  $("#btn-usb-stop").onclick = async () => {
    await api("/api/usb-live/stop", { method: "POST", body: "{}" });
    await refresh();
  };
  $("#btn-cam-connect").onclick = async () => {
    try {
      await api("/api/camera/connect", { method: "POST", body: "{}" });
      await refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  $("#btn-cam-disconnect").onclick = async () => {
    await api("/api/camera/disconnect", { method: "POST", body: "{}" });
    lastCapsKey = "";
    await refresh();
  };
  $("#btn-caps").onclick = async () => {
    try {
      lastCapsKey = "";
      await api("/api/camera/refresh-capabilities", { method: "POST", body: "{}" });
      await refresh();
    } catch (e) {
      alert(e.message);
    }
  };
  $("#btn-capture").onclick = async () => {
    const btn = $("#btn-capture");
    btn.disabled = true;
    try {
      const data = await api("/api/camera/capture", {
        method: "POST",
        body: JSON.stringify({ restart_hdmi: $("#auto-restart").checked }),
      });
      if (data.hdmi_restarted) {
        $("#stream").src = `/stream?t=${Date.now()}`;
      }
      await refresh();
    } catch (e) {
      alert(e.message);
    } finally {
      btn.disabled = false;
    }
  };
  $("#btn-clear-log").onclick = () => {
    eventLog.innerHTML = "";
  };
  document.querySelectorAll(".maximize").forEach((btn) => {
    btn.onclick = () => {
      const wrap = btn.closest(".stream-wrap");
      if (document.fullscreenElement === wrap) {
        document.exitFullscreen();
      } else {
        wrap.requestFullscreen().catch((e) => alert(e.message));
      }
    };
  });
}

wireButtons();
refreshDevices().catch(() => {});
refresh().catch(console.error);
setInterval(() => refresh().catch(() => {}), 1000);
