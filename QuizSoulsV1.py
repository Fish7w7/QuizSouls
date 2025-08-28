import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import time
import random
import json
from collections import defaultdict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# CONFIGURAÇÕES BÁSICAS

URL = "https://daily-souls.netlify.app/classic/"
MAX_ATTEMPTS = 7
WAIT_SUGGESTIONS_SECS = 6
TYPE_DELAY_RANGE = (0.15, 0.30)


# ARQUIVOS

HERE = os.path.dirname(os.path.abspath(__file__))
def _load_json(fname, default=None):
    path = os.path.join(HERE, fname)
    if not os.path.exists(path):
        print(f"Arquivo não encontrado: {fname}. Usando valor padrão.")
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

boss_db = _load_json("bosses_indexed.json", default=[])
legend = _load_json("legend.json", default={
    "resistance": {},
    "weakness": {},
    "immunity": {}
})

# id -> name para as categorias numéricas
id_to_name = {
    "resistance": {int(k): v for k, v in legend.get("resistance", {}).items()},
    "weakness":   {int(k): v for k, v in legend.get("weakness", {}).items()},
    "immunity":   {int(k): v for k, v in legend.get("immunity", {}).items()},
}


# SELENIUM

options = Options()
options.add_experimental_option("detach", True)
options.add_argument("--log-level=3")
options.add_argument("--disable-logging")
options.add_experimental_option("excludeSwitches", ["enable-logging"])
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get(URL)
time.sleep(3)


# FUNÇÕES UTILITÁRIAS

def normalize_boss(b):
    """Normaliza os campos e calcula contagens usadas no jogo."""
    return {
        "slug": b.get("slug"),
        "name": b.get("name"),
        "hp": int(b.get("hp", 0)),
        "optional": 0 if b.get("optional") == "required" else 1,
        "resistance": b.get("resistance", [])[:],
        "weakness": b.get("weakness", [])[:],
        "immunity": b.get("immunity", [])[:],
        "weapons": b.get("weapons", [])[:],
        # métricas numéricas que o jogo usa
        "res_count": len(b.get("resistance", [])),
        "weak_count": len(b.get("weakness", [])),
        "imm_count": len(b.get("immunity", [])),
        "wep_count": len(b.get("weapons", [])),
    }

bosses = [normalize_boss(b) for b in boss_db]

def get_suggestions():
    try:
        return [s.text.strip() for s in driver.find_elements(By.CSS_SELECTOR, ".page-button__list li") if s.text.strip()]
    except:
        return []

def wait_for_suggestions(timeout=WAIT_SUGGESTIONS_SECS):
    start = time.time()
    while time.time() - start < timeout:
        s = get_suggestions()
        if s:
            return s
        time.sleep(0.4)
    return []

def type_and_enter(text):
    try:
        input_box = driver.find_element(By.CSS_SELECTOR, "input")
        input_box.clear()
        for ch in text:
            input_box.send_keys(ch)
            time.sleep(random.uniform(*TYPE_DELAY_RANGE))
        time.sleep(random.uniform(0.5, 1.0))
        input_box.send_keys(Keys.ENTER)
        return True
    except:
        return False

def get_feedback():
    """Le a ultima linha da tabela de feedback e interpreta os ícones."""
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, ".categories__content-row")
        if not rows:
            return None
        last_row = rows[-1]
        cells = last_row.find_elements(By.CSS_SELECTOR, ".categories__content-cell")
        raw = {
            "Boss Name": cells[1].get_attribute("class"),
            "HP": cells[2].get_attribute("class"),
            "Weapons": cells[3].get_attribute("class"),
            "Resistance": cells[4].get_attribute("class"),
            "Weakness": cells[5].get_attribute("class"),
            "Immunity": cells[6].get_attribute("class"),
            "Optional": cells[7].get_attribute("class"),
        }
        interp = {}
        for k, v in raw.items():
            if "green" in v:
                interp[k] = "✅"
            elif "yellow" in v:
                interp[k] = "⚠️"
            elif "arrow-up" in v:
                interp[k] = "⬆️"
            elif "arrow-down" in v:
                interp[k] = "⬇️"
            else:
                interp[k] = "❌"
        return interp
    except:
        return None


