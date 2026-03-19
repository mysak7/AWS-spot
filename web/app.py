import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))           # web/ — for jobs.py
sys.path.insert(0, str(BASE_DIR.parent / "src"))  # src/ — for all domain modules

from config import DEFAULT_INSTANCE_TYPES, DEFAULT_REGIONS, FREE_TIER_TYPES
from credentials import load_credentials, validate_credentials
from instance_catalog import get_instance_info
from inventory import load_hosts
from provisioner import provision_instance, terminate_host
from spot_scanner import scan_spot_prices
from jobs import create_job, get_job, update_job
from config_store import load_config, save_config
from agent.sessions import (
    create_session, append_log, finish_session,
    load_session, load_session_meta, read_log, list_sessions,
)
from agent.runner import run_agent
from agent.stop_flags import create_flag, request_stop, cleanup as cleanup_stop_flag
from llm_log import load_log, get_totals, INPUT_COST_PER_M, OUTPUT_COST_PER_M

creds: dict[str, str] = {}
account_id: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global creds, account_id
    creds = load_credentials()
    account_id = validate_credentials(creds)
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def ctx(request: Request, **kw: Any) -> dict[str, Any]:
    return {"request": request, "account_id": account_id, **kw}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    hosts = load_hosts()
    running = [h for h in hosts if h.get("status") == "running"]
    total_mo = sum(float(h.get("monthly_price_usd", 0)) for h in running)
    recent = sorted(hosts, key=lambda h: h.get("launched_at", ""), reverse=True)[:6]
    return templates.TemplateResponse("dashboard.html", ctx(
        request,
        recent=recent,
        total_hosts=len(hosts),
        running_count=len(running),
        terminated_count=len([h for h in hosts if h.get("status") == "terminated"]),
        total_monthly=f"{total_mo:.2f}",
        active_page="dashboard",
    ))


# ── Scan ──────────────────────────────────────────────────────────────────────

@app.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    return templates.TemplateResponse("scan.html", ctx(
        request,
        instance_types=DEFAULT_INSTANCE_TYPES,
        regions=DEFAULT_REGIONS,
        free_tier_types=FREE_TIER_TYPES,
        active_page="scan",
    ))


@app.post("/scan/start", response_class=HTMLResponse)
async def scan_start(request: Request):
    form = await request.form()
    sel_types = list(form.getlist("instance_types")) or DEFAULT_INSTANCE_TYPES
    sel_regions = list(form.getlist("regions")) or DEFAULT_REGIONS
    job_id = create_job("scan")

    def run() -> None:
        try:
            def on_progress(region: str, i: int, total: int) -> None:
                update_job(job_id, message=f"Scanning {region}… ({i}/{total})")

            results = scan_spot_prices(sel_types, creds, sel_regions, progress_cb=on_progress)
            found = list({r["instance_type"] for r in results})
            catalog = get_instance_info(found, creds, creds["aws_region"]) if found else {}
            update_job(job_id, status="done", result={"results": results, "catalog": catalog})
        except Exception as e:
            update_job(job_id, status="error", error=str(e))

    Thread(target=run, daemon=True).start()
    return templates.TemplateResponse(
        "partials/scan_pending.html", ctx(request, job_id=job_id, message="Starting scan…")
    )


@app.get("/scan/status/{job_id}", response_class=HTMLResponse)
async def scan_status(request: Request, job_id: str):
    job = get_job(job_id)
    if job is None:
        return HTMLResponse('<p class="text-red-400 text-sm">Job not found.</p>')
    if job["status"] == "running":
        return templates.TemplateResponse(
            "partials/scan_pending.html", ctx(request, job_id=job_id, message=job["message"])
        )
    if job["status"] == "done":
        r = job["result"]
        return templates.TemplateResponse("partials/scan_results.html", ctx(
            request,
            results=r["results"],
            catalog=r["catalog"],
            free_tier_types=FREE_TIER_TYPES,
        ))
    return HTMLResponse(
        f'<p class="text-red-400 text-sm p-3 rounded-lg bg-red-950 border border-red-800">'
        f'Scan failed: {job.get("error")}</p>'
    )


# ── Launch ────────────────────────────────────────────────────────────────────

