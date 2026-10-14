const state = {
  snapshot: { profiles: [], accounts: [], strategies: [], capabilities: [] },
  health: null,
  selected: null,
  dirty: false,
  update: null,
  refreshing: false,
  refreshingLogs: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "content-type": "application/json", ...(options.headers || {}) },
    });
  } catch {
    throw new Error("Studio 서버와 연결할 수 없습니다. Trade Router Studio 실행 창이 켜져 있는지 확인하세요.");
  }
  if (response.status === 401) {
    $("#auth-warning").classList.remove("hidden");
    throw new Error("웹 인증이 만료되었습니다.");
  }
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch {}
    let message = body.message;
    if (!message && Array.isArray(body.detail) && body.detail.length) {
      const first = body.detail[0];
      const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      message = (field ? field + ": " : "") + (first.msg || "입력값을 확인하세요.");
    }
    throw new Error((body.code ? body.code + ": " : "") + (message || "요청 실패 · HTTP " + response.status));
  }
  return response.status === 204 ? null : response.json();
}

function esc(value) {
  return String(value == null ? "" : value).replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.style.background = error ? "#992d3a" : "#1e2b3a";
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 3500);
}

function table(headers, rows) {
  if (!rows.length) return '<div class="empty"><span>등록된 항목이 없습니다.</span></div>';
  return "<table><thead><tr>" +
    headers.map((header) => "<th>" + header + "</th>").join("") +
    "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
}

async function refresh() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    const results = await Promise.all([api("/api/health"), api("/api/snapshot")]);
    state.health = results[0];
    state.snapshot = results[1];
    render();
  } catch (error) {
    toast(error.message, true);
    $("#status-text").textContent = "연결 안 됨";
  } finally {
    state.refreshing = false;
  }
}

function render() {
  const health = state.health;
  const snapshot = state.snapshot;
  $("#status-dot").className = health.status;
  $("#status-text").textContent = health.status === "ready" ? "Studio 정상" : "Router 확인 필요";
  $("#app-version").textContent = "v" + health.version;
  $("#router-state").textContent = health.router.status;
  $("#order-state").textContent = health.router.accepting_orders ? "주문 권한 열림" : "주문 권한 닫힘";
  $("#profile-count").textContent = snapshot.profiles.length;
  $("#account-count").textContent = snapshot.accounts.length;
  $("#account-armed").textContent = "허용 " + snapshot.accounts.filter((item) => item.armed).length;
  $("#running-count").textContent = snapshot.strategies.filter(
    (item) => item.process && item.process.state === "running",
  ).length;
  $("#strategy-count").textContent = "등록 " + snapshot.strategies.length;

  const providerNames = { kis: "한국투자증권 KIS", namuh: "NH투자증권 NAMUH", simulated: "시뮬레이션" };
  const environmentNames = { live: "실전 계좌", paper: "모의 계좌" };
  $("#profiles").innerHTML = table(
    ["연결 이름", "증권사", "인증", "작업"],
    snapshot.profiles.map((item) => {
      const hasAccount = snapshot.accounts.some((account) => account.profile_id === item.id);
      const action = hasAccount
        ? '<button class="secondary" data-check-profile="' + esc(item.id) + '">연결 확인</button>'
        : '<button class="secondary" data-add-account-profile="' + esc(item.id) +
          '">계좌 등록</button>';
      return (
      "<tr><td><strong>" + esc(item.id) + "</strong></td>" +
      "<td>" + esc(providerNames[item.provider] || item.provider) + "</td>" +
      '<td><span class="badge ' + (item.secret_configured ? "ready" : "") + '">' +
      (item.secret_configured ? "설정됨" : "불필요/미설정") + "</span></td>" +
      '<td><div class="row-actions">' + action + "</div></td></tr>"
      );
    }),
  );

  $("#accounts").innerHTML = table(
    ["별칭", "증권사 연결", "계좌 구분", "계좌", "주문", "작업"],
    snapshot.accounts.map((item) =>
      "<tr><td><strong>" + esc(item.alias) + "</strong></td>" +
      "<td>" + esc(item.profile_id) + "</td><td>" +
      esc(environmentNames[item.environment] || item.environment) + "</td><td>" + esc(item.masked_account) + "</td>" +
      '<td><span class="badge ' + (item.armed ? "ready" : "") + '">' +
      (item.armed ? "허용" : "차단") + "</span></td>" +
      '<td><div class="row-actions"><button class="' + (item.armed ? "danger" : "secondary") +
      '" data-account-arm="' + esc(item.alias) + '" data-armed="' + item.armed + '">' +
      (item.armed ? "차단" : "허용") + "</button></div></td></tr>",
    ),
  );

  $("#strategies").innerHTML = table(
    ["전략", "거래 계좌", "시세 연결", "승인", "프로세스", "작업"],
    snapshot.strategies.map((item) => {
      const processState = item.process ? item.process.state : "stopped";
      return "<tr><td><strong>" + esc(item.strategy.id) + "</strong></td>" +
        "<td>" + esc(item.strategy.trading_account) + "</td>" +
        "<td>" + esc(item.strategy.market_data) + "</td>" +
        '<td><span class="badge ' + (item.strategy.armed ? "ready" : "") + '">' +
        (item.strategy.armed ? "허용" : "차단") + "</span></td>" +
        '<td><span class="badge ' + esc(processState) + '">' + esc(processState) + "</span></td>" +
        '<td><div class="row-actions"><button class="' +
        (item.strategy.armed ? "danger" : "secondary") + '" data-strategy-arm="' +
        esc(item.strategy.id) + '" data-armed="' + item.strategy.armed + '">' +
        (item.strategy.armed ? "차단" : "허용") + "</button></div></td></tr>";
    }),
  );
  bindRowActions();
  renderList();
}

