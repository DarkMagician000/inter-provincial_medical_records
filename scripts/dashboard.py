"""Read-only, direct-site dashboard; run --selftest without PostgreSQL."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import threading
import time
import tomllib
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit


TABLES = (
    "hospital", "drug", "patient", "visit", "prescription", "visit_cardio",
    "visit_eye", "visit_eye_diagnosis", "visit_blood", "visit_blood_test",
)
NEW_ROWS = {
    "patient": "patient_id > 20000",
    "visit": "visit_id > 80000",
    "prescription": "prescription_id > 200000",
    **{table: "visit_id > 80000" for table in TABLES[5:]},
}
LABELS = {
    "tayninh": "Tây Ninh", "hcm": "TP. Hồ Chí Minh", "cantho": "Cần Thơ",
    "dongnai": "Đồng Nai", "ref": "Đối chứng",
}
POLL_INTERVAL = 1.0
STALE_AFTER = 2.0
COUNT_SQL = "\nUNION ALL\n".join(
    f"SELECT '{table}', count(*), "
    + (f"count(*) FILTER (WHERE {NEW_ROWS[table]})" if table in NEW_ROWS else "0::bigint")
    + f" FROM public.{table}"
    for table in TABLES
)


def timestamp() -> str:
    """Return an ISO timestamp with an explicit UTC offset."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_config(filename: Path) -> dict:
    """Validate deploy.toml and return database and direct-site settings."""
    with filename.open("rb") as source:
        config = tomllib.load(source)
    if not isinstance(config.get("dbname"), str) or not config["dbname"].strip():
        raise ValueError("deploy.toml: dbname phải là chuỗi không rỗng")
    if not isinstance(config.get("machines"), dict):
        raise ValueError("deploy.toml: thiếu bảng machines")
    sites = config.get("sites")
    if not isinstance(sites, dict) or set(sites) != set(LABELS) - {"ref"}:
        raise ValueError("deploy.toml: cần đủ bốn trạm tayninh, hcm, cantho, dongnai")
    result = {}
    for name, label in LABELS.items():
        site = config.get("ref") if name == "ref" else sites[name]
        if not isinstance(site, dict):
            raise ValueError(f"deploy.toml: thiếu cấu hình {name}")
        machine, address, port = site.get("machine"), site.get("ip"), site.get("port")
        if not isinstance(machine, str) or machine not in config["machines"]:
            raise ValueError(f"deploy.toml: máy không hợp lệ tại {name}")
        if not isinstance(address, str):
            raise ValueError(f"deploy.toml: IP không hợp lệ tại {name}")
        ipaddress.ip_address(address)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f"deploy.toml: cổng không hợp lệ tại {name}")
        result[name] = {
            "name": name, "label": label, "machine": machine,
            "hostname": config["machines"][machine], "ip": address, "port": port,
            "central": site.get("central", False), "reference": name == "ref",
        }
    return {"dbname": config["dbname"], "sites": result}


def event_diff(previous: dict, current: dict, at: str) -> list[dict]:
    """Compare snapshots; retain outage baselines and suppress initial row events."""
    events = []
    if previous["status"] != current["status"]:
        if current["status"] == "down":
            events.append({"kind": "down", "level": "bad", "text": "Mất kết nối"})
        elif current["status"] == "up":
            reconnect = previous["status"] == "down"
            events.append({
                "kind": "reconnected" if reconnect else "connected", "level": "good",
                "text": "Đã kết nối lại" if reconnect else "Đã kết nối",
            })
    if current["status"] == "up":
        for table, count in current["counts"].items():
            if table not in previous["counts"]:
                continue
            delta = count - previous["counts"][table]
            if delta:
                events.append({
                    "kind": "rows_added" if delta > 0 else "rows_removed",
                    "level": "good" if delta > 0 else "warn", "table": table,
                    "delta": delta, "text": f"{table}: {delta:+d} dòng",
                })
    return [{"at": at, "site": current["name"], **event} for event in events]