@app.post("/launch/start", response_class=HTMLResponse)
async def launch_start(request: Request):
    form = await request.form()
    region = str(form["region"])
    az = str(form["az"])
    instance_type = str(form["instance_type"])
    spot_price_usd = str(form["spot_price_usd"])
    job_id = create_job("launch")

    def run() -> None:
        def on_progress(msg: str) -> None:
            update_job(job_id, message=msg)
        try:
            host = provision_instance(region, az, instance_type, spot_price_usd, creds, on_progress)
            update_job(job_id, status="done", result=host)
        except Exception as e:
            update_job(job_id, status="error", error=str(e))

    Thread(target=run, daemon=True).start()
    return templates.TemplateResponse(
        "partials/launch_pending.html", ctx(request, job_id=job_id, job=get_job(job_id))
    )


@app.get("/launch/status/{job_id}", response_class=HTMLResponse)
async def launch_status(request: Request, job_id: str):
    job = get_job(job_id)
    if job is None:
        return HTMLResponse('<p class="text-red-400 text-sm">Job not found.</p>')
    if job["status"] == "running":
        return templates.TemplateResponse(
            "partials/launch_pending.html", ctx(request, job_id=job_id, job=job)
        )
    if job["status"] == "done":
        return templates.TemplateResponse(
            "partials/launch_success.html", ctx(request, host=job["result"])
        )
    return HTMLResponse(
        f'<div class="text-red-400 text-sm p-3 rounded-lg bg-red-950 border border-red-800">'
        f'Launch failed: {job.get("error")}</div>'
    )


# ── Inventory ─────────────────────────────────────────────────────────────────

def _host_cost(host: dict) -> float | None:
    """Total spend so far: running = now, terminated = terminated_at."""
    from datetime import datetime, timezone
    try:
        launched = datetime.fromisoformat(
            (host.get("launched_at") or "").replace("Z", "+00:00")
        )
        if host.get("status") == "terminated" and host.get("terminated_at"):
            end = datetime.fromisoformat(host["terminated_at"].replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)
        hours = max((end - launched).total_seconds() / 3600, 0)
        return round(hours * float(host.get("spot_price_usd", 0)), 4)
    except Exception:
        return None


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    hosts = load_hosts()
    for h in hosts:
        h["_cost_usd"] = _host_cost(h)
    hosts = sorted(hosts, key=lambda h: h.get("launched_at") or "", reverse=True)
    hosts = sorted(hosts, key=lambda h: 0 if h.get("status") == "running" else 1)
    return templates.TemplateResponse("inventory.html", ctx(
        request, hosts=hosts, active_page="inventory"
    ))


@app.get("/host/{host_id}/row", response_class=HTMLResponse)
async def host_row(request: Request, host_id: str):
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    if not host:
        return HTMLResponse(f'<tr id="row-{host_id}"></tr>')
    return templates.TemplateResponse("partials/host_row.html", ctx(request, host=host))


@app.get("/host/{host_id}/edit", response_class=HTMLResponse)
async def host_edit_form(request: Request, host_id: str):
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    if not host:
        return HTMLResponse(f'<tr id="row-{host_id}"></tr>')
    return templates.TemplateResponse("partials/host_edit_row.html", ctx(request, host=host))


@app.post("/host/{host_id}/edit", response_class=HTMLResponse)
async def host_edit_save(request: Request, host_id: str):
    form = await request.form()
    updates: dict[str, str] = {
        "name": str(form.get("name", "")).strip(),
        "notes": str(form.get("notes", "")).strip(),
    }
    # Allow editing public_ip in case it changed (e.g. elastic IP swap)
    if form.get("public_ip"):
        ip = str(form["public_ip"]).strip()
        updates["public_ip"] = ip
        # Rebuild ssh_cmd with new IP
        hosts = load_hosts()
        host = next((h for h in hosts if h["host_id"] == host_id), None)
        if host:
            updates["ssh_cmd"] = host["ssh_cmd"].rsplit("@", 1)[0] + "@" + ip
    from inventory import update_host, InventoryError
    try:
        update_host(host_id, updates)
    except InventoryError as e:
        return HTMLResponse(f'<tr id="row-{host_id}"><td colspan="10" class="text-red-400 p-3 text-sm">{e}</td></tr>')
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    return templates.TemplateResponse("partials/host_row.html", ctx(request, host=host))


@app.post("/terminate/{host_id}", response_class=HTMLResponse)
async def do_terminate(request: Request, host_id: str):
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    if not host:
        return HTMLResponse(
            f'<tr id="row-{host_id}"><td colspan="9" class="text-red-400 p-3 text-sm">'
            f'Host {host_id} not found.</td></tr>'
        )
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, terminate_host, host, creds)
        from datetime import datetime, timezone
        terminated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        from inventory import update_host
        update_host(host_id, {"status": "terminated", "terminated_at": terminated_at})
        host = {**host, "status": "terminated", "terminated_at": terminated_at}
    except Exception as e:
        host = {**host, "_error": str(e)}
    return templates.TemplateResponse("partials/host_row.html", ctx(request, host=host))


