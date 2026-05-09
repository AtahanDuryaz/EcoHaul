"""
Canlı simülasyon API router'ı.

POST /api/simulation/start          → simülasyonu başlat
POST /api/simulation/stop           → durdur
POST /api/simulation/reset          → sıfırla
PATCH /api/simulation/speed         → hız ayarla {multiplier: int}
GET  /api/simulation/live-state     → anlık bin + kamyon durumu
GET  /api/simulation/live-kpis      → anlık KPI özeti
GET  /api/simulation/anomalies      → son 50 simülasyon anomalisi
GET  /api/simulation/export-csv     → fill history CSV indir
"""
import csv
import io

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from ..simulation_engine import SPEED_OPTIONS, engine

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/start")
async def start_simulation():
    await engine.start()
    return {"status": "running", "speed_multiplier": engine.speed_multiplier}


@router.post("/stop")
async def stop_simulation():
    await engine.stop()
    return {"status": "stopped"}


@router.post("/reset")
async def reset_simulation():
    was_running = engine.is_running
    await engine.stop()
    engine.reset()
    if was_running:
        await engine.start()
    return {"status": "reset"}


@router.patch("/speed")
async def set_speed(multiplier: int = Body(..., embed=True)):
    valid = list(SPEED_OPTIONS.values())
    if multiplier not in valid:
        return {"error": f"Geçersiz hız. Kullanılabilir: {valid}"}
    engine.speed_multiplier = multiplier
    return {"speed_multiplier": multiplier}


@router.get("/live-state")
def get_live_state():
    return engine.state_snapshot()


@router.get("/live-kpis")
def get_live_kpis():
    return engine.kpis_snapshot()


@router.get("/anomalies")
def get_anomalies():
    return list(reversed(engine.recent_anomalies))


@router.get("/export-csv")
def export_fill_history():
    history = engine.fill_history
    if not history:
        return {"message": "Henüz kayıt yok. Simülasyonu çalıştırın."}

    fieldnames = ["sim_time", "world", "bin_id", "event",
                  "fill_pct", "fill_label", "distance_label", "fill_rate"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(history)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fill_history.csv"},
    )
