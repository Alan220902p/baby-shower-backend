import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# --- Config -----------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rsvp.db")
# Railway/Heroku-style Postgres URLs sometimes start with postgres:// which
# SQLAlchemy 2.x no longer accepts directly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- Model --------------------------------------------------------------

class RSVP(Base):
    __tablename__ = "rsvps"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    acompanantes = Column(Integer, nullable=False, default=1)
    dedicatoria = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


# --- Schemas ------------------------------------------------------------

class RSVPCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    acompanantes: int = Field(ge=1, le=30)
    dedicatoria: str | None = Field(default=None, max_length=500)


class RSVPOut(BaseModel):
    id: int
    nombre: str
    acompanantes: int
    dedicatoria: str | None
    created_at: datetime

    class Config:
        from_attributes = True


# --- App ------------------------------------------------------------------

app = FastAPI(title="Baby Shower RSVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "service": "baby-shower-rsvp-api"}


@app.get("/debug-token")
def debug_token():
    """TEMPORAL: solo para diagnosticar el problema del token. Borrar despues."""
    return {
        "length": len(ADMIN_TOKEN),
        "repr": repr(ADMIN_TOKEN),
    }


@app.post("/api/rsvp", response_model=RSVPOut)
def create_rsvp(payload: RSVPCreate):
    db = SessionLocal()
    try:
        rsvp = RSVP(
            nombre=payload.nombre.strip(),
            acompanantes=payload.acompanantes,
            dedicatoria=(payload.dedicatoria or "").strip() or None,
        )
        db.add(rsvp)
        db.commit()
        db.refresh(rsvp)
        return rsvp
    finally:
        db.close()


@app.get("/api/rsvp", response_model=list[RSVPOut])
def list_rsvp(token: str = Query(...)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")
    db = SessionLocal()
    try:
        rows = db.query(RSVP).order_by(RSVP.created_at.desc()).all()
        return rows
    finally:
        db.close()


@app.delete("/api/rsvp/{rsvp_id}")
def delete_rsvp(rsvp_id: int, token: str = Query(...)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")
    db = SessionLocal()
    try:
        rsvp = db.query(RSVP).filter(RSVP.id == rsvp_id).first()
        if not rsvp:
            raise HTTPException(status_code=404, detail="No encontrado")
        db.delete(rsvp)
        db.commit()
        return {"deleted": rsvp_id}
    finally:
        db.close()


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    """Simple password-protected page to see who has confirmed."""
    return """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Confirmaciones · Bebé Flores López</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body { font-family: system-ui, sans-serif; background: #FBF1DC; color: #241B12; margin:0; padding: 2rem 1rem; }
  h1 { font-size: 1.4rem; }
  .box { max-width: 780px; margin: 0 auto; }
  input { padding: .6rem .8rem; border-radius: 8px; border: 1px solid #ccc; font-size: 1rem; }
  button { padding: .6rem 1.2rem; border-radius: 8px; border: none; background: #D98E04; color: white; font-weight: bold; cursor: pointer; }
  button:hover { opacity: 0.9; }
  table { width: 100%; border-collapse: collapse; margin-top: 1.5rem; background: white; border-radius: 12px; overflow: hidden; }
  th, td { text-align: left; padding: .7rem .9rem; border-bottom: 1px solid #eee; font-size: .92rem; }
  th { background: #F2B705; color: #241B12; }
  .summary-cards { display: flex; gap: 1rem; margin-top: 1.5rem; flex-wrap: wrap; }
  .card { background: white; border-radius: 14px; padding: 1rem 1.4rem; box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
  .card .num { font-size: 1.8rem; font-weight: 700; color: #B36A00; display: block; }
  .card .label { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; opacity: .7; }
  .del-btn { background: #B3261E; padding: .35rem .8rem; font-size: .8rem; }
  .err { color: #b3261e; margin-top: 1rem; }
</style>
</head>
<body>
<div class="box">
  <h1>🐝 Confirmaciones — Baby Shower</h1>
  <div>
    <input id="token" type="password" placeholder="Token de administrador" />
    <button onclick="load()">Ver confirmaciones</button>
  </div>
  <div id="summary" class="summary-cards"></div>
  <div id="out"></div>
</div>
<script>
let currentToken = '';

async function load() {
  currentToken = document.getElementById('token').value;
  const out = document.getElementById('out');
  const summary = document.getElementById('summary');
  out.innerHTML = 'Cargando...';
  summary.innerHTML = '';
  try {
    const res = await fetch(`/api/rsvp?token=${encodeURIComponent(currentToken)}`);
    if (!res.ok) { out.innerHTML = '<p class="err">Token inválido</p>'; return; }
    const data = await res.json();
    renderSummary(data);
    renderTable(data);
  } catch (e) {
    out.innerHTML = '<p class="err">Error al conectar con el servidor</p>';
  }
}

function renderSummary(data) {
  const summary = document.getElementById('summary');
  const totalPersonas = data.reduce((s, r) => s + r.acompanantes, 0);
  summary.innerHTML = `
    <div class="card"><span class="num">${data.length}</span><span class="label">Familias confirmadas</span></div>
    <div class="card"><span class="num">${totalPersonas}</span><span class="label">Total de asistentes</span></div>
  `;
}

function renderTable(data) {
  const out = document.getElementById('out');
  if (data.length === 0) {
    out.innerHTML = '<p>Todavía no hay confirmaciones.</p>';
    return;
  }
  let html = '<table><tr><th>Nombre</th><th>Acompañantes</th><th>Dedicatoria</th><th>Fecha</th><th></th></tr>';
  for (const r of data) {
    html += `<tr>
      <td>${r.nombre}</td>
      <td>${r.acompanantes}</td>
      <td>${r.dedicatoria || '-'}</td>
      <td>${new Date(r.created_at).toLocaleString('es-MX')}</td>
      <td><button class="del-btn" onclick="remove(${r.id})">Borrar</button></td>
    </tr>`;
  }
  html += '</table>';
  out.innerHTML = html;
}

async function remove(id) {
  if (!confirm('¿Borrar esta confirmación? Esta acción no se puede deshacer.')) return;
  try {
    const res = await fetch(`/api/rsvp/${id}?token=${encodeURIComponent(currentToken)}`, {
      method: 'DELETE',
    });
    if (!res.ok) { alert('No se pudo borrar (token inválido o ya no existe).'); return; }
    load();
  } catch (e) {
    alert('Error al conectar con el servidor.');
  }
}
</script>
</body>
</html>
"""