# ── Host workbench ────────────────────────────────────────────────────────────

@app.get("/host/{host_id}", response_class=HTMLResponse)
async def host_detail(request: Request, host_id: str):
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    if not host:
        return HTMLResponse('<p class="text-red-400 p-8">Host not found.</p>')
    sessions = list_sessions(host_id)
    return templates.TemplateResponse("host_detail.html", ctx(
        request, host=host, sessions=sessions, active_page="inventory",
    ))


@app.post("/host/{host_id}/run", response_class=HTMLResponse)
async def host_run(request: Request, host_id: str):
    form = await request.form()
    instruction = str(form.get("instruction", "")).strip()
    if not instruction:
        return HTMLResponse('<p class="text-red-400 text-sm">Instruction cannot be empty.</p>')

    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    if not host:
        return HTMLResponse('<p class="text-red-400 text-sm">Host not found.</p>')

    session_id = create_session(host_id, instruction)
    cfg = load_config()
    stop_event = create_flag(session_id)

    def do_run() -> None:
        def on_log(entry: dict) -> None:
            append_log(host_id, session_id, entry)
        try:
            summary, final_status = run_agent(
                host, instruction, on_log,
                claude_bin=cfg["claude_bin"],
                session_id=session_id,
                stop_event=stop_event,
            )
            finish_session(host_id, session_id, final_status, summary)
        except Exception as e:
            append_log(host_id, session_id, {"type": "error", "content": str(e)})
            finish_session(host_id, session_id, "failed", str(e))
        finally:
            cleanup_stop_flag(session_id)

    Thread(target=do_run, daemon=True).start()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        f"/host/{host_id}/session/{session_id}", status_code=303
    )


@app.post("/host/{host_id}/session/{session_id}/stop", response_class=HTMLResponse)
async def session_stop(host_id: str, session_id: str):
    request_stop(session_id)
    return HTMLResponse(
        '<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs '
        'bg-orange-900/60 text-orange-300 border border-orange-800">stopping…</span>'
    )


@app.get("/host/{host_id}/session/{session_id}", response_class=HTMLResponse)
async def session_detail(request: Request, host_id: str, session_id: str):
    hosts = load_hosts()
    host = next((h for h in hosts if h["host_id"] == host_id), None)
    try:
        session = load_session(host_id, session_id)
    except Exception:
        return HTMLResponse('<p class="text-red-400 p-8">Session not found.</p>')
    return templates.TemplateResponse("session_detail.html", ctx(
        request, host=host, session=session, active_page="inventory",
    ))


# ── LLM Usage ─────────────────────────────────────────────────────────────────

@app.get("/llm", response_class=HTMLResponse)
async def llm_page(request: Request):
    entries = load_log()
    entries_desc = list(reversed(entries))
    totals = get_totals(entries)
    return templates.TemplateResponse("llm.html", ctx(
        request,
        entries=entries_desc,
        totals=totals,
        input_cost_per_m=INPUT_COST_PER_M,
        output_cost_per_m=OUTPUT_COST_PER_M,
        active_page="llm",
    ))


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    return templates.TemplateResponse("settings.html", ctx(
        request, config=load_config(), saved=saved, active_page="settings",
    ))


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    form = await request.form()
    save_config({"claude_bin": str(form.get("claude_bin", "")).strip()})
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/test")
async def settings_test():
    import asyncio
    cfg = load_config()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cfg["claude_bin"].split(), "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return {"ok": True, "version": stdout.decode().strip()}
        return {"ok": False, "error": stderr.decode().strip() or f"exit {proc.returncode}"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/host/{host_id}/session/{session_id}/stream")
async def session_stream(host_id: str, session_id: str, skip: int = 0):
    async def generate():
        sent = skip
        while True:
            log = read_log(host_id, session_id)
            for entry in log[sent:]:
                yield f"data: {json.dumps(entry)}\n\n"
                sent += 1
            try:
                meta = load_session_meta(host_id, session_id)
            except Exception:
                break
            if meta.get("status") in ("done", "failed"):
                yield f"data: {json.dumps({'type': 'done', 'status': meta['status'], 'summary': meta.get('summary', '')})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