# REGRAS / RESTRIÇÕES 

constraints = {
    "HP": {}, "Weapons": {}, "Resistance": {},
    "Weakness": {}, "Immunity": {}, "Optional": {}
}

def add_to_list_rule(rules, key, value):
    if value is None: 
        return
    if key not in rules:
        rules[key] = []
    if value not in rules[key]:
        rules[key].append(value)

def update_constraints_from_feedback(guess_boss, feedback):
    """Atualiza restrições com base no feedback. Não elimina; apenas acumula 'pistas'."""
    # Valores observados para o palpite
    val = {
        "HP": guess_boss["hp"],
        "Weapons": guess_boss["wep_count"],
        "Resistance": guess_boss["res_count"],
        "Weakness": guess_boss["weak_count"],
        "Immunity": guess_boss["imm_count"],
        "Optional": guess_boss["optional"],
    }
    for attr, fb in feedback.items():
        if attr == "Boss Name":  # ignorado no sistema de pistas
            continue
        rules = constraints[attr]
        x = val[attr]
        if fb == "✅":
            rules["exact"] = x
        elif fb == "⬆️":
            rules["min"] = max(rules.get("min", -10**9), x + 1)
        elif fb == "⬇️":
            rules["max"] = min(rules.get("max", 10**9), x - 1)
        elif fb == "⚠️":
            # 'próximo' → registra como alvo aproximado
            rules["close"] = x
        elif fb == "❌":
            add_to_list_rule(rules, "not", x)


# SISTEMA DE SCORE

def score_numeric(value, rules, weight_exact=1.0, weight_close=0.7, weight_range=0.6, weight_penalty=0.2):

    score = 0.0
    # exato
    if "exact" in rules:
        return weight_exact if value == rules["exact"] else 0.0

    # aproximação
    if "close" in rules:
        if abs(value - rules["close"]) <= 1:
            score = max(score, weight_close)

    # faixa
    minv = rules.get("min", None)
    maxv = rules.get("max", None)
    if minv is not None or maxv is not None:
        lo = minv if minv is not None else value
        hi = maxv if maxv is not None else value
        if lo <= value <= hi:
            # bônus por estar perto do centro da faixa
            if hi > lo:
                center = (lo + hi) / 2
                dist = abs(value - center)
                maxdist = (hi - lo) / 2
                proximity = 1.0 - (dist / maxdist) if maxdist > 0 else 1.0
                score = max(score, weight_range * (0.7 + 0.3 * proximity))
            else:
                score = max(score, weight_range)

    # penalidade por valores explicitamente proibidos
    if "not" in rules and value in rules["not"]:
        score = max(score - weight_penalty, 0.0)

    return max(score, 0.05)

def score_hp(value, rules):
    
    base = score_numeric(value, rules, weight_exact=1.0, weight_close=0.8, weight_range=0.75, weight_penalty=0.25)
    return base

def score_count(value, rules):
    # campos de contagem 
    return score_numeric(value, rules, weight_exact=1.0, weight_close=0.75, weight_range=0.65, weight_penalty=0.25)

def composite_score(boss):
    """Combina os scores de cada atributo com pesos."""
    weights = {
        "HP": 3.0,
        "Weapons": 2.5,
        "Resistance": 2.0,
        "Weakness": 2.4,
        "Immunity": 2.2,
        "Optional": 1.2,
    }
    parts = {}
    parts["HP"] = score_hp(boss["hp"], constraints["HP"])
    parts["Weapons"] = score_count(boss["wep_count"], constraints["Weapons"])
    parts["Resistance"] = score_count(boss["res_count"], constraints["Resistance"])
    parts["Weakness"] = score_count(boss["weak_count"], constraints["Weakness"])
    parts["Immunity"] = score_count(boss["imm_count"], constraints["Immunity"])
    parts["Optional"] = score_count(boss["optional"], constraints["Optional"])

    total = sum(parts[k] * weights[k] for k in parts)
    
    if constraints["Immunity"].get("exact") == 0 and boss["imm_count"] == 0:
        total *= 1.05
    
    if constraints["Weapons"].get("exact") == 0 and boss["wep_count"] == 0:
        total *= 1.05
    return total, parts