function renderUpdateButton() {
  const button = $("#update-app");
  const update = state.update;
  if (!update || !update.available) {
    button.textContent = "업데이트 확인";
  } else if (!update.downloaded) {
    button.textContent = "v" + update.latest_version + " 업데이트 시작";
  } else {
    button.textContent = "업데이트 적용 후 재시작";
  }
}

async function handleUpdate() {
  const button = $("#update-app");
  button.disabled = true;
  try {
    if (!state.update || !state.update.available) {
      state.update = await api("/api/app/update?refresh=true");
      if (!state.update.available) {
        toast("현재 최신 버전입니다. · v" + state.update.current_version);
      } else if (!state.update.package_ready) {
        throw new Error("최신 GitHub 배포에 Windows 업데이트 파일이 없습니다.");
      } else {
        toast("새 버전 v" + state.update.latest_version + "을 사용할 수 있습니다.");
      }
      renderUpdateButton();
      return;
    }
    if (!state.update.downloaded) {
      button.textContent = "업데이트 다운로드 중…";
      const downloaded = await api("/api/app/update/download", { method: "POST" });
      state.update.downloaded = true;
      state.update.latest_version = downloaded.version;
      toast("업데이트 다운로드와 SHA-256 검증을 마쳤습니다.");
      renderUpdateButton();
      return;
    }
    if (!confirm("실행 중인 전략과 Trade Router를 정리한 뒤 업데이트하고 다시 시작할까요?")) return;
    button.textContent = "재시작 준비 중…";
    await api(
      "/api/app/update/apply?version=" + encodeURIComponent(state.update.latest_version),
      { method: "POST" },
    );
    toast("업데이트를 적용하고 다시 시작합니다.");
  } catch (error) {
    toast(error.message, true);
    renderUpdateButton();
  } finally {
    button.disabled = false;
  }
}

async function exitApp() {
  if (!confirm("실행 중인 전략과 중앙 Router를 정리하고 프로그램을 종료할까요?")) return;
  try {
    await api("/api/app/stop", { method: "POST" });
    toast("프로그램을 종료하고 있습니다.");
    $("#exit-app").disabled = true;
    $("#update-app").disabled = true;
  } catch (error) {
    toast(error.message, true);
  }
}

function bindRowActions() {
  $$("[data-check-profile]").forEach((button) => {
    button.onclick = async () => {
      button.disabled = true;
      try {
        const result = await api(
          "/api/profiles/" + encodeURIComponent(button.dataset.checkProfile) + "/check",
          { method: "POST" },
        );
        if (result.status === "account_required") {
          toast(result.message);
          showAccountDialog(button.dataset.checkProfile);
          return;
        }
        toast(result.ok ? "연결이 정상입니다." : "연결 확인을 마쳤습니다.");
        await refresh();
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = false;
      }
    };
  });
  $$('[data-add-account-profile]').forEach((button) => {
    button.onclick = () => showAccountDialog(button.dataset.addAccountProfile);
  });
  $$("[data-account-arm]").forEach((button) => {
    button.onclick = () => changeArm(
      "accounts", button.dataset.accountArm, button.dataset.armed === "true",
    );
  });
  $$("[data-strategy-arm]").forEach((button) => {
    button.onclick = () => changeArm(
      "strategies", button.dataset.strategyArm, button.dataset.armed === "true",
    );
  });
}

