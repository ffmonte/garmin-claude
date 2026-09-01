import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from clients import strava_client, garmin_client, claude_client

app = FastAPI(title="Garmin + Claude Training Backend")

# Libera acesso de um frontend hospedado em outro domínio (ex: app do Lovable).
# Em produção, troque "*" pela URL exata do seu app pra maior segurança.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Schemas ----------

class AskBody(BaseModel):
    prompt: str


class AnalyzeBody(BaseModel):
    goal: str
    days: int = 14
    sources: list[str] = ["strava", "garmin"]
    coaching_style: str = "balanced"


class PlanBody(BaseModel):
    goal: str
    race_date: Optional[str] = None
    days_per_week: int = 4
    days: int = 28  # janela de histórico usada para calibrar o plano
    sources: list[str] = ["strava", "garmin"]
    coaching_style: str = "balanced"


class PushBody(BaseModel):
    workout: dict  # um item de "workouts" retornado por /plan


class WeeklySyncBody(BaseModel):
    goal: str
    race_date: Optional[str] = None
    days_per_week: int = 4
    days: int = 28  # janela de histórico usada para calibrar o plano
    sources: list[str] = ["strava", "garmin"]
    dry_run: bool = False  # se True, so gera o plano, nao envia pro Garmin
    coaching_style: str = "balanced"


# ---------- Helpers ----------

def _fetch_activities(days: int, sources: list[str]) -> list[dict]:
    activities = []
    if "strava" in sources:
        activities += strava_client.get_recent_activities(days)
    if "garmin" in sources:
        activities += garmin_client.get_recent_activities(days)
    activities.sort(key=lambda a: a.get("start_date") or "", reverse=True)
    return activities


# ---------- Endpoints ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/activities")
def activities(days: int = 14, sources: str = "strava,garmin"):
    src_list = [s.strip() for s in sources.split(",") if s.strip()]
    return {"activities": _fetch_activities(days, src_list)}


@app.post("/ask")
def ask(body: AskBody):
    """Endpoint simples usado pelo widget do relógio (perguntas curtas)."""
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    reply = claude_client._call_claude(
        system=(
            "Responda de forma extremamente curta (2-3 frases), pois o "
            "texto sera exibido na tela pequena de um relogio Garmin."
        ),
        user_content=body.prompt,
        max_tokens=300,
    )
    if len(reply) > 400:
        reply = reply[:399] + "…"
    return {"reply": reply}


@app.get("/coaching-styles")
def coaching_styles():
    """Lista os estilos de treino disponíveis (baseados em metodologias
    publicamente conhecidas) pra usar no campo coaching_style dos outros
    endpoints."""
    return {
        "styles": [
            {"id": key, "description": desc}
            for key, desc in claude_client.COACHING_STYLES.items()
        ]
    }


@app.post("/analyze")
def analyze(body: AnalyzeBody):
    acts = _fetch_activities(body.days, body.sources)
    if not acts:
        raise HTTPException(404, "Nenhuma atividade encontrada no periodo")
    text = claude_client.analyze_training(acts, body.goal, body.coaching_style)
    return {"analysis": text, "activities_considered": len(acts)}


@app.post("/plan")
def plan(body: PlanBody):
    acts = _fetch_activities(body.days, body.sources)
    result = claude_client.generate_plan(
        acts, body.goal, body.race_date, body.days_per_week, body.coaching_style
    )
    return result


@app.post("/push-to-garmin")
def push_to_garmin(body: PushBody):
    try:
        result = garmin_client.push_workout(body.workout)
    except AttributeError as e:
        raise HTTPException(
            500,
            "Metodo de upload nao encontrado na versao instalada da lib "
            "garminconnect. Confira o README (secao 'ajustando a lib') "
            f"para o nome correto do metodo. Detalhe: {e}",
        )
    return {"pushed": True, "result": result}


@app.post("/weekly-sync")
def weekly_sync(body: WeeklySyncBody):
    """Faz tudo de uma vez: busca historico, gera o plano da semana e
    envia cada treino pro Garmin Connect. Pensado pra ser chamado por um
    cron/GitHub Actions toda semana (ex: toda segunda de manha).

    Se um treino individual falhar ao enviar, os demais continuam sendo
    processados — o resultado final lista sucesso/erro por dia.
    """
    acts = _fetch_activities(body.days, body.sources)
    plan_result = claude_client.generate_plan(
        acts, body.goal, body.race_date, body.days_per_week, body.coaching_style
    )

    workouts = plan_result.get("workouts", [])
    push_results = []

    if not body.dry_run:
        for w in workouts:
            try:
                result = garmin_client.push_workout(w)
                push_results.append(
                    {"day": w.get("day"), "name": w.get("name"), "status": "ok", "result": result}
                )
            except Exception as e:
                push_results.append(
                    {"day": w.get("day"), "name": w.get("name"), "status": "error", "error": str(e)}
                )

    return {
        "week_summary": plan_result.get("week_summary"),
        "workouts_planned": len(workouts),
        "dry_run": body.dry_run,
        "push_results": push_results,
        "plan": plan_result,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
 
