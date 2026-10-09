import { en, translate } from "./translations.js";
import { styles } from "./styles.js";
class ServiceError extends Error {
    code;
    espError;
    constructor(code, espError) {
        super(code);
        this.code = code;
        this.espError = espError;
    }
}
class ServicePanel extends HTMLElement {
    homeAssistant;
    language = "en";
    devices = [];
    selected = "";
    tab = "status";
    firmware = [];
    firmwareId = "";
    profileDraft = "";
    busy = false;
    refreshing = false;
    timer;
    message;
    manifestFile;
    imageFile;
    root = this.attachShadow({ mode: "open" });
    constructor() {
        super();
        this.root.addEventListener("click", event => {
            const element = event.target.closest("button");
            if (!element || element.disabled)
                return;
            if (element.dataset.tab) {
                void this.changeTab(element.dataset.tab);
                return;
            }
            if (element.dataset.action)
                void this.action(element.dataset.action);
        });
    }
    set hass(value) {
        this.homeAssistant = value;
        const language = value.locale?.language ?? value.language ?? "en";
        const changed = this.language !== language;
        this.language = language;
        if (!this.root.querySelector("main") || changed)
            this.render();
        if (!this.timer && this.isConnected)
            this.start();
    }
    connectedCallback() { this.render(); if (this.homeAssistant)
        this.start(); }
    disconnectedCallback() { clearInterval(this.timer); this.timer = undefined; }
    t(key, values) { return translate(this.language, key, values); }
    get device() { return this.devices.find(device => device.id === this.selected); }
    path(action) { return `/api/espoid_service/devices/${encodeURIComponent(this.selected)}/${action}`; }
    async start() {
        this.timer = setInterval(() => {
            if (!document.hidden && !this.busy)
                void this.refresh(false);
        }, 5000);
        await this.loadDevices();
        await this.refresh(false);
    }
    async request(path, options) {
        const response = await this.homeAssistant.fetchWithAuth(path, options);
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new ServiceError(Object.hasOwn(en, result.error) ? result.error : "request_failed", result.esp_error);
        }
        return response;
    }
    async json(path, body) {
        const options = body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
        return (await this.request(path, options)).json();
    }
    async loadDevices() {
        try {
            this.devices = (await this.json("/api/espoid_service/devices")).devices;
            if (!this.devices.some(device => device.id === this.selected))
                this.selected = this.devices[0]?.id ?? "";
            this.renderDeviceOptions();
            this.updateStatus();
        }
        catch (error) {
            this.showError(error);
        }
    }
    async refresh(report = true) {
        if (!this.selected || this.refreshing || !this.homeAssistant)
            return;
        this.refreshing = true;
        const id = this.selected;
        const device = this.device;
        try {
            device.status = await this.json(this.path("status"));
            device.reachable = true;
            device.checked_at = new Date().toISOString();
            if (report)
                this.message = undefined;
        }
        catch (error) {
            device.reachable = false;
            device.checked_at = new Date().toISOString();
            if (report)
                this.showError(error);
        }
        finally {
            this.refreshing = false;
            if (id === this.selected)
                this.updateStatus();
        }
    }
    showError(error) {
        const failure = error instanceof ServiceError ? error : new ServiceError("request_failed");
        this.message = { error: true, text: this.t(failure.code) + (failure.espError ? ` (${failure.espError})` : "") };
        this.updateMessage();
    }
    note(key) { this.message = { error: false, text: this.t(key) }; this.updateMessage(); }
    updateMessage() {
        const notice = this.root.querySelector("#notice");
        notice.textContent = this.message?.text ?? "";
        notice.hidden = !this.message;
        notice.className = this.message?.error ? "notice error" : "notice";
    }
    button(action, key, icon, extra = "") {
        return `<button type="button" data-action="${action}" ${extra}><ha-icon icon="mdi:${icon}"></ha-icon><span>${this.t(key)}</span></button>`;
    }
    iconButton(action, key, icon) {
        return `<button type="button" class="icon" data-action="${action}" title="${this.t(key)}" aria-label="${this.t(key)}"><ha-icon icon="mdi:${icon}"></ha-icon></button>`;
    }
    render() {
        this.root.innerHTML = `<style>${styles}</style>
      <header>${this.iconButton("menu", "menu", "menu")}<h1>ESPOID Service</h1><div class="header-actions">
      ${this.iconButton("add", "add", "plus")}${this.iconButton("settings", "settings", "cog-outline")}</div></header>
      <main><div class="device-bar"><label for="device">${this.t("device")}</label><select id="device"></select>
      ${this.iconButton("refresh", "refresh", "refresh")}<span id="connection" class="connection"></span></div>
      <p id="address" class="address"></p><nav aria-label="ESPOID">${["status", "profile", "diagnostics", "firmware"].map(key => `<button type="button" data-tab="${key}" aria-selected="${this.tab === key}">${this.t(key)}</button>`).join("")}</nav>
      <div id="notice" role="status" class="notice" hidden></div>
      <section id="status" ${this.tab === "status" ? "" : "hidden"}>
        <div class="commands">
        ${this.button("mqtt_wifi", "wifi", "wifi")}${this.button("hold", "hold", "timer-plus-outline")}
        ${this.button("reboot_zigbee", "zigbee", "access-point")}${this.button("reboot_wifi", "reboot", "restart")}
        ${this.button("recovery_retry", "retry", "restore")}</div><dl id="facts"></dl></section>
      <section id="profile" ${this.tab === "profile" ? "" : "hidden"}>
        <div class="toolbar">${this.button("read", "read", "download")}${this.button("validate", "validate", "check")}
        ${this.button("apply", "apply", "content-save-outline", 'class="primary"')}<span id="profile-source"></span></div>
        <label for="profile-json">${this.t("json")}</label><textarea id="profile-json" spellcheck="false"></textarea>
        <dl id="impact"></dl></section>
      <section id="diagnostics" ${this.tab === "diagnostics" ? "" : "hidden"}>
        <div class="toolbar">${this.button("download", "download", "download")}${this.button("snapshot", "snapshot", "file-download-outline")}</div>
        <pre id="snapshot"></pre></section>
      <section id="firmware" ${this.tab === "firmware" ? "" : "hidden"}>
        <div class="upload-grid"><label>${this.t("manifest")}<input id="manifest-file" type="file" accept=".json"></label>
        <label>${this.t("image")}<input id="image-file" type="file" accept=".bin"></label></div>
        <div class="toolbar">${this.button("import", "import", "upload")}</div>
        <label for="firmware-select">${this.t("select")}</label><select id="firmware-select"></select>
        <dl id="firmware-facts"></dl><div class="toolbar">${this.button("install", "install", "update", 'class="primary"')}</div>
        <dl id="ota-facts"></dl></section></main>`;
        this.root.querySelector("#device").onchange = async (event) => {
            this.selected = event.target.value;
            this.profileDraft = "";
            this.message = undefined;
            this.render();
            await this.refresh(false);
        };
        this.root.querySelector("#profile-json").oninput = event => {
            this.profileDraft = event.target.value;
        };
        this.root.querySelector("#profile-json").value = this.profileDraft;
        this.root.querySelector("#manifest-file").onchange = event => {
            this.manifestFile = event.target.files?.[0];
        };
        this.root.querySelector("#image-file").onchange = event => {
            this.imageFile = event.target.files?.[0];
        };
        this.root.querySelector("#firmware-select").onchange = event => {
            this.firmwareId = event.target.value;
            this.updateFirmware();
        };
        this.renderDeviceOptions();
        this.updateStatus();
        this.renderFirmwareOptions();
        this.updateMessage();
    }
    renderDeviceOptions() {
        const select = this.root.querySelector("#device");
        select.replaceChildren();
        if (!this.devices.length)
            select.add(new Option(this.t("noDevices"), ""));
        for (const device of this.devices)
            select.add(new Option(device.name, device.id));
        select.value = this.selected;
        this.root.querySelector("#address").textContent = this.device?.base_url ?? "";
    }
    facts(id, facts) {
        const element = this.root.querySelector(`#${id}`);
        element.replaceChildren();
        for (const [key, value] of facts) {
            const dt = document.createElement("dt");
            dt.textContent = this.t(key);
            const dd = document.createElement("dd");
            dd.textContent = value === null || value === undefined ? this.t("unknown")
                : typeof value === "boolean" ? this.t(value ? "yes" : "no") : String(value);
            element.append(dt, dd);
        }
    }
    updateStatus() {
        const device = this.device;
        const status = device?.status ?? {};
        const haier = (status.haier ?? {});
        const ota = (status.wifi_ota ?? {});
        const connection = this.root.querySelector("#connection");
        connection.textContent = this.t(!device?.checked_at ? "unchecked" : device.reachable ? "reachable" : "unavailable");
        connection.className = `connection ${device?.reachable ? "online" : "offline"}`;
        const temperature = (value) => haier.climate_valid && value != null ? `${value} °C` : null;
        this.facts("facts", [["running", status.running_version], ["lease", status.wifi_admin_remaining_ms != null ? `${Math.ceil(Number(status.wifi_admin_remaining_ms) / 60000)} min` : null],
            ["checkTime", device?.checked_at ? new Date(device.checked_at).toLocaleTimeString(this.language) : null],
            ["protocol", haier.protocol], ["current", temperature(haier.current_temperature)], ["target", temperature(haier.target_temperature)],
            ["tx", haier.tx_bytes], ["rx", haier.rx_bytes], ["frames", haier.status_frames], ["timeouts", haier.timeouts],
            ["age", haier.last_valid_status_age_ms != null ? `${Math.round(Number(haier.last_valid_status_age_ms) / 1000)} s` : null],
            ["pending", haier.control_pending], ["recovery", status.recovery?.active]]);
        const otaStates = { idle: "idle", checking: "checking", downloading: "downloading",
            installing: "installing", rebooting: "rebooting", skipped: "skipped", done: "done", failed: "failed" };
        this.facts("ota-facts", [["otaState", ota.state ? this.t(otaStates[String(ota.state)] ?? "unknown") : null],
            ["progress", ota.total_bytes ? `${Math.floor(Number(ota.downloaded_bytes) * 100 / Number(ota.total_bytes))}%` : null],
            ["version", ota.artifact_version || null], ["verification", ota.verification_pending], ["otaMessage", ota.message || null]]);
        this.root.querySelector("#snapshot").textContent = device?.status ? JSON.stringify(device.status, null, 2) : "";
        this.root.querySelector('[data-action="recovery_retry"]').hidden = !status.recovery?.active;
        this.updateDisabled();
        this.updateMessage();
    }
    updateDisabled() {
        for (const button of this.root.querySelectorAll("button[data-action]")) {
            const action = button.dataset.action;
            const needsDevice = !["menu", "add", "settings", "import"].includes(action);
            button.disabled = this.busy || (needsDevice && !this.device)
                || (action === "mqtt_wifi" && !this.device?.mqtt_configured)
                || (action === "install" && !this.firmwareId);
        }
        this.root.querySelector("#device").disabled = this.busy;
        this.root.querySelector("#firmware-select").disabled = this.busy;
    }
    async changeTab(tab) {
        this.tab = tab;
        for (const section of this.root.querySelectorAll("section"))
            section.hidden = section.id !== tab;
        for (const button of this.root.querySelectorAll("button[data-tab]"))
            button.setAttribute("aria-selected", String(button.dataset.tab === tab));
        if (tab === "firmware") {
            try {
                this.firmware = (await this.json("/api/espoid_service/firmware")).firmware;
                this.renderFirmwareOptions();
            }
            catch (error) {
                this.showError(error);
            }
        }
    }
    renderFirmwareOptions() {
        const select = this.root.querySelector("#firmware-select");
        select.replaceChildren(new Option(this.t(this.firmware.length ? "select" : "emptyFirmware"), ""));
        for (const firmware of this.firmware)
            select.add(new Option(`${firmware.version} · ${firmware.id.slice(0, 12)}`, firmware.id));
        select.value = this.firmwareId;
        this.updateFirmware();
    }
    updateFirmware() {
        const firmware = this.firmware.find(item => item.id === this.firmwareId);
        this.facts("firmware-facts", firmware ? [["version", firmware.version], ["size", `${firmware.artifact.size.toLocaleString(this.language)} B`], ["hash", firmware.id]] : []);
        this.updateDisabled();
    }
    parseProfile() {
        try {
            const profile = JSON.parse(this.profileDraft);
            if (!profile || typeof profile !== "object" || Array.isArray(profile))
                throw new Error();
            return profile;
        }
        catch {
            throw new ServiceError("invalid_profile");
        }
    }
    showImpact(result) {
        const key = String(result.zigbeeAction);
        this.facts("impact", [["rebootRequired", result.requiresReboot], ["zigbeeAction", this.t(key === "reinterview" ? "reinterview" : key === "reconfigure" ? "reconfigure" : "none")]]);
    }
    download(data, filename) {
        const url = URL.createObjectURL(data);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    async action(action) {
        if (this.busy)
            return;
        if (action === "menu") {
            this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
            return;
        }
        if (action === "add" || action === "settings") {
            const url = action === "add" ? "/config/integrations/dashboard?add_integration=espoid_service" : "/config/integrations/integration/espoid_service";
            history.pushState(null, "", url);
            window.dispatchEvent(new CustomEvent("location-changed"));
            return;
        }
        if (action === "refresh") {
            await this.loadDevices();
            await this.refresh();
            return;
        }
        this.busy = true;
        this.updateDisabled();
        try {
            if (action === "read") {
                const result = await this.json(this.path("profile"));
                this.profileDraft = result.config == null ? "" : JSON.stringify(result.config, null, 2);
                this.root.querySelector("#profile-json").value = this.profileDraft;
                this.root.querySelector("#profile-source").textContent = this.t("source") + ": " + this.t(result.source === "stored" ? "stored" : "default");
                this.showImpact(result);
                this.message = undefined;
            }
            else if (action === "validate" || action === "apply") {
                const profile = this.parseProfile();
                if (action === "apply" && !confirm(this.t("confirmSave", { name: this.device.name })))
                    return;
                const result = await this.json(this.path(action === "apply" ? "profile_store" : "profile_validate"), { profile });
                this.showImpact(result);
                this.note(action === "apply" ? "saved" : "valid");
            }
            else if (action === "download") {
                this.download(await (await this.request(this.path("diagnostics"))).blob(), `espoid-${this.selected}-uart.ndjson`);
            }
            else if (action === "snapshot") {
                this.download(new Blob([JSON.stringify(this.device.status, null, 2)], { type: "application/json" }), `espoid-${this.selected}-status.json`);
            }
            else if (action === "import") {
                if (!this.manifestFile || !this.imageFile)
                    throw new ServiceError("pickFiles");
                const form = new FormData();
                form.append("manifest", this.manifestFile);
                form.append("image", this.imageFile);
                await this.request("/api/espoid_service/firmware", { method: "POST", body: form });
                this.note("imported");
                await this.changeTab("firmware");
            }
            else if (action === "install") {
                const firmware = this.firmware.find(item => item.id === this.firmwareId);
                if (!confirm(this.t("confirmInstall", { name: this.device.name, version: firmware.version, hash: firmware.id })))
                    return;
                await this.json(this.path("ota_install"), { firmware_id: firmware.id });
                this.note("queued");
                await this.refresh(false);
            }
            else {
                if (["reboot_wifi", "reboot_zigbee", "recovery_retry"].includes(action) && !confirm(this.t("confirmReboot", { name: this.device.name })))
                    return;
                const result = await this.json(this.path(action), {});
                this.note("queued");
                if (action === "hold") {
                    this.device.status = result;
                    this.device.reachable = true;
                }
                if (action.startsWith("reboot") || action === "recovery_retry")
                    this.device.reachable = false;
            }
        }
        catch (error) {
            this.showError(error);
        }
        finally {
            this.busy = false;
            this.updateStatus();
        }
    }
}
if (!customElements.get("espoid-service-panel"))
    customElements.define("espoid-service-panel", ServicePanel);