def summarize(sites: dict) -> dict:
    """Compare available direct counts; missing sites never contribute zero."""
    fragments = [site for name, site in sites.items() if name != "ref"]
    reference = sites["ref"]
    complete = all(site["status"] == "up" for site in fragments)
    fragmented = []
    replicated = []
    for table in TABLES:
        ref_count = reference["counts"].get(table) if reference["status"] == "up" else None
        if table in NEW_ROWS:
            total = sum(site["counts"][table] for site in fragments) if complete else None
            new = sum(site["new"][table] for site in fragments) if complete else None
            difference = total - ref_count if total is not None and ref_count is not None else None
            fragmented.append({
                "table": table, "total": total, "reference": ref_count,
                "difference": difference, "new": new,
            })
        else:
            counts = []
            for site in fragments:
                count = site["counts"].get(table) if site["status"] == "up" else None
                difference = count - ref_count if count is not None and ref_count is not None else None
                counts.append({"site": site["name"], "count": count, "difference": difference})
            replicated.append({"table": table, "reference": ref_count, "sites": counts})
    return {"fragmented": fragmented, "replicated": replicated}


class Dashboard:
    """Own thread-safe snapshots, freshness deadlines, and the last 200 events."""

    def __init__(self, config: dict) -> None:
        self.lock = threading.Lock()
        self.events: deque[dict] = deque(maxlen=200)
        self.sites = {
            name: {
                **site, "status": "waiting", "counts": {}, "new": {},
                "last_poll": None, "last_success": None, "latency_ms": None, "error": "",
            }
            for name, site in config["sites"].items()
        }
        self.completed = {name: time.monotonic() for name in self.sites}

    def _replace(self, name: str, current: dict, at: str) -> None:
        self.events.extendleft(event_diff(self.sites[name], current, at))
        self.sites[name] = current

    def publish(self, name: str, result: dict) -> None:
        """Publish one completed poll, preserving counts on failure."""
        with self.lock:
            at = timestamp()
            current = {**self.sites[name], **result, "last_poll": at}
            if current["status"] == "up":
                current["last_success"] = at
            self._replace(name, current, at)
            self.completed[name] = time.monotonic()

    def expire(self, now: float) -> None:
        """Mark stalled workers down without waiting for network timeouts."""
        with self.lock:
            for name, site in self.sites.items():
                if site["status"] != "down" and now - self.completed[name] >= STALE_AFTER:
                    self._replace(name, {
                        **site, "status": "down", "latency_ms": None,
                        "error": "Quá 2 giây chưa nhận được kết quả; số đếm cũ không được cộng vào tổng.",
                    }, timestamp())

    def snapshot(self) -> dict:
        """Return a detached JSON-ready snapshot, including comparisons."""
        with self.lock:
            sites = copy.deepcopy(self.sites)
            events = list(self.events)
        return {
            "at": timestamp(), "tables": TABLES, "sites": sites, "events": events,
            "last_poll": max((site["last_poll"] for site in sites.values() if site["last_poll"]), default=None),
            "summary": summarize(sites),
        }


def poll_site(name: str, config: dict, state: Dashboard, stop: threading.Event, driver: ModuleType) -> None:
    """Poll one direct connection each second; reconnect after any database error."""
    site = config["sites"][name]
    connection = None
    try:
        while not stop.is_set():
            started = time.monotonic()
            query_started = None
            try:
                if connection is None:
                    connection = driver.connect(
                        host=site["ip"], port=site["port"], dbname=config["dbname"],
                        user="postgres", connect_timeout=1, autocommit=True,
                        prepare_threshold=None, application_name="cs5104-dashboard",
                        options="-c statement_timeout=800 -c default_transaction_read_only=on -c search_path=pg_catalog",
                        keepalives=1, keepalives_idle=1, keepalives_interval=1,
                        keepalives_count=1, tcp_user_timeout=1000,
                    )
                query_started = time.monotonic()
                with connection.cursor() as cursor:
                    cursor.execute(COUNT_SQL)
                    rows = cursor.fetchall()
                latency = round((time.monotonic() - query_started) * 1000, 1)
                counts = {table: count for table, count, new in rows}
                new_counts = {table: new for table, count, new in rows}
                if len(rows) != len(TABLES) or set(counts) != set(TABLES):
                    raise ValueError("Truy vấn không trả đủ số đếm của 10 bảng")
                state.publish(name, {
                    "status": "up", "counts": counts, "new": new_counts,
                    "latency_ms": latency, "error": "",
                })
            except (driver.Error, OSError, ValueError) as error:
                state.publish(name, {
                    "status": "down", "error": str(error),
                    "latency_ms": round((time.monotonic() - query_started) * 1000, 1) if query_started is not None else None,
                })
                if connection is not None:
                    connection.close()
                    connection = None
            stop.wait(max(0.0, POLL_INTERVAL - (time.monotonic() - started)))
    finally:
        if connection is not None:
            connection.close()


