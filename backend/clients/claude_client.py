import os
import json
import requests

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-5"


# Metodologias de treino publicamente conhecidas, descritas em termos de
# PRINCIPIOS (nao sao citacoes nem planos copiados de ninguem) — servem
# como direcionamento de estilo pro Claude ao gerar analise/plano.
COACHING_STYLES = {
    "balanced": (
        "Abordagem equilibrada e generalista, sem seguir uma metodologia "
        "especifica: mistura volume moderado, algum trabalho de qualidade "
        "e progressao gradual segura."
    ),
    "daniels": (
        "Estilo Jack Daniels (VDOT): prescreva ritmos em zonas fisiologicas "
        "bem definidas — Easy (E), Marathon (M), Threshold (T), Interval (I) "
        "e Repetition (R) — calculadas a partir do nivel atual do atleta "
        "(estimado pelos ritmos/FC do historico). Priorize qualidade sobre "
        "quantidade: cada treino de qualidade tem um proposito fisiologico "
        "claro (limiar de lactato, VO2max, economia de corrida). Volume "
        "moderado, foco em execucao precisa dos ritmos."
    ),
    "lydiard": (
        "Estilo Arthur Lydiard: priorize construir uma base aerobica solida "
        "e prolongada (semanas de volume alto em ritmo facil/moderado, "
        "predominantemente abaixo do limiar) antes de introduzir qualquer "
        "trabalho anaerobico. So depois da base vem uma fase curta de "
        "treino de morro (forca) e, por ultimo, uma fase breve e afiada de "
        "velocidade/anaerobico proxima a competicao. Evite intervalados "
        "intensos cedo demais no plano."
    ),
    "canova": (
        "Estilo Renato Canova (treino especifico para maratona/fundo): "
        "volume alto com blocos de trabalho 'especifico' que se aproximam "
        "progressivamente do ritmo e duracao da prova-alvo ao longo das "
        "semanas. Menos foco em VO2max isolado, mais foco em resistencia "
        "especifica ao ritmo de prova (ex: longos parciais no ritmo alvo, "
        "trabalho de 'special blocks' combinando ritmo de limiar com ritmo "
        "de prova). Assume atleta com boa base ja construida."
    ),
    "pfitzinger": (
        "Estilo Pete Pfitzinger: volume medio-alto com enfase forte em "
        "treinos de limiar de lactato (tempo runs, cruise intervals) "
        "distribuidos regularmente ao longo da semana, complementados por "
        "longos progressivos (terminando mais rapido do que comecam). "
        "Estrutura previsivel e consistente semana a semana."
    ),
    "higdon": (
        "Estilo Hal Higdon: abordagem acessivel e conservadora, priorizando "
        "completar o objetivo com seguranca e sem lesao antes de buscar "
        "performance maxima. Progressao de volume suave, dias de descanso "
        "ou cross-training regulares, ritmos confortaveis na maioria dos "
        "treinos, pouco ou nenhum trabalho de alta intensidade para "
        "iniciantes/intermediarios."
    ),
}

DEFAULT_STYLE = "balanced"


def _style_instructions(coaching_style: str) -> str:
    style = COACHING_STYLES.get(coaching_style, COACHING_STYLES[DEFAULT_STYLE])
    return f"\n\nESTILO DE TREINO A SEGUIR:\n{style}"


def _call_claude(system: str, user_content: str, max_tokens: int = 1024) -> str:
    resp = requests.post(
        _API_URL,
        headers={
            "content-type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": _MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text_block = next((b for b in data["content"] if b["type"] == "text"), None)
    return text_block["text"] if text_block else ""


def analyze_training(
    activities: list[dict], goal: str, coaching_style: str = DEFAULT_STYLE
) -> str:
    """Analisa os treinos recentes em texto curto e direto (pro relógio
    ou pro app), considerando o objetivo do atleta e o estilo de treino
    escolhido."""
    system = (
        "Você é um treinador experiente analisando dados de treino. "
        "Seja objetivo, cite números concretos (FC, ritmo, volume, carga), "
        "aponte 1-2 pontos de atenção (excesso/falta de volume, fadiga, etc.) "
        "e termine com uma recomendação prática. Máximo 6-8 frases."
        + _style_instructions(coaching_style)
    )
    user_content = (
        f"Objetivo do atleta: {goal}\n\n"
        f"Atividades recentes (JSON):\n{json.dumps(activities, ensure_ascii=False, indent=2)}"
    )
    return _call_claude(system, user_content, max_tokens=500)


def generate_plan(
    activities: list[dict],
    goal: str,
    race_date: str | None,
    days_per_week: int,
    coaching_style: str = DEFAULT_STYLE,
) -> dict:
    """Gera um plano de treino estruturado para a próxima semana, em JSON,
    pronto para ser convertido em workouts do Garmin, seguindo o estilo de
    treino escolhido.

    Formato de retorno esperado:
    {
      "week_summary": "...",
      "workouts": [
        {
          "day": "segunda",
          "name": "Rodagem leve",
          "sport": "running",
          "steps": [
            {"type": "warmup", "duration_min": 10},
            {"type": "interval", "repeat": 1, "duration_min": 30, "target_pace_min_km": 5.5},
            {"type": "cooldown", "duration_min": 5}
          ]
        }
      ]
    }
    """
    system = (
        "Você é um treinador de corrida/ciclismo experiente. Gere um plano de "
        "treino para os próximos 7 dias, baseado no histórico e objetivo do "
        "atleta. Responda APENAS com um JSON válido, sem markdown, sem texto "
        "explicativo antes ou depois, seguindo exatamente este schema:\n\n"
        '{"week_summary": string, "workouts": [{"day": string, "name": string, '
        '"sport": "running"|"cycling"|"swimming", "steps": [{"type": '
        '"warmup"|"interval"|"recovery"|"cooldown", "duration_min": number, '
        '"repeat": number (opcional, so pra type=interval), '
        '"target_pace_min_km": number (opcional), '
        '"recovery_min": number (opcional, so pra type=interval)}]}]}\n\n'
        f"O atleta treina {days_per_week}x por semana. Distribua os dias de "
        "descanso adequadamente."
        + _style_instructions(coaching_style)
    )
    user_content = (
        f"Objetivo: {goal}\n"
        f"Data da prova (se houver): {race_date or 'nao informada'}\n\n"
        f"Historico recente de treinos (JSON):\n"
        f"{json.dumps(activities, ensure_ascii=False, indent=2)}"
    )

    raw = _call_claude(system, user_content, max_tokens=2000)

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    return json.loads(cleaned)
