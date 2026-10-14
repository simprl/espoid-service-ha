const p = ":host{display:block;font:14px/1.5 system-ui,sans-serif;color:var(--primary-text-color,#23352d);background:var(--primary-background-color,#f3f7f4);min-height:100vh;--green:#168054;--border:var(--divider-color,#dce5df)}*{box-sizing:border-box}main{max-width:1300px;margin:auto;padding:24px}header{display:flex;gap:16px;align-items:center;justify-content:space-between}h1{font-size:25px;margin:0}h2{font-size:19px;margin:0 0 12px}h3{font-size:16px}p{margin:8px 0}nav,.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}button,input,select,textarea{font:inherit;color:inherit}button{border:1px solid var(--border);background:var(--card-background-color,#fff);border-radius:8px;padding:9px 13px;cursor:pointer}button:hover{border-color:var(--green)}button.primary,button[aria-selected=true]{background:var(--green);border-color:var(--green);color:#fff}button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #58b889;outline-offset:2px}input,select,textarea{border:1px solid var(--border);border-radius:7px;padding:9px;background:var(--card-background-color,#fff);max-width:100%}input[type=search]{flex:1;min-width:180px}label{display:grid;gap:5px;margin:12px 0;font-weight:600}.card{border:1px solid var(--border);border-radius:12px;background:var(--card-background-color,#fff);padding:20px;margin:16px 0}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--border)}th{font-weight:600;color:var(--secondary-text-color,#64776c)}td small,.muted{color:var(--secondary-text-color,#64776c)}code{font-size:12px;overflow-wrap:anywhere}pre,textarea{width:100%;white-space:pre-wrap;overflow-wrap:anywhere}pre{max-height:460px;overflow:auto;padding:12px;background:var(--secondary-background-color,#edf3ef);border-radius:8px}textarea{min-height:210px;font-family:monospace;font-weight:400}dl{display:grid;grid-template-columns:minmax(120px,1fr) 2fr;gap:8px}dt{color:var(--secondary-text-color,#64776c)}dd{margin:0;overflow-wrap:anywhere}.notice{border-left:4px solid var(--green);padding:12px;background:var(--card-background-color,#fff)}.error{border-left-color:#b74040}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.badge{border-radius:20px;padding:4px 9px;background:#e8f4ec;white-space:nowrap}dialog{color:inherit;background:var(--card-background-color,#fff);border:1px solid var(--border);border-radius:12px;max-width:min(620px,95vw)}dialog::backdrop{background:#0005}@media(max-width:700px){main{padding:12px}.grid{grid-template-columns:1fr}header{align-items:flex-start}th,td{padding:8px}dl{grid-template-columns:1fr}dd{margin-bottom:6px}}@media(prefers-reduced-motion:no-preference){button{transition:background .15s,border-color .15s}}", u = {
  ota_z2m: "Z2M → Wi-Fi update",
  ota_url: "Wi-Fi update",
  ota_upload: "Direct upload",
  profile_store: "Save profile",
  reboot_wifi: "Restart in Wi-Fi",
  reboot_zigbee: "Return to Zigbee",
  recovery_retry: "Retry recovery",
  search_running: "Searching",
  search_complete: "Search completed",
  search_timeout: "Search time limit reached",
  search_cancelled: "Search stopped",
  search_failed: "Search failed",
  yes: "Yes",
  no: "No",
  unknown_value: "Not checked",
  devices: "Devices",
  service: "Service",
  firmware: "Firmware",
  history: "History",
  settings: "Settings",
  add: "Add device",
  nodeType: "Device",
  name: "Name",
  address: "Service address",
  identity: "Node ID",
  connection: "Connection",
  version: "Firmware version",
  refresh: "Refresh",
  open: "Open",
  filter: "Find by name, ID or address",
  all: "All states",
  wifi: "Wi-Fi service available",
  service_closed: "HTTP not verified · Z2M binding present",
  unknown: "HTTP not verified",
  empty: "No devices added",
  choose: "Choose a device",
  wake: "Request Wi-Fi through Z2M",
  hold: "Extend Wi-Fi by 30 minutes",
  zigbee: "Return to Zigbee",
  reboot: "Restart in Wi-Fi",
  prepare: "Configure remote updates",
  prepareHelp: "Sets the shared HA announcement address and this node’s firmware source. Do this once while Wi-Fi is available.",
  status: "Read status",
  profile: "Device profile",
  read: "Read profile",
  validate: "Validate",
  store: "Save profile",
  trace: "Download diagnostics",
  snapshot: "Download status JSON",
  import: "Import firmware",
  manifest: "OTA manifest (.json)",
  image: "Application image (.bin)",
  selectFirmware: "Select firmware",
  mode: "Update method",
  z2m: "Z2M → Wi-Fi download (primary)",
  url: "Wi-Fi download",
  upload: "HA → ESP direct upload (fallback)",
  install: "Start update",
  confirm: "Confirm running image",
  pending: "Awaiting firmware confirmation",
  running: "Running version",
  marker: "Installed image SHA-256",
  state: "Operation state",
  message: "Message",
  networks: "Device search networks",
  networksHelp: "Comma-separated private networks, e.g. 192.168.1.0/24. Used only when you start a search.",
  base: "HA LAN address for firmware",
  baseHelp: "Address reachable from ESP, e.g. http://192.168.1.10:8123.",
  prefixes: "Z2M bridge topics",
  prefixesHelp: "Optional, comma-separated base topics. Device command topics are derived automatically.",
  announcement: "MQTT service topic prefix",
  save: "Save",
  search: "Find devices in this network",
  stop: "Stop search",
  found: "Discovered devices",
  candidates: "Z2M devices available to connect",
  connect: "Connect",
  connectSelected: "Connect selected",
  close: "Close",
  rename: "Rename",
  remove: "Remove from service",
  closeOperation: "Close unresolved operation",
  confirmInstall: "Start this update on the selected physical device?",
  confirmRemove: "Remove this device from ESPOID Service? Firmware and Z2M pairing remain on the device.",
  confirmClose: "The previous result is unresolved. Close its record without declaring success? Check the device before starting another update.",
  noHistory: "No operations recorded",
  size: "Size",
  hash: "SHA-256",
  lastCheck: "Last HTTP check",
  accept: "Command accepted; device completion is not yet verified",
  ready: "Saved",
  error: "Operation failed",
  legacy: "This service requires firmware with transport-neutral identity and passive status.",
  profileWarning: "Saving changes the ESP profile. Reboot only when the device reports it is required.",
  waiting: "Waiting for Wi-Fi or fresh device status",
  prepared: "Prepared",
  sending: "Sending",
  verifying: "Image awaiting confirmation",
  verified: "Verified",
  failed: "Failed",
  uncertain: "Result uncertain",
  accepted: "Command accepted",
  closed_unverified: "Closed without verification",
  already_current: "Selected image is already running; download skipped",
  identity_mismatch: "The address belongs to a different device.",
  invalid_identity: "Invalid device identity.",
  unsupported_service: "Update firmware to enable the service API.",
  cannot_connect: "HA cannot reach the ESP HTTP service.",
  address_unknown: "Device address is unknown.",
  already_configured: "This node is already added.",
  invalid_search_network: "Select a configured private search network.",
  invalid_url: "Enter a private IPv4 HTTP address.",
  invalid_topic: "Invalid MQTT topic prefix.",
  operation_unresolved: "Resolve the existing operation before issuing another command.",
  operation_busy: "Another operation is still running.",
  ota_busy: "The ESP is updating or awaiting confirmation.",
  ota_not_prepared: "Configure remote updates once while this device is in Wi-Fi.",
  firmware_url_required: "Set the HA LAN address in shared settings.",
  z2m_device_missing: "The device is not present in the configured Z2M catalog.",
  mqtt_unavailable: "HA MQTT service is unavailable.",
  outcome_uncertain: "Connection was interrupted; do not repeat the update automatically.",
  publication_failed: "HA firmware publication could not be verified.",
  invalid_firmware: "Invalid firmware image, size or SHA-256.",
  artifact_mismatch: "The running image marker does not match this operation.",
  readback_failed: "Stored value was not verified by readback.",
  invalid_request: "Invalid request.",
  invalid_name: "Enter a name from 1 to 80 characters.",
  node_limit: "The device limit has been reached.",
  unknown_node: "Device is no longer registered.",
  storage_failed: "Service storage is unavailable.",
  invalid_response: "The device returned an invalid response.",
  device_rejected: "The device rejected the operation.",
  no_diagnostics: "No diagnostic snapshot is available.",
  search_busy: "A device search is running.",
  search_address_conflict: "Another registered device uses this address.",
  search_expired: "Search results have expired.",
  operation_failed: "Operation failed.",
  response_too_large: "Device response exceeds the permitted size."
}, f = {
  ota_z2m: "Оновлення Z2M → Wi-Fi",
  ota_url: "Оновлення через Wi-Fi",
  ota_upload: "Пряме завантаження",
  profile_store: "Зберегти профіль",
  reboot_wifi: "Перезапустити у Wi-Fi",
  reboot_zigbee: "Повернутися до Zigbee",
  recovery_retry: "Повторити відновлення",
  search_running: "Пошук",
  search_complete: "Пошук завершено",
  search_timeout: "Досягнуто ліміту часу пошуку",
  search_cancelled: "Пошук зупинено",
  search_failed: "Помилка пошуку",
  yes: "Так",
  no: "Ні",
  unknown_value: "Не перевірено",
  devices: "Пристрої",
  service: "Обслуговування",
  firmware: "Прошивки",
  history: "Історія",
  settings: "Налаштування",
  add: "Додати пристрій",
  nodeType: "Пристрій",
  name: "Назва",
  address: "Адреса обслуговування",
  identity: "ID плати",
  connection: "З’єднання",
  version: "Версія прошивки",
  refresh: "Оновити",
  open: "Відкрити",
  filter: "Пошук за назвою, ID або адресою",
  all: "Усі стани",
  wifi: "Wi-Fi обслуговування доступне",
  service_closed: "HTTP не перевірено · є прив’язка Z2M",
  unknown: "HTTP не перевірено",
  empty: "Пристрої ще не додано",
  choose: "Виберіть пристрій",
  wake: "Запросити Wi-Fi через Z2M",
  hold: "Продовжити Wi-Fi на 30 хвилин",
  zigbee: "Повернутися до Zigbee",
  reboot: "Перезапустити у Wi-Fi",
  prepare: "Налаштувати віддалене оновлення",
  prepareHelp: "Зберігає адресу сповіщень HA та джерело прошивки цієї плати. Виконайте один раз у режимі Wi-Fi.",
  status: "Прочитати статус",
  profile: "Профіль пристрою",
  read: "Прочитати профіль",
  validate: "Перевірити",
  store: "Зберегти профіль",
  trace: "Завантажити діагностику",
  snapshot: "Завантажити JSON статусу",
  import: "Імпортувати прошивку",
  manifest: "Маніфест OTA (.json)",
  image: "Образ застосунку (.bin)",
  selectFirmware: "Виберіть прошивку",
  mode: "Спосіб оновлення",
  z2m: "Z2M → завантаження через Wi-Fi (основний)",
  url: "Завантаження через Wi-Fi",
  upload: "HA → ESP напряму (резервний)",
  install: "Почати оновлення",
  confirm: "Підтвердити запущений образ",
  pending: "Очікує підтвердження прошивки",
  running: "Запущена версія",
  marker: "SHA-256 встановленого образу",
  state: "Стан операції",
  message: "Повідомлення",
  networks: "Мережі пошуку пристроїв",
  networksHelp: "Приватні мережі через кому, наприклад 192.168.1.0/24. Пошук запускається лише вашою командою.",
  base: "LAN-адреса HA для прошивок",
  baseHelp: "Адреса, доступна ESP, наприклад http://192.168.1.10:8123.",
  prefixes: "Топіки мостів Z2M",
  prefixesHelp: "Необов’язково, базові топіки через кому. Топіки команд пристроїв визначаються автоматично.",
  announcement: "Префікс MQTT сповіщень",
  save: "Зберегти",
  search: "Знайти пристрої в цій мережі",
  stop: "Зупинити пошук",
  found: "Знайдені пристрої",
  candidates: "Пристрої Z2M для підключення",
  connect: "Підключити",
  connectSelected: "Підключити вибрані",
  close: "Закрити",
  rename: "Перейменувати",
  remove: "Вилучити з обслуговування",
  closeOperation: "Закрити невизначену операцію",
  confirmInstall: "Почати це оновлення на вибраному фізичному пристрої?",
  confirmRemove: "Вилучити пристрій з ESPOID Service? Прошивка та сполучення Z2M залишаться на пристрої.",
  confirmClose: "Результат попередньої операції невизначений. Закрити запис без підтвердження успіху? Перевірте пристрій перед новим оновленням.",
  noHistory: "Операцій ще немає",
  size: "Розмір",
  hash: "SHA-256",
  lastCheck: "Остання HTTP-перевірка",
  accept: "Команду прийнято; виконання пристроєм ще не підтверджено",
  ready: "Збережено",
  error: "Операція не вдалася",
  legacy: "Потрібна прошивка з незалежним ID плати та пасивним статусом.",
  profileWarning: "Збереження змінює профіль ESP. Перезапускайте лише коли пристрій повідомляє про необхідність.",
  waiting: "Очікування Wi-Fi або свіжого статусу",
  prepared: "Підготовлено",
  sending: "Передавання",
  verifying: "Образ очікує підтвердження",
  verified: "Перевірено",
  failed: "Помилка",
  uncertain: "Результат невизначений",
  accepted: "Команду прийнято",
  closed_unverified: "Закрито без перевірки",
  already_current: "Обраний образ уже працює; завантаження пропущено",
  identity_mismatch: "За цією адресою інший пристрій.",
  invalid_identity: "Некоректна ідентичність пристрою.",
  unsupported_service: "Оновіть прошивку для підтримки сервісного API.",
  cannot_connect: "HA не може підключитися до HTTP-служби ESP.",
  address_unknown: "Адреса пристрою невідома.",
  already_configured: "Цю плату вже додано.",
  invalid_search_network: "Виберіть налаштовану приватну мережу пошуку.",
  invalid_url: "Введіть приватну IPv4 HTTP-адресу.",
  invalid_topic: "Некоректний префікс MQTT-топіка.",
  operation_unresolved: "Завершіть розбір попередньої операції перед новою командою.",
  operation_busy: "Інша операція ще виконується.",
  ota_busy: "ESP оновлюється або очікує підтвердження.",
  ota_not_prepared: "Один раз налаштуйте віддалене оновлення в режимі Wi-Fi.",
  firmware_url_required: "Задайте LAN-адресу HA у спільних налаштуваннях.",
  z2m_device_missing: "Пристрою немає в каталозі налаштованого Z2M.",
  mqtt_unavailable: "MQTT-служба HA недоступна.",
  outcome_uncertain: "З’єднання обірвалося; не повторюйте оновлення автоматично.",
  publication_failed: "Не вдалося перевірити публікацію прошивки на HA.",
  invalid_firmware: "Некоректний образ, розмір або SHA-256.",
  artifact_mismatch: "Маркер запущеного образу не відповідає цій операції.",
  readback_failed: "Збережене значення не підтверджене читанням.",
  invalid_request: "Некоректний запит.",
  invalid_name: "Введіть назву від 1 до 80 символів.",
  node_limit: "Досягнуто ліміту пристроїв.",
  unknown_node: "Пристрій більше не зареєстровано.",
  storage_failed: "Сховище обслуговування недоступне.",
  invalid_response: "Пристрій повернув некоректну відповідь.",
  device_rejected: "Пристрій відхилив операцію.",
  no_diagnostics: "Діагностичного знімка немає.",
  search_busy: "Триває пошук пристрою.",
  search_address_conflict: "Інший пристрій використовує цю адресу.",
  search_expired: "Результати пошуку застаріли.",
  operation_failed: "Операція не вдалася.",
  response_too_large: "Відповідь пристрою перевищує дозволений розмір."
};
function h(n) {
  const e = n === "uk" || n === "ru" ? f : u;
  return (i) => e[i] ?? e.error;
}
const t = (n) => String(n ?? "").replace(/[&<>"']/g, (e) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[e]), m = "/api/espoid_service";
class v extends HTMLElement {
  root = this.attachShadow({ mode: "open" });
  ha;
  t = h("en");
  timer;
  nodes = [];
  site;
  firmware = [];
  selected = "";
  tab = "devices";
  query = "";
  stateFilter = "";
  status = {};
  profile = "";
  profileResult = "";
  digest = "";
  mode = "z2m";
  busy = !1;
  loading = !1;
  notice = "";
  error = !1;
  searchNetwork = "";
  searchNode = "";
  chosen = /* @__PURE__ */ new Set();
  siteDraft;
  constructor() {
    super(), this.root.addEventListener("click", (e) => {
      this.handleClick(e);
    }), this.root.addEventListener("change", (e) => {
      const i = e.target;
      i.dataset.found && (i.checked ? this.chosen.add(i.dataset.found) : this.chosen.delete(i.dataset.found), this.update());
    });
  }
  set hass(e) {
    this.ha = e, this.t = h(e.language), !this.timer && this.isConnected && this.start();
  }
  connectedCallback() {
    this.render(), this.ha && !this.timer && this.start();
  }
  disconnectedCallback() {
    this.timer && clearInterval(this.timer), this.timer = void 0;
  }
  start() {
    this.reload(!0), this.timer = setInterval(() => {
      !document.hidden && !this.busy && this.reload(!1);
    }, 5e3);
  }
  get node() {
    return this.nodes.find((e) => e.node_id === this.selected);
  }
  button(e, i, s = !1, a = !1) {
    return `<button data-action="${e}" ${s ? "disabled" : ""} class="${a ? "primary" : ""}">${t(this.t(i))}</button>`;
  }
  async request(e, i) {
    if (!this.ha) throw new Error("invalid_request");
    const s = await this.ha.fetchWithAuth(m + e, i);
    if (!s.ok) {
      const a = await s.json().catch(() => ({ error: "operation_failed" }));
      throw new Error(a.error ?? "operation_failed");
    }
    return s;
  }
  async json(e, i) {
    return (await this.request(e, i === void 0 ? void 0 : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(i) })).json();
  }
  path(e) {
    return `/devices/${encodeURIComponent(this.selected)}/${e}`;
  }
  note(e, i = !1) {
    this.notice = this.t(e), this.error = i, this.updateNotice();
  }
  updateNotice() {
    const e = this.root.querySelector("#notice");
    e && (e.textContent = this.notice, e.className = `notice ${this.error ? "error" : ""}`, e.hidden = !this.notice);
  }
  async reload(e = !1) {
    if (!this.loading) {
      this.loading = !0;
      try {
        const [i, s] = await Promise.all([this.json("/devices"), this.json("/site")]);
        if (this.nodes = i.devices, this.site = s, this.nodes.some((a) => a.node_id === this.selected) || (this.selected = this.nodes[0]?.node_id ?? "", this.status = {}, this.mode = this.node?.z2m.ieee && this.node.identity?.transports.zigbee !== !1 ? "z2m" : "url"), e ? (this.firmware = (await this.json("/firmware")).firmware, this.render()) : this.update(), this.selected && (this.tab === "service" && this.node?.connection === "wifi" || this.node?.operation))
          try {
            this.status = await this.json(this.path("status")), this.updateStatus(), this.updateControls();
          } catch {
          }
      } catch (i) {
        this.note(i.message, !0);
      } finally {
        this.loading = !1;
      }
    }
  }
  table() {
    const e = this.query.toLowerCase(), i = this.nodes.filter((s) => (!this.stateFilter || s.connection === this.stateFilter) && `${s.name} ${s.node_id} ${s.base_url}`.toLowerCase().includes(e));
    return `<div class="scroll"><table><thead><tr>${["name", "connection", "version", "address"].map((s) => `<th>${t(this.t(s))}</th>`).join("")}<th></th></tr></thead><tbody>${i.map((s) => `<tr><td>${t(s.name)}<br><code>${t(s.node_id)}</code></td><td><span class="badge">${t(this.t(s.connection))}</span></td><td>${t(s.firmware_version || "—")}</td><td>${t(s.base_url || "—")}</td><td><button data-node="${t(s.node_id)}">${t(this.t("open"))}</button></td></tr>`).join("")}</tbody></table></div>${i.length ? "" : `<p class="muted">${t(this.t("empty"))}</p>`}`;
  }
  history() {
    return this.site?.history.length ? `<div class="scroll"><table><thead><tr>${["name", "state", "version", "message"].map((e) => `<th>${t(this.t(e))}</th>`).join("")}</tr></thead><tbody>${[...this.site.history].reverse().map((e) => `<tr><td>${t(this.nodes.find((i) => i.node_id === e.node_id)?.name ?? e.node_id)}<br><small>${t(new Date(e.created_at).toLocaleString())}</small></td><td>${t(this.t(e.state))}<br><code>${t(this.t(e.action))}</code></td><td>${t(e.artifact?.version ?? "—")}<br><code>${t(e.artifact?.sha256 ?? "")}</code></td><td>${t(e.message ? this.t(e.message) : "")}</td></tr>`).join("")}</tbody></table></div>` : `<p>${t(this.t("noHistory"))}</p>`;
  }
  search() {
    const e = this.site?.search.job;
    return `<div class="toolbar"><select id="search-node" aria-label="${t(this.t("choose"))}"><option value="">${t(this.t("all"))}</option>${this.nodes.map((i) => `<option value="${t(i.node_id)}" ${i.node_id === this.searchNode ? "selected" : ""}>${t(i.name)}</option>`).join("")}</select><select id="network" aria-label="${t(this.t("networks"))}">${(this.site?.settings.search_networks ?? []).map((i) => `<option ${i === this.searchNetwork ? "selected" : ""}>${t(i)}</option>`).join("")}</select>${this.button("search", "search", this.busy || !this.site?.settings.search_networks.length || e?.state === "running")}${this.button("stop", "stop", e?.state !== "running")}</div><div id="search-results">${this.searchResults()}</div>`;
  }
  searchResults() {
    const e = this.site?.search.job;
    return e ? `<p>${e.checked}/${e.total} · ${t(this.t("search_" + e.state))}</p><div class="scroll"><table><tbody>${e.candidates.map((i) => `<tr><td><input type="checkbox" data-found="${t(i.node_id)}" ${this.chosen.has(i.node_id) ? "checked" : ""} aria-label="${t(i.node_id)}"></td><td><code>${t(i.node_id)}</code></td><td>${t(i.url)}</td></tr>`).join("")}</tbody></table></div>${this.button("connectSelected", "connectSelected", this.busy || !this.chosen.size)}` : "";
  }
  deviceView() {
    return `<div class="toolbar"><input id="query" type="search" value="${t(this.query)}" placeholder="${t(this.t("filter"))}" aria-label="${t(this.t("filter"))}"><select id="state-filter" aria-label="${t(this.t("connection"))}"><option value="">${t(this.t("all"))}</option>${["wifi", "service_closed", "unknown"].map((e) => `<option value="${e}" ${this.stateFilter === e ? "selected" : ""}>${t(this.t(e))}</option>`).join("")}</select>${this.button("add", "add", this.busy, !0)}</div><div id="table" class="card">${this.table()}</div><div class="card"><h2>${t(this.t("found"))}</h2>${this.search()}<h3>${t(this.t("candidates"))}</h3><div id="catalog">${this.catalog()}</div></div>`;
  }
  catalog() {
    return (this.site?.candidates ?? []).map((e) => `<p>${t(e.name)} · <code>${t(e.ieee)}</code> <button data-wake="${t(JSON.stringify([e.prefix, e.ieee]))}" ${this.busy ? "disabled" : ""}>${t(this.t("wake"))}</button>${e.admin_url ? ` <button data-connect="${t(JSON.stringify([e.prefix, e.ieee]))}" ${this.busy ? "disabled" : ""}>${t(this.t("connect"))}</button>` : ""}</p>`).join("") + (this.site?.announcements ?? []).filter((e) => !this.nodes.some((i) => i.node_id === e.node_id)).map((e) => `<p><code>${t(e.node_id)}</code> <button data-announcement="${t(e.node_id)}" ${this.busy ? "disabled" : ""}>${t(this.t("connect"))}</button></p>`).join("");
  }
  nodeSelect() {
    return `<label>${t(this.t("choose"))}<select id="node">${this.nodes.map((e) => `<option value="${t(e.node_id)}" ${e.node_id === this.selected ? "selected" : ""}>${t(e.name)} · ${t(e.node_id)}</option>`).join("")}</select></label>`;
  }
  serviceView() {
    const e = this.node;
    return `${this.nodeSelect()}${e ? `<div class="card"><h2>${t(e.name)}</h2><code>${t(e.node_id)}</code><p>${t(e.base_url)}</p><div class="toolbar">${this.button("status", "status", this.busy)}${e.z2m.ieee && e.identity?.transports.zigbee !== !1 ? this.button("wifi", "wake", this.busy) : ""}${this.button("hold", "hold", this.busy)}${e.identity?.transports.zigbee ? this.button("reboot_zigbee", "zigbee", this.busy) : ""}${this.button("reboot_wifi", "reboot", this.busy)}</div><div id="status-facts"></div><div class="toolbar">${this.button("snapshot", "snapshot")}${e.identity?.diagnostics ? this.button("diagnostics", "trace", this.busy) : ""}${this.button("rename", "rename", this.busy)}${this.button("address", "address", this.busy)}${this.button("remove", "remove", this.busy)}</div></div><div class="card"><h2>${t(this.t("prepare"))}</h2><p class="muted">${t(this.t("prepareHelp"))}</p>${this.button("prepare", "prepare", this.busy)}</div><div class="card"><h2>${t(this.t("profile"))}</h2><p class="muted">${t(this.t("profileWarning"))}</p><textarea id="profile" aria-label="${t(this.t("profile"))}" spellcheck="false">${t(this.profile)}</textarea><div class="toolbar">${this.button("profile_read", "read", this.busy)}${this.button("profile_validate", "validate", this.busy)}${this.button("profile_store", "store", this.busy)}</div><pre id="profile-result"></pre></div>` : `<p>${t(this.t("empty"))}</p>`}`;
  }
  firmwareView() {
    return `${this.nodeSelect()}<div class="card"><h2>${t(this.t("install"))}</h2><label>${t(this.t("selectFirmware"))}<select id="firmware"><option value="">—</option>${this.firmware.map((e) => `<option value="${e.id}" ${e.id === this.digest ? "selected" : ""}>${t(e.version)} · ${e.id.slice(0, 12)}</option>`).join("")}</select></label><div id="firmware-facts"></div><label>${t(this.t("mode"))}<select id="mode">${["z2m", "url", "upload"].map((e) => `<option value="${e}" ${e === this.mode ? "selected" : ""} ${e === "z2m" && (!this.node?.z2m.ieee || this.node?.identity?.transports.zigbee === !1) ? "disabled" : ""}>${t(this.t(e))}</option>`).join("")}</select></label>${this.button("install", "install", this.busy || !this.digest || !this.selected, !0)}<div id="operation"></div><div class="toolbar">${this.button("status", "refresh", this.busy)}${this.button("confirm", "confirm", this.busy || !this.status.wifi_ota?.verification_pending)}${this.button("resolve", "closeOperation", this.busy || !this.node?.operation)}</div></div><div class="card"><h2>${t(this.t("import"))}</h2><div class="grid"><label>${t(this.t("manifest"))}<input id="manifest" type="file" accept=".json"></label><label>${t(this.t("image"))}<input id="image" type="file" accept=".bin"></label></div>${this.button("import", "import", this.busy)}</div>`;
  }
  settingsView() {
    const e = this.siteDraft ?? this.site?.settings;
    return `<div class="card"><h2>${t(this.t("settings"))}</h2>${[["base", "firmware_base_url", "baseHelp"], ["networks", "search_networks", "networksHelp"], ["prefixes", "z2m_prefixes", "prefixesHelp"], ["announcement", "announcement_prefix", ""]].map(([i, s, a]) => `<label>${t(this.t(i))}<input data-setting="${s}" value="${t(Array.isArray(e?.[s]) ? (e?.[s]).join(", ") : e?.[s] ?? "")}"></label>${a ? `<p class="muted">${t(this.t(a))}</p>` : ""}`).join("")}${this.button("saveSettings", "save", this.busy, !0)}</div>`;
  }
  render() {
    this.root.innerHTML = `<style>${p}</style><main><header><div><h1>ESPOID Service</h1><p class="muted">${this.nodes.length} · ${t(this.t("devices"))}</p></div>${this.button("reload", "refresh", this.busy)}</header><nav>${["devices", "service", "firmware", "history", "settings"].map((l) => `<button data-tab="${l}" aria-selected="${l === this.tab}">${t(this.t(l))}</button>`).join("")}</nav><p id="notice" role="status"></p><section>${this.tab === "devices" ? this.deviceView() : this.tab === "service" ? this.serviceView() : this.tab === "firmware" ? this.firmwareView() : this.tab === "history" ? `<div class="card" id="history">${this.history()}</div>` : this.settingsView()}</section></main>`;
    const e = this.root.querySelector("#query");
    e && (e.oninput = () => {
      this.query = e.value, this.update();
    });
    const i = this.root.querySelector("#state-filter");
    i && (i.onchange = () => {
      this.stateFilter = i.value, this.update();
    });
    const s = this.root.querySelector("#node");
    s && (s.onchange = () => {
      this.selected = s.value, this.status = {}, this.profile = "", this.mode = this.node?.z2m.ieee && this.node.identity?.transports.zigbee !== !1 ? "z2m" : "url", this.render();
    });
    const a = this.root.querySelector("#profile");
    a && (a.oninput = () => this.profile = a.value);
    const r = this.root.querySelector("#network");
    r && (r.onchange = () => this.searchNetwork = r.value);
    const o = this.root.querySelector("#search-node");
    o && (o.onchange = () => this.searchNode = o.value);
    const d = this.root.querySelector("#firmware");
    d && (d.onchange = () => {
      this.digest = d.value, this.render();
    });
    const c = this.root.querySelector("#mode");
    c && (c.onchange = () => this.mode = c.value), this.updateNotice(), this.updateStatus(), this.updateFirmware(), this.updateControls();
  }
  update() {
    const e = this.root.querySelector("#table");
    e && (e.innerHTML = this.table());
    const i = this.root.querySelector("#search-results");
    i && (i.innerHTML = this.searchResults());
    const s = this.root.querySelector("#catalog");
    s && (s.innerHTML = this.catalog());
    const a = this.root.querySelector("#history");
    a && (a.innerHTML = this.history()), this.updateStatus(), this.updateControls();
  }
  updateStatus() {
    const e = this.root.querySelector("#status-facts");
    e && (e.innerHTML = `<dl><dt>${t(this.t("running"))}</dt><dd>${t(this.status.running_version ?? "—")}</dd><dt>${t(this.t("marker"))}</dt><dd><code>${t(this.status.ota_marker_sha256 || "—")}</code></dd><dt>${t(this.t("pending"))}</dt><dd>${t(this.t(typeof this.status.wifi_ota?.verification_pending == "boolean" ? this.status.wifi_ota.verification_pending ? "yes" : "no" : "unknown_value"))}</dd></dl><details><summary>${t(this.t("snapshot"))}</summary><pre>${t(JSON.stringify(this.status, null, 2))}</pre></details>`);
    const i = this.root.querySelector("#operation");
    if (i) {
      const s = this.node?.operation;
      i.innerHTML = s ? `<h3>${t(this.t(s.state))}</h3><p>${t(s.message ? this.t(s.message) : "")}</p>${s.total_bytes ? `<progress max="${s.total_bytes}" value="${s.sent_bytes ?? 0}"></progress>` : ""}<code>${t(s.artifact?.sha256 ?? "")}</code>` : "";
    }
  }
  updateControls() {
    this.root.querySelectorAll("button[data-action]").forEach((e) => {
      const i = e.dataset.action;
      e.disabled = this.busy, i === "confirm" && (e.disabled = this.busy || !this.status.wifi_ota?.verification_pending || this.node?.operation?.state !== "verifying"), i === "resolve" && (e.disabled = this.busy || !this.node?.operation), i === "install" && (e.disabled = this.busy || !this.digest || !this.selected || !!this.node?.operation), i === "search" && (e.disabled = this.busy || !this.site?.settings.search_networks.length || this.site?.search.job?.state === "running"), i === "stop" && (e.disabled = this.busy || this.site?.search.job?.state !== "running"), i === "connectSelected" && (e.disabled = this.busy || !this.chosen.size);
    });
  }
  updateFirmware() {
    const e = this.root.querySelector("#firmware-facts"), i = this.firmware.find((s) => s.id === this.digest);
    e && (e.innerHTML = i ? `<dl><dt>${t(this.t("size"))}</dt><dd>${i.artifact.size.toLocaleString()} B</dd><dt>SHA-256</dt><dd><code>${i.id}</code></dd></dl>` : "");
  }
  download(e, i) {
    const s = URL.createObjectURL(e), a = document.createElement("a");
    a.href = s, a.download = i, a.click(), setTimeout(() => URL.revokeObjectURL(s), 1e3);
  }
  async handleClick(e) {
    const i = e.target.closest("button");
    if (!i || i.disabled) return;
    if (i.dataset.tab) {
      this.tab = i.dataset.tab, this.render();
      return;
    }
    if (i.dataset.node) {
      this.selected = i.dataset.node, this.status = {}, this.profile = "", this.tab = "service", this.mode = this.node?.z2m.ieee && this.node.identity?.transports.zigbee !== !1 ? "z2m" : "url", this.render();
      return;
    }
    if (this.busy) return;
    const s = i.dataset.action;
    this.busy = !0;
    try {
      if (i.dataset.wake) {
        const a = this.site.candidates.find((r) => JSON.stringify([r.prefix, r.ieee]) === i.dataset.wake);
        if (!a) throw new Error("invalid_request");
        await this.json("/catalog/wifi", { prefix: a.prefix, ieee: a.ieee }), this.note("accept");
      } else if (i.dataset.connect) {
        const a = this.site.candidates.find((o) => JSON.stringify([o.prefix, o.ieee]) === i.dataset.connect);
        if (!a) throw new Error("invalid_request");
        const r = this.nodes.find((o) => o.z2m.prefix === a.prefix && o.z2m.ieee === a.ieee);
        await this.json(r ? `/devices/${encodeURIComponent(r.node_id)}/address` : "/devices", r ? { url: a.admin_url } : { url: a.admin_url, name: a.name, z2m: { prefix: a.prefix, ieee: a.ieee } }), this.note("ready");
      } else if (i.dataset.announcement) {
        const a = this.site.announcements.find((r) => r.node_id === i.dataset.announcement);
        if (!a) throw new Error("invalid_request");
        await this.json("/devices", { url: a.admin_url, name: a.node_id }), this.note("ready");
      } else if (s === "reload") await this.reload(!0);
      else if (s === "add") {
        const a = window.prompt(this.t("address"));
        if (a) {
          const r = window.prompt(this.t("name"), "ESPOID");
          r && await this.json("/devices", { url: a, name: r });
        }
      } else if (s === "status")
        this.status = await this.json(this.path("status")), this.updateStatus();
      else if (s === "snapshot") this.download(new Blob([JSON.stringify(this.status, null, 2)], { type: "application/json" }), `espoid-${this.selected}-status.json`);
      else if (s === "diagnostics") this.download(await (await this.request(this.path("diagnostics"))).blob(), `espoid-${this.selected}.ndjson`);
      else if (s === "profile_read")
        this.profile = JSON.stringify((await this.json(this.path("profile"))).config, null, 2), this.render();
      else if (s === "profile_validate" || s === "profile_store") {
        const a = await this.json(this.path(s), { profile: JSON.parse(this.profile) });
        this.profileResult = JSON.stringify(a, null, 2), this.note("ready");
      } else if (s === "rename" || s === "address") {
        const a = window.prompt(this.t(s), s === "rename" ? this.node?.name : this.node?.base_url);
        a && await this.json(this.path(s), s === "rename" ? { name: a } : { url: a });
      } else if (s === "remove")
        window.confirm(this.t("confirmRemove")) && await this.json(this.path("remove"), { confirmed: !0 });
      else if (s === "resolve")
        window.confirm(this.t("confirmClose")) && await this.json(this.path("resolve"), { operation_id: this.node?.operation?.id, confirmed: !0 });
      else if (s === "install")
        window.confirm(`${this.t("confirmInstall")}
${this.node?.name}
SHA-256: ${this.digest}`) && (await this.json(this.path("ota"), { mode: this.mode, firmware_id: this.digest }), this.note("accept"));
      else if (s === "saveSettings") {
        const a = {};
        this.root.querySelectorAll("[data-setting]").forEach((r) => a[r.dataset.setting] = r.value), await this.json("/site", a), this.siteDraft = void 0, this.note("ready");
      } else if (s === "search") {
        const a = this.root.querySelector("#network").value;
        this.searchNetwork = a, this.chosen.clear(), await this.json("/search/start", { cidr: a, ...this.searchNode ? { node_id: this.searchNode } : {} });
      } else if (s === "stop") await this.json("/search/cancel", { job_id: this.site?.search.job?.id });
      else if (s === "connectSelected") {
        for (const a of this.site?.search.job?.candidates ?? [])
          if (this.chosen.has(a.node_id))
            if (this.nodes.some((r) => r.node_id === a.node_id))
              await this.json(`/devices/${encodeURIComponent(a.node_id)}/address`, { url: a.url });
            else {
              const r = this.site.candidates.filter((o) => o.ieee === a.zigbee_ieee);
              await this.json("/devices", { url: a.url, name: r[0]?.name ?? a.node_id, ...r.length === 1 ? { z2m: { prefix: r[0].prefix, ieee: r[0].ieee } } : {} });
            }
        this.chosen.clear(), this.note("ready");
      } else if (s === "import") {
        const a = this.root.querySelector("#manifest")?.files?.[0], r = this.root.querySelector("#image")?.files?.[0];
        if (!a || !r) throw new Error("invalid_firmware");
        const o = new FormData();
        o.append("manifest", a), o.append("image", r);
        const d = await (await this.request("/firmware", { method: "POST", body: o })).json();
        this.firmware = (await this.json("/firmware")).firmware, this.digest = d.firmware.id, this.note("ready"), this.render();
      } else s && (await this.json(this.path(s), {}), this.note(s === "wifi" ? "accept" : "ready"));
      await this.reload(!1);
    } catch (a) {
      this.note(a instanceof SyntaxError ? "invalid_request" : a.message, !0);
    } finally {
      this.busy = !1, this.render();
      const a = this.root.querySelector("#profile-result");
      a && (a.textContent = this.profileResult);
    }
  }
}
customElements.get("espoid-service-panel") || customElements.define("espoid-service-panel", v);