def watch_freshness(state: Dashboard, stop: threading.Event) -> None:
    """Enforce freshness even when a worker is stuck on a broken network."""
    while not stop.wait(0.1):
        state.expire(time.monotonic())


PAGE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CS5104 · Theo dõi cơ sở dữ liệu phân tán</title>
<style>
:root { color-scheme: light; --good:#176c3b; --bad:#b32323; --warn:#805000; --line:#d9e1e8; --muted:#526170; }
* { box-sizing:border-box; }
body { margin:0; color:#192b3b; background:#f2f5f8; font:15px/1.5 "Segoe UI",Arial,sans-serif; }
header { padding:18px 24px; background:white; border-bottom:1px solid var(--line); }
h1 { margin:0; font-size:23px; } h2 { margin:0 0 8px; font-size:19px; }
p { margin:6px 0; } small,.muted { color:var(--muted); }
main { display:grid; grid-template-columns:minmax(0,1fr) 330px; gap:18px; padding:18px 24px; }
#tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
.tile,.panel,aside { background:white; border:1px solid var(--line); border-radius:12px; padding:14px; }
.tile { border:2px solid var(--line); min-width:0; }
.tile.good { border-color:var(--good); } .tile.warn { border-color:var(--warn); background:#fff8e8; }
.tile.bad { border-color:var(--bad); background:#fff1f1; }
.good { color:var(--good); } .bad { color:var(--bad); } .warn { color:var(--warn); }
.tile h2 { color:#192b3b; } .status { font-weight:700; } .meta { color:var(--muted); overflow-wrap:anywhere; }
.error { color:var(--bad); overflow-wrap:anywhere; font-size:13px; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th,td { text-align:right; padding:5px 7px; border-bottom:1px solid var(--line); white-space:nowrap; }
th { color:var(--muted); font-weight:600; } th:first-child,td:first-child { text-align:left; }
.tile table { font-size:13px; } .tile th,.tile td { padding:4px 2px; }
.panel { margin-top:18px; } .scroll { overflow-x:auto; } .panel table { min-width:570px; }
aside { align-self:start; position:sticky; top:16px; max-height:calc(100vh - 32px); overflow:auto; }
#events { list-style:none; margin:0; padding:0; }
#events li { padding:8px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; }
#events time { display:block; color:var(--muted); font-size:12px; }
#connection { margin-top:8px; font-weight:600; } .changed { animation:flash 1.6s ease-out; }
@keyframes flash { from { background-color:#ffe190; } to { background-color:transparent; } }
@media (prefers-reduced-motion:reduce) { .changed { animation:none; outline:2px solid #b36e00; } }
@media (max-width:1000px) { main { grid-template-columns:1fr; } aside { position:static; max-height:420px; } }
@media (max-width:600px) { header,main { padding:12px; } }
</style>
</head>
<body>
<header>
<h1>CS5104 · Theo dõi cơ sở dữ liệu phân tán</h1>
<p>Hồ sơ khám bệnh liên tỉnh · Đọc trực tiếp từng trạm · Chỉ đọc · Cập nhật mỗi giây</p>
<div id="connection" role="status">Đang tải trạng thái…</div>
<small id="last-poll">Chưa có lần kiểm tra nào.</small>
</header>
<main>
<div>
<section id="tiles" aria-label="Trạng thái từng trạm"></section>
<section class="panel" aria-labelledby="fragmented-title">
<h2 id="fragmented-title">Đối chiếu 8 bảng phân mảnh</h2>
<p class="muted">Chênh lệch = tổng bốn trạm − đối chứng. Thiếu trạm: không tính tổng, không thay bằng 0.</p>
<div class="scroll"><table><thead><tr><th scope="col">Bảng</th><th scope="col">Tổng 4 trạm</th><th scope="col">Đối chứng</th><th scope="col">Chênh lệch</th><th scope="col">Dòng mới</th></tr></thead><tbody id="fragmented"></tbody></table></div>
<p class="muted">Dòng mới: patient_id &gt; 20000; visit_id &gt; 80000; prescription_id &gt; 200000.
Các bảng con dùng visit_id &gt; 80000. Màu vàng: phần tăng khớp số dòng mới; màu đỏ: chênh lệch khác.</p>
</section>
<section class="panel" aria-labelledby="replicated-title">
<h2 id="replicated-title">Đối chiếu bảng sao chép</h2>
<div class="scroll"><table><thead id="replicated-head"></thead><tbody id="replicated"></tbody></table></div>
<p class="muted">Mỗi ô: số dòng (chênh lệch so với đối chứng). Không cộng các bản sao.</p>
<p class="muted">Các trạm được đọc độc lập; số đếm có thể lệch tạm thời khi đang nhập.
Đối chiếu số dòng không thay thế kiểm tra nội dung bằng make check.</p>
</section>
</div>
<aside aria-labelledby="events-title"><h2 id="events-title">Nhật ký sự kiện</h2>
<p class="muted">Mới nhất trước · Giữ 200 sự kiện · Tăng/giảm ròng giữa hai lần đọc thành công.</p>
<ul id="events"><li>Chưa có sự kiện.</li></ul></aside>
</main>
<script>
const history = new Map();
const number = new Intl.NumberFormat('vi-VN');
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const format = value => value == null ? '—' : number.format(value);
const signed = value => value == null ? '—' : `${value > 0 ? '+' : ''}${format(value)}`;
const date = value => value ? new Date(value).toLocaleString('vi-VN') : '—';
function changed(key, value) {
    const different = history.has(key) && history.get(key) !== value;
    history.set(key, value);
    return different ? ' changed' : '';
}
function cell(key, value, tone = '', display = format(value)) {
    return `<td class="${tone}${changed(key, value)}">${escapeHTML(display)}</td>`;
}
function render(state) {
    document.getElementById('last-poll').textContent = `Lần kiểm tra gần nhất: ${date(state.last_poll)}`;
    document.getElementById('tiles').innerHTML = Object.values(state.sites).map(site => {
        const tone = {up:'good', down:'bad', waiting:'warn'}[site.status];
        const status = {up:'Đang kết nối', down:'Mất kết nối / không đọc được', waiting:'Đang kiểm tra'}[site.status];
        const tileChange = changed(`tile:${site.name}`, JSON.stringify([site.status, site.counts, site.new]));
        const rows = state.tables.map(table => `<tr><th scope="row">${escapeHTML(table)}</th>${cell(`${site.name}:${table}`, site.counts[table], site.status === 'up' ? '' : 'muted')}${cell(`${site.name}:${table}:new`, ['hospital','drug'].includes(table) ? null : site.new[table])}</tr>`).join('');
        return `<article class="tile ${tone}${tileChange}"><h2>${escapeHTML(site.label)}</h2>
            <p class="meta">Máy ${escapeHTML(site.machine)} (${escapeHTML(site.hostname)}) · ${escapeHTML(site.ip)}:${site.port}<br>${site.reference ? 'Cơ sở dữ liệu đối chứng' : site.central ? 'Trạm trung tâm' : 'Trạm phân mảnh'}</p>
            <p class="status ${tone}">${status}</p>
            <p class="meta">Lần kiểm tra: ${date(site.last_poll)}<br>Đọc thành công: ${date(site.last_success)}<br>Truy vấn: ${format(site.latency_ms)} ms</p>
            ${site.error ? `<p class="error">${escapeHTML(site.error)}</p>` : ''}
            ${site.status !== 'up' && site.last_success ? '<p class="warn">Số đếm cũ, chỉ để tham khảo.</p>' : ''}
            <table><thead><tr><th scope="col">Bảng</th><th scope="col">Số dòng</th><th scope="col">Mới</th></tr></thead><tbody>${rows}</tbody></table></article>`;
    }).join('');
    document.getElementById('fragmented').innerHTML = state.summary.fragmented.map(row => {
        const tone = row.difference == null ? 'muted' : row.difference === 0 ? 'good' : row.difference === row.new ? 'warn' : 'bad';
        return `<tr><th scope="row">${escapeHTML(row.table)}</th>${cell(`${row.table}:total`, row.total)}${cell(`${row.table}:ref`, row.reference)}${cell(`${row.table}:difference`, row.difference, tone, signed(row.difference))}${cell(`${row.table}:new`, row.new)}</tr>`;
    }).join('');
    const fragments = Object.values(state.sites).filter(site => !site.reference);
    document.getElementById('replicated-head').innerHTML = `<tr><th scope="col">Bảng</th><th scope="col">Đối chứng</th>${fragments.map(site => `<th scope="col">${escapeHTML(site.label)}</th>`).join('')}</tr>`;
    document.getElementById('replicated').innerHTML = state.summary.replicated.map(row => `<tr><th scope="row">${escapeHTML(row.table)}</th>${cell(`${row.table}:ref`, row.reference)}${row.sites.map(site => cell(`${row.table}:replica:${site.site}`, `${site.count}:${site.difference}`, site.difference == null ? 'muted' : site.difference === 0 ? 'good' : 'bad', `${format(site.count)} (${signed(site.difference)})`)).join('')}</tr>`).join('');
    document.getElementById('events').innerHTML = state.events.map(event => `<li class="${event.level}"><time datetime="${escapeHTML(event.at)}">${date(event.at)}</time><strong>${escapeHTML(state.sites[event.site].label)}</strong>: ${escapeHTML(event.text)}</li>`).join('') || '<li>Chưa có sự kiện.</li>';
}
let busy = false;
async function refresh() {
    if (busy) return;
    busy = true;
    const connection = document.getElementById('connection');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 900);
    try {
        const response = await fetch('/api/state', {cache:'no-store', signal:controller.signal});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        render(await response.json());
        connection.textContent = 'Đang nhận trạng thái trực tiếp';
        connection.className = 'good';
    } catch (error) {
        connection.textContent = `Mất kết nối dashboard; dữ liệu hiển thị có thể đã cũ. ${error.message}`;
        connection.className = 'bad';
    } finally {
        clearTimeout(timer);
        busy = false;
    }
}
refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>
"""


def make_handler(state: Dashboard) -> type[BaseHTTPRequestHandler]:
    """Serve the inline page and cached JSON; HTTP never queries a database."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Return the dashboard or state; reject unknown routes."""
            route = urlsplit(self.path).path
            if route == "/":
                content, content_type = PAGE.encode("utf-8"), "text/html; charset=utf-8"
            elif route == "/api/state":
                content = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, format: str, *args: object) -> None:
            """Log HTTP failures without flooding stdout every refresh."""
            if len(args) > 1 and str(args[1]) == "200":
                return
            super().log_message(format, *args)

    return Handler


def selftest() -> None:
    """Assert event, comparison, freshness, and retention behavior without a DB."""
    config = {"sites": {name: {"name": name, "label": label} for name, label in LABELS.items()}}
    state = Dashboard(config)
    good = {"status": "up", "counts": {table: 10 for table in TABLES}, "new": {table: 0 for table in TABLES}, "error": ""}
    waiting = state.snapshot()["sites"]["hcm"]
    initial = {**waiting, **good}
    assert [event["kind"] for event in event_diff(waiting, initial, "first")] == ["connected"]
    assert event_diff(initial, initial, "same") == []
    added = {**initial, "counts": {**good["counts"], "patient": 13, "visit_eye_diagnosis": 12}}
    assert [(event["table"], event["delta"]) for event in event_diff(initial, added, "add")] == [("patient", 3), ("visit_eye_diagnosis", 2)]
    down = {**added, "status": "down"}
    assert [event["kind"] for event in event_diff(added, down, "down")] == ["down"]
    assert event_diff(down, down, "still down") == []
    reconnected = {**added, "counts": {**added["counts"], "patient": 15}}
    recovery = event_diff(down, reconnected, "recovery")
    assert [event["kind"] for event in recovery] == ["reconnected", "rows_added"]
    assert recovery[1]["delta"] == 2 and recovery[1]["at"] == "recovery"
    assert event_diff(reconnected, initial, "reset")[0]["kind"] == "rows_removed"
    assert state.snapshot()["summary"]["fragmented"][0]["total"] is None
    for name in LABELS:
        counts = {table: 40 if name == "ref" and table in NEW_ROWS else 10 for table in TABLES}
        state.publish(name, {**good, "counts": counts})
    summary = state.snapshot()["summary"]
    assert len(summary["fragmented"]) == 8 and len(summary["replicated"]) == 2
    assert all(row["difference"] == 0 and row["new"] == 0 for row in summary["fragmented"])
    assert all(site["difference"] == 0 for row in summary["replicated"] for site in row["sites"])
    state.publish("hcm", {**good, "counts": {**good["counts"], "patient": 13}, "new": {**good["new"], "patient": 3}})
    patient = state.snapshot()["summary"]["fragmented"][0]
    assert (patient["total"], patient["reference"], patient["difference"], patient["new"]) == (43, 40, 3, 3)
    state.publish("hcm", {"status": "down", "error": "synthetic failure"})
    snapshot = state.snapshot()
    assert snapshot["sites"]["hcm"]["counts"]["patient"] == 13
    assert snapshot["summary"]["fragmented"][0]["total"] is None
    assert snapshot["summary"]["replicated"][0]["sites"][1]["count"] is None
    state.publish("hcm", {**good, "counts": {**good["counts"], "patient": 14}})
    assert state.snapshot()["events"][0]["delta"] == 1
    state.publish("ref", {"status": "down"})
    patient = state.snapshot()["summary"]["fragmented"][0]
    assert patient["total"] == 44 and patient["reference"] is None and patient["difference"] is None
    snapshot["sites"]["hcm"]["counts"]["patient"] = -1
    assert state.snapshot()["sites"]["hcm"]["counts"]["patient"] == 14
    for count in range(15, 220):
        state.publish("hcm", {**good, "counts": {**good["counts"], "patient": count}})
    events = state.snapshot()["events"]
    assert len(events) == 200 and events[0]["kind"] == "rows_added"
    assert all(events[index]["at"] >= events[index + 1]["at"] for index in range(len(events) - 1))
    state.expire(max(state.completed.values()) + STALE_AFTER)
    assert all(site["status"] == "down" for site in state.snapshot()["sites"].values())
    event_count = len(state.events)
    state.expire(time.monotonic() + 100)
    assert len(state.events) == event_count
    assert COUNT_SQL.count(" FROM public.") == 10 and COUNT_SQL.count("UNION ALL") == 9
    assert NEW_ROWS["patient"] == "patient_id > 20000"
    assert NEW_ROWS["prescription"] == "prescription_id > 200000"
    assert all(NEW_ROWS[table] == "visit_id > 80000" for table in TABLES[5:])
    print("Selftest: PASS (events, comparisons, freshness, retention; no database)")


def main() -> None:
    """Run offline checks or start the dashboard on machine A, port 8090."""
    parser = argparse.ArgumentParser(description="Theo dõi trực tiếp cơ sở dữ liệu phân tán CS5104")
    parser.add_argument("--selftest", action="store_true", help="Kiểm tra bằng dữ liệu giả, không kết nối CSDL")
    arguments = parser.parse_args()
    if arguments.selftest:
        selftest()
        return
    try:
        config = load_config(Path(__file__).resolve().parents[1] / "deploy.toml")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        import psycopg
    except ImportError:
        parser.error("Thiếu psycopg; chạy bằng ~/cs5104-venv/bin/python (psycopg 3.3.6)")
    state = Dashboard(config)
    stop = threading.Event()
    workers = [
        threading.Thread(target=poll_site, args=(name, config, state, stop, psycopg), daemon=True, name=f"poll-{name}")
        for name in config["sites"]
    ]
    workers.append(threading.Thread(target=watch_freshness, args=(state, stop), daemon=True, name="freshness"))
    try:
        with ThreadingHTTPServer(("0.0.0.0", 8090), make_handler(state)) as server:
            for worker in workers:
                worker.start()
            print(f"Dashboard: http://{config['sites']['tayninh']['ip']}:8090 · chỉ đọc · Ctrl+C để dừng", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng dashboard.")
    except OSError as error:
        parser.error(str(error))
    finally:
        stop.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(timeout=0.2)


if __name__ == "__main__":
    main()