def rank_bosses(bosses_list):
    scored = []
    for b in bosses_list:
        s, parts = composite_score(b)
        scored.append((s, b, parts))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# LÓGICA DE PALPITES

def pick_best_from_suggestions(suggestions, tried_names):
    """Escolhe o melhor boss (maior score) entre as sugestões ainda não tentadas."""
    pool = [b for b in bosses if b["name"] in suggestions and b["name"] not in tried_names]
    if not pool:
        pool = [b for b in bosses if b["name"] in suggestions]
    ranked = rank_bosses(pool)
    return ranked[0][1]["name"] if ranked else random.choice(suggestions)

def print_feedback(feedback):
    print(" Feedback:")
    for k, v in feedback.items():
        print(f"  {k}: {v}")

def pretty_constraints(cdict):
    # deixa o print das restrições mais legível
    compact = {}
    for k, v in cdict.items():
        vv = {}
        for rk, rv in v.items():
            if isinstance(rv, list):
                vv[rk] = list(rv)
            else:
                vv[rk] = rv
        compact[k] = vv
    return compact


# LOOP PRINCIPAL

letters = list("abcdefghijklmnopqrstuvwxyz")
random.shuffle(letters)
used_letters = set()
tried_names = set()

for attempt in range(1, MAX_ATTEMPTS + 1):
    available_letters = [l for l in letters if l not in used_letters]
    if not available_letters:
        break
    letter = random.choice(available_letters)
    used_letters.add(letter)

    try:
        input_box = driver.find_element(By.CSS_SELECTOR, "input")
        input_box.clear()
        input_box.send_keys(letter)
    except:
        pass

    suggestions = wait_for_suggestions(timeout=WAIT_SUGGESTIONS_SECS)
    print(f"\n📌 Sugestões encontradas: {suggestions}")
    print(f"🔎 Tentativa {attempt}/{MAX_ATTEMPTS}")

    if not suggestions:
        continue

    chosen = pick_best_from_suggestions(suggestions, tried_names)
    tried_names.add(chosen)

    if not type_and_enter(chosen):
        print("Input desativado. Provavelmente o jogo acabou.")
        break

    print(f"\n🎯 Palpite enviado: {chosen}")
    time.sleep(random.uniform(2.2, 3.6))

    feedback = get_feedback()
    if not feedback:
        continue

    print_feedback(feedback)

    # atualiza pistas
    guessed_boss = next((b for b in bosses if b["name"] == chosen), None)
    if guessed_boss:
        update_constraints_from_feedback(guessed_boss, feedback)

    # terminou
    if all(v == "✅" for v in feedback.values()):
        print(f"\n🔥 Boss encontrado: {chosen}")
        break

    # Log de restrições (para acompanhar raciocínio)
    print(f"📚 Restrições acumuladas: {pretty_constraints(constraints)}")


# RANKING FINAL

print("\n🏁 Fim do script. Calculando ranking final por probabilidade…")

final_ranking = rank_bosses(bosses)
top5 = final_ranking[:5]

if top5:
    best = top5[0]
    best_score, best_boss, parts = best
    print(f"\n🏆 Melhor candidato provável: {best_boss['name']}  (score: {best_score:.2f})")
    print("   Detalhe dos componentes do score:")
    for k, v in parts.items():
        print(f"   - {k}: {v:.3f}")

    print("\n📊 Top 5 candidatos:")
    for i, (score, b, p) in enumerate(top5, start=1):
        print(f"  {i}. {b['name']} — score {score:.2f} | HP={b['hp']} | Wep={b['wep_count']} | Res={b['res_count']} | Weak={b['weak_count']} | Imm={b['imm_count']} | Opt={b['optional']}")

else:
    print("Nenhum boss para ranquear.")