async function changeArm(kind, id, currentlyArmed) {
  const nextArmed = !currentlyArmed;
  if (nextArmed && !confirm(
    id + "의 실전 주문 권한을 허용할까요? 계좌와 전략이 모두 허용되어야 주문할 수 있습니다.",
  )) return;
  try {
    const action = nextArmed ? "arm" : "disarm";
    await api("/api/" + kind + "/" + encodeURIComponent(id) + "/" + action, { method: "POST" });
    toast(id + " 주문 권한을 " + (nextArmed ? "허용" : "차단") + "했습니다.");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderList() {
  const rows = state.snapshot.strategies;
  $("#strategy-list").innerHTML = rows.length
    ? rows.map((item) => {
        const active = state.selected === item.strategy.id ? "active" : "";
        const processState = item.process ? item.process.state : "stopped";
        return '<div class="strategy-item ' + active + '" data-strategy="' +
          esc(item.strategy.id) + '"><strong>' + esc(item.strategy.id) +
          "</strong><small>" + esc(processState) + " · " +
          (item.script ? "코드 저장됨" : "코드 없음") + "</small></div>";
      }).join("")
    : '<div class="empty"><span>등록 전략 없음</span></div>';
  $$("[data-strategy]").forEach((element) => {
    element.onclick = () => selectStrategy(element.dataset.strategy);
  });
}

async function selectStrategy(id) {
  if (state.dirty && !confirm("저장하지 않은 변경을 버리고 이동할까요?")) return;
  state.selected = id;
  state.dirty = false;
  renderList();
  const item = state.snapshot.strategies.find((candidate) => candidate.strategy.id === id);
  $("#empty").classList.add("hidden");
  $("#editor-body").classList.remove("hidden");
  $("#selected-name").textContent = id;
  $("#binding").textContent = item.strategy.trading_account + " · " + item.strategy.market_data;
  setProcess(item.process || { state: "stopped" });
  try {
    $("#source").value = (await api("/api/strategies/" + encodeURIComponent(id) + "/script")).source;
  } catch (error) {
    if (error.message.includes("NOT_FOUND")) {
      $("#source").value = (
        await api("/api/strategies/" + encodeURIComponent(id) + "/script/template")
      ).source;
    } else {
      toast(error.message, true);
    }
  }
  setDirty(false);
  refreshLogs();
}

function setProcess(process) {
  const badge = $("#process");
  badge.textContent = process.state;
  badge.className = "badge " + process.state;
  const running = ["starting", "running", "backoff"].includes(process.state);
  $("#run").disabled = running;
  $("#stop").disabled = !running;
  $("#save").disabled = running;
  $("#source").readOnly = running;
}

function setDirty(value) {
  state.dirty = value;
  $("#dirty").textContent = value ? "저장되지 않은 변경" : "저장됨";
}

async function save() {
  if (!state.selected) return;
  const result = await api("/api/strategies/" + encodeURIComponent(state.selected) + "/script", {
    method: "PUT",
    body: JSON.stringify({ source: $("#source").value }),
  });
  setDirty(false);
  toast("저장 완료 · " + result.validation.bytes + " bytes");
  await refresh();
}

async function run() {
  await save();
  setProcess(await api("/api/strategies/" + encodeURIComponent(state.selected) + "/start", {
    method: "POST",
  }));
  toast("전략 프로세스를 시작했습니다.");
  await refresh();
}

async function stop() {
  setProcess(await api("/api/strategies/" + encodeURIComponent(state.selected) + "/stop", {
    method: "POST",
  }));
  toast("전략을 중지했습니다.");
  await refresh();
}

async function refreshLogs() {
  if (!state.selected || state.refreshingLogs) return;
  state.refreshingLogs = true;
  try {
    const id = encodeURIComponent(state.selected);
    const results = await Promise.all([
      api("/api/strategies/" + id + "/status"),
      api("/api/strategies/" + id + "/logs"),
    ]);
    setProcess(results[0]);
    const element = $("#logs");
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 35;
    element.textContent = results[1].logs || "아직 실행 로그가 없습니다.";
    if (atBottom) element.scrollTop = element.scrollHeight;
  } catch {
  } finally {
    state.refreshingLogs = false;
  }
}

function updateCredentialFields() {
  const provider = $("#profile-provider").value;
  const simulated = provider === "simulated";
  $("#credential-fields").classList.toggle("hidden", simulated);
  $("#profile-key").required = !simulated;
  $("#profile-secret").required = !simulated;
  if (provider === "namuh") {
    $("#credential-title").textContent = "NH PLUG API 인증정보";
    $("#credential-help").textContent = "NH PLUG 포털에서 발급받은 App Key와 App Secret을 입력하세요.";
    $("#profile-key-label").textContent = "NH PLUG App Key";
    $("#profile-secret-label").textContent = "NH PLUG App Secret";
    $("#profile-key").placeholder = "NH PLUG App Key";
    $("#profile-secret").placeholder = "NH PLUG App Secret";
  } else if (provider === "kis") {
    $("#credential-title").textContent = "KIS Developers API 인증정보";
    $("#credential-help").textContent = "KIS Developers에서 발급받은 App Key와 App Secret을 입력하세요.";
    $("#profile-key-label").textContent = "KIS App Key";
    $("#profile-secret-label").textContent = "KIS App Secret";
    $("#profile-key").placeholder = "KIS App Key";
    $("#profile-secret").placeholder = "KIS App Secret";
  }
}

function showProfileDialog() {
  $("#profile-form").reset();
  updateCredentialFields();
  $("#profile-dialog").showModal();
  $("#profile-id").focus();
}

async function registerProfile(event) {
  event.preventDefault();
  const provider = $("#profile-provider").value;
  const body = {
    id: $("#profile-id").value.trim(),
    provider,
    display_name: $("#profile-name").value.trim() || null,
    app_key: provider === "simulated" ? null : $("#profile-key").value.trim(),
    app_secret: provider === "simulated" ? null : $("#profile-secret").value,
    settings: {},
  };
  try {
    const result = await api("/api/profiles", { method: "POST", body: JSON.stringify(body) });
    $("#profile-secret").value = "";
    $("#profile-dialog").close();
    toast("증권사 API 연결을 추가했습니다.");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

function showAccountDialog(profileId = null) {
  const profiles = state.snapshot.profiles;
  if (!profiles.length) {
    toast("증권사 API 연결을 먼저 추가하세요.", true);
    return;
  }
  $("#account-form").reset();
  $("#account-profile").innerHTML = profiles.map(
    (item) => '<option value="' + esc(item.id) + '">' + esc(item.id) +
      " · " + esc(item.provider) + "</option>",
  ).join("");
  if (typeof profileId === "string" && profiles.some((item) => item.id === profileId)) {
    $("#account-profile").value = profileId;
  }
  updateEnvironmentSelect("#account-profile", "#account-environment");
  $("#account-dialog").showModal();
  $("#account-alias").focus();
}

function updateEnvironmentSelect(profileSelector, environmentSelector) {
  const profile = state.snapshot.profiles.find((item) => item.id === $(profileSelector).value);
  if (!profile) return;
  const environments = ["auto", "shared"].includes(profile.usage)
    ? ["paper", "live"]
    : [profile.usage];
  const select = $(environmentSelector);
  const current = select.value;
  select.innerHTML = environments.map(
    (item) => '<option value="' + item + '">' + (item === "live" ? "실전 계좌" : "모의 계좌") + "</option>",
  ).join("");
  if (environments.includes(current)) select.value = current;
  select.disabled = environments.length === 1;
  if (profileSelector === "#account-profile") {
    $("#account-type-help").textContent = environments.length === 1
      ? (environments[0] === "live" ? "실전용 키이므로 실전 계좌로 자동 지정됩니다." : "모의용 키이므로 모의 계좌로 자동 지정됩니다.")
      : "계좌 구분을 선택하면 해당 증권사 API 서버로 자동 연결합니다.";
  }
}

function updateStrategyMarketConnection() {
  const profile = state.snapshot.profiles.find((item) => item.id === $("#strategy-market").value);
  const account = state.snapshot.accounts.find((item) => item.alias === $("#strategy-account").value);
  if (!profile || !account) return;
  const environment = ["auto", "shared"].includes(profile.usage)
    ? account.environment
    : profile.usage;
  $("#strategy-market-environment").value = environment;
  const kind = environment === "live" ? "실전" : "모의";
  $("#strategy-market-help").textContent = kind + " 시세 API를 자동 사용합니다. 서버 주소를 따로 설정할 필요가 없습니다.";
}

function optionalNumber(selector) {
  const value = $(selector).value.trim();
  return value === "" ? undefined : Number(value);
}

async function registerAccount(event) {
  event.preventDefault();
  const risk = {};
  [
    ["max_order_krw", "#risk-order"],
    ["max_daily_buy_krw", "#risk-daily"],
    ["max_exposure_krw", "#risk-exposure"],
    ["max_open_orders", "#risk-open"],
  ].forEach((field) => {
    const value = optionalNumber(field[1]);
    if (value !== undefined) risk[field[0]] = value;
  });
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({
        alias: $("#account-alias").value.trim(),
        profile_id: $("#account-profile").value,
        environment: $("#account-environment").value,
        account_number: $("#account-number").value.trim(),
        risk,
      }),
    });
    $("#account-number").value = "";
    $("#account-dialog").close();
    toast("계좌를 등록했습니다. 주문 권한은 차단 상태입니다.");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

function showStrategyDialog() {
  const snapshot = state.snapshot;
  if (!snapshot.accounts.length || !snapshot.profiles.length) {
    toast("먼저 증권사 API 연결과 계좌를 등록하세요.", true);
    return;
  }
  $("#register-form").reset();
  $("#strategy-account").innerHTML = snapshot.accounts.map(
    (item) => '<option value="' + esc(item.alias) + '">' + esc(item.alias) + "</option>",
  ).join("");
  $("#strategy-market").innerHTML = snapshot.profiles.map(
    (item) => '<option value="' + esc(item.id) + '">' + esc(item.id) +
      " · " + esc(item.provider) + "</option>",
  ).join("");
  updateStrategyMarketConnection();
  $("#register").showModal();
  $("#strategy-id").focus();
}

async function registerStrategy(event) {
  event.preventDefault();
  try {
    const id = $("#strategy-id").value.trim();
    await api("/api/strategies", {
      method: "POST",
      body: JSON.stringify({
        id,
        trading_account: $("#strategy-account").value,
        market_data: $("#strategy-market").value,
        market_environment: $("#strategy-market-environment").value,
      }),
    });
    $("#register").close();
    toast("전략을 등록했습니다. 주문 권한은 차단 상태입니다.");
    await refresh();
    await selectStrategy(id);
  } catch (error) {
    toast(error.message, true);
  }
}

function go(view) {
  $$(".nav").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach((item) => item.classList.toggle("active", item.id === view));
  if (view === "editor") refreshLogs();
}

$$(".nav").forEach((item) => { item.onclick = () => go(item.dataset.view); });
$$("[data-go]").forEach((item) => { item.onclick = () => go(item.dataset.go); });
$$("[data-close-dialog]").forEach((item) => {
  item.onclick = () => item.closest("dialog").close();
});
$("#refresh").onclick = refresh;
$("#update-app").onclick = handleUpdate;
$("#exit-app").onclick = exitApp;
$("#new-profile").onclick = showProfileDialog;
$("#new-account").onclick = () => showAccountDialog();
$("#new-strategy").onclick = showStrategyDialog;
$("#profile-provider").onchange = updateCredentialFields;
$("#account-profile").onchange = () => updateEnvironmentSelect("#account-profile", "#account-environment");
$("#strategy-account").onchange = updateStrategyMarketConnection;
$("#strategy-market").onchange = updateStrategyMarketConnection;
$("#profile-form").onsubmit = registerProfile;
$("#account-form").onsubmit = registerAccount;
$("#register-form").onsubmit = registerStrategy;
$("#source").oninput = () => setDirty(true);
$("#source").onkeydown = (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    const start = event.target.selectionStart;
    event.target.setRangeText("    ", start, event.target.selectionEnd, "end");
    setDirty(true);
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save().catch((error) => toast(error.message, true));
  }
};
$("#save").onclick = () => save().catch((error) => toast(error.message, true));
$("#validate").onclick = async () => {
  try {
    const result = await api(
      "/api/strategies/" + encodeURIComponent(state.selected) + "/script/validate",
      { method: "POST", body: JSON.stringify({ source: $("#source").value }) },
    );
    toast("코드가 올바릅니다 · " + result.bytes + " bytes");
  } catch (error) {
    toast(error.message, true);
  }
};
$("#template").onclick = async () => {
  if (state.dirty && !confirm("현재 코드를 예제로 바꿀까요?")) return;
  $("#source").value = (
    await api("/api/strategies/" + encodeURIComponent(state.selected) + "/script/template")
  ).source;
  setDirty(true);
};
$("#run").onclick = () => run().catch((error) => toast(error.message, true));
$("#stop").onclick = () => stop().catch((error) => toast(error.message, true));
$$("[data-tab]").forEach((item) => {
  item.onclick = () => {
    $$("[data-tab]").forEach((candidate) => candidate.classList.toggle("active", candidate === item));
    $("#logs").classList.toggle("hidden", item.dataset.tab !== "logs");
    $("#sdk").classList.toggle("hidden", item.dataset.tab !== "sdk");
  };
});
window.onbeforeunload = (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
};

refresh();
setInterval(refresh, 5000);
setInterval(refreshLogs, 2000);
