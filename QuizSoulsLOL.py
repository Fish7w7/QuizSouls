# -*- coding: utf-8 -*-
"""
Requisitos:
    pip install dearpygui webdriver-manager selenium
Autor: Fish7w7
"""

import os
import json
import math
import time

import random
from typing import List, Dict, Any, Tuple, Optional

#  Tentativa de import Selenium 
SELENIUM_OK = True
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
except Exception:
    SELENIUM_OK = False

#  DearPyGui
from dearpygui import dearpygui as dpg

# Utilidades / Dados


def log(ui, msg: str):
    """Escreve no log da GUI (sem prints)."""
    prev = dpg.get_value(ui["log"])
    if prev:
        dpg.set_value(ui["log"], prev + "\n" + msg)
    else:
        dpg.set_value(ui["log"], msg)
    # Scroll para o fim
    dpg.set_y_scroll(ui["log_child"], 1e9)


def load_bosses() -> List[Dict[str, Any]]:
    """
    Carrega bosses de 'bosses_indexed.json' ou de 'bosses.json'.
    """
    filename = None
    if os.path.exists("bosses_indexed.json"):
        filename = "bosses_indexed.json"
    elif os.path.exists("bosses.json"):
        filename = "bosses.json"

    if not filename:
        # retorna dataset mínimo para não travar
        return [
            {"name": "Exemplo Boss 1", "hp": 1000, "weapons": ["Sword"], "resistance": ["Fire"], "weakness": ["Ice"], "immunity": [], "optional": "required", "slug": "exemplo1"},
            {"name": "Exemplo Boss 2", "hp": 1500, "weapons": [], "resistance": [], "weakness": ["Lightning"], "immunity": ["Poison"], "optional": "optional", "slug": "exemplo2"},
            {"name": "Exemplo Boss 3", "hp": 800, "weapons": ["Magic"], "resistance": ["Ice", "Fire"], "weakness": [], "immunity": ["Death"], "optional": "required", "slug": "exemplo3"}
        ]

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        bosses = list(data.values())
    elif isinstance(data, list):
        bosses = data
    else:
        bosses = []

    # normalização
    for b in bosses:
        b.setdefault("slug", "")
        b.setdefault("name", b.get("boss", b.get("slug", "Unknown")))
        b.setdefault("hp", 0)
        b.setdefault("optional", "required")
        b.setdefault("resistance", [])
        b.setdefault("weakness", [])
        b.setdefault("immunity", [])
        b.setdefault("weapons", [])
    return bosses

# Restrições e Ranking

def optional_to_int(opt_str: str) -> int:
    # no dataset: "required" ou "optional"
    return 1 if str(opt_str).lower() == "optional" else 0


def score_hp(boss_hp: int, hp_min: Optional[int], hp_max: Optional[int]) -> float:

    if hp_min is not None and hp_max is not None and hp_min <= hp_max:
        # centro da faixa
        center = (hp_min + hp_max) / 2.0
        half = max((hp_max - hp_min) / 2.0, 1.0)
        # gauss em torno do centro
        z = (boss_hp - center) / (half)
        s = math.exp(-(z ** 2))
        return float(s)

    if hp_min is not None and (hp_max is None):
        if boss_hp >= hp_min:
            return 1.0
        # abaixo do mínimo → penaliza
        gap = hp_min - boss_hp
        return float(math.exp(- (gap / 500.0) ** 2))

    if hp_max is not None and (hp_min is None):
        if boss_hp <= hp_max:
            return 1.0
        # acima do máximo → penaliza
        gap = boss_hp - hp_max
        return float(math.exp(- (gap / 500.0) ** 2))

    return 0.5


def score_count_exact(count_value: int, exact: Optional[int], not_list: List[int], close_target: Optional[int]) -> float:

    s_exact = 1.0 if (exact is not None and count_value == exact) else (0.0 if exact is not None else 0.5)
    s_not = 0.0 if (count_value in (not_list or [])) else 1.0
    if close_target is not None:
        z = (count_value - close_target) / 1.5
        s_close = float(math.exp(-(z ** 2)))
    else:
        s_close = 0.5

    # pesos razoáveis
    w_exact, w_not, w_close = 0.45, 0.25, 0.30
    return float(w_exact * s_exact + w_not * s_not + w_close * s_close)


def build_restrictions_state() -> Dict[str, Any]:
    return {
        "HP": {"min": None, "max": None},
        "Weapons": {"exact": None},
        "Resistance": {"exact": None, "not": [], "close": None},
        "Weakness": {"exact": None, "not": [], "close": None},
        "Immunity": {"exact": None, "not": [], "close": None},
        "Optional": {"exact": None}  # 0 required, 1 optional
    }


def apply_feedback_to_restrictions(restr: Dict[str, Any],
                                   feedback: Dict[str, str],
                                   guess_boss: Dict[str, Any]):
    """
    Atualiza restrições com base no feedback textual por atributo.
    feedback: { "HP": "MAIOR/MENOR/IGUAL", "Weapons": "IGUAL/DIFERENTE", ... }
    guess_boss: boss chutado (para saber contagens)
    """
    # HP
    hp_symbol = feedback.get("HP")
    if hp_symbol == "MAIOR":
        # alvo tem HP > guess
        g = guess_boss["hp"]
        old = restr["HP"].get("min")
        restr["HP"]["min"] = max(old, g + 1) if old is not None else g + 1
    elif hp_symbol == "MENOR":
        g = guess_boss["hp"]
        old = restr["HP"].get("max")
        restr["HP"]["max"] = min(old, g - 1) if old is not None else g - 1
    elif hp_symbol == "IGUAL":
        # igual → faixa fica travada naquele HP
        g = guess_boss["hp"]
        restr["HP"]["min"] = g
        restr["HP"]["max"] = g

    # Weapons (usa EXATAMENTE a contagem)
    wep_symbol = feedback.get("Weapons")
    g_wep = len(guess_boss.get("weapons", []))
    if wep_symbol == "IGUAL":
        restr["Weapons"]["exact"] = g_wep
    elif wep_symbol == "DIFERENTE":
        if g_wep == 0:
            restr["Weapons"]["exact"] = None
        else:
            restr["Weapons"]["exact"] = 0  

    # Resistance / Weakness / Immunity recebem 'close' (tamanho da lista) e 'not' (proibições)
    for key in ["Resistance", "Weakness", "Immunity"]:
        sym = feedback.get(key)
        g_count = len(guess_boss.get(key.lower(), []))
        if sym == "IGUAL":
            restr[key]["exact"] = g_count
        elif sym == "PERTO":
            restr[key]["close"] = g_count
        elif sym == "DIFERENTE":
            not_list = set(restr[key].get("not") or [])
            not_list.add(g_count)
            restr[key]["not"] = list(sorted(not_list))

    # Optional (obrigatoriedade)
    opt_symbol = feedback.get("Optional")
    g_opt = 1 if str(guess_boss.get("optional", "")).lower() == "optional" else 0
    if opt_symbol == "IGUAL":
        restr["Optional"]["exact"] = g_opt
    elif opt_symbol == "DIFERENTE":
        restr["Optional"]["exact"] = 1 - g_opt


def score_boss(boss: Dict[str, Any], r: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """
    Calcula score total e quebra por componente para um boss.
    Retorna (score_total, breakdown).
    """
    # HP
    s_hp = score_hp(boss["hp"], r["HP"]["min"], r["HP"]["max"])
    # Weapons
    s_wep = score_count_exact(len(boss["weapons"]), r["Weapons"]["exact"], [], None)

    # Resistance / Weakness / Immunity
    s_res = score_count_exact(len(boss["resistance"]), r["Resistance"]["exact"], r["Resistance"]["not"], r["Resistance"]["close"])
    s_weak = score_count_exact(len(boss["weakness"]), r["Weakness"]["exact"], r["Weakness"]["not"], r["Weakness"]["close"])
    s_imm = score_count_exact(len(boss["immunity"]), r["Immunity"]["exact"], r["Immunity"]["not"], r["Immunity"]["close"])

    # Optional
    opt_exact = r["Optional"]["exact"]
    opt_val = optional_to_int(boss.get("optional", "required"))
    s_opt = 1.0 if (opt_exact is None) else (1.0 if opt_exact == opt_val else 0.0)

    # Pesos
    w_hp, w_wep, w_res, w_weak, w_imm, w_opt = 0.28, 0.16, 0.14, 0.18, 0.16, 0.08
    total = (w_hp * s_hp + w_wep * s_wep + w_res * s_res +
             w_weak * s_weak + w_imm * s_imm + w_opt * s_opt)
    scaled = total * 15.0
    breakdown = {
        "HP": s_hp,
        "Weapons": s_wep,
        "Resistance": s_res,
        "Weakness": s_weak,
        "Immunity": s_imm,
        "Optional": s_opt
    }
    return (scaled, breakdown)


def rank_bosses(bosses: List[Dict[str, Any]],
                restrictions: Dict[str, Any],
                suggestions_whitelist: Optional[List[str]] = None) -> List[Tuple[Dict[str, Any], float, Dict[str, float]]]:
    """
    Gera ranking (lista ordenada decrescente) de (boss, score, breakdown).
    Se suggestions_whitelist for fornecida: filtra candidatos por nome contido nessa lista.
    """
    items = []
    for b in bosses:
        if suggestions_whitelist:
            if b["name"] not in suggestions_whitelist:
                continue
        sc, bd = score_boss(b, restrictions)
        items.append((b, sc, bd))
    items.sort(key=lambda x: x[1], reverse=True)
    return items


# Selenium Helpers 

class SuggestionScraper:
    def __init__(self, url: str, sel_suggestions: str, sel_input: str, sel_submit: str, headless: bool = True):
        self.enabled = SELENIUM_OK
        self.driver = None
        self.url = url
        self.sel_suggestions = sel_suggestions
        self.sel_input = sel_input
        self.sel_submit = sel_submit
        self.headless = headless

    def start(self) -> bool:
        if not self.enabled:
            return False
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.get(self.url)
            return True
        except Exception:
            self.driver = None
            return False

    def stop(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None

    def get_suggestions(self) -> List[str]:
        if not self.driver:
            return []
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, self.sel_suggestions)
            names = [e.text.strip() for e in els if e.text.strip()]
            return names
        except Exception:
            return []

    def send_guess(self, guess: str) -> bool:
        if not self.driver:
            return False
        try:
            # Espera mais tempo e tenta diferentes estratégias
            wait = WebDriverWait(self.driver, 15)
            
            # Tenta encontrar o campo de input com diferentes seletores
            input_selectors = [
                self.sel_input,
                "input[type='text']",
                "input",
                "[data-testid='guess-input']",
                "#guess-input",
                ".guess-input"
            ]
            
            inp = None
            for selector in input_selectors:
                try:
                    inp = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not inp:
                return False
                
            # Limpa e digita o palpite
            inp.clear()
            time.sleep(0.5)  # Pequena pausa
            inp.send_keys(guess)
            time.sleep(0.5)
            
            # Tenta enviar
            if self.sel_submit:
                # Tenta diferentes seletores para o botão
                button_selectors = [
                    self.sel_submit,
                    "button[type='submit']",
                    "button",
                    "[data-testid='submit-button']",
                    ".submit-button"
                ]
                
                for selector in button_selectors:
                    try:
                        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                        btn.click()
                        return True
                    except TimeoutException:
                        continue
            else:
                # Tenta Enter
                inp.send_keys(Keys.ENTER)
                return True
                
            return False
            
        except Exception as e:
            # Para debug
            print(f"Erro no send_guess: {e}")
            return False

    def get_feedback_from_site(self) -> Dict[str, str]:
        """
        Captura o feedback automaticamente do site baseado nas classes CSS.
        Retorna um dicionário com o feedback para cada atributo.
        
        A ordem dos elementos é: NAME, HP, WEAPONS, RESISTANCES, WEAKNESSES, IMMUNITIES, OPTIONAL
        """
        if not self.driver:
            return {}
        
        try:
            feedback = {}
            
            # Aguarda um pouco para garantir que a página atualizou após o palpite
            time.sleep(1) 
            
            # Tenta diferentes seletores para encontrar as células
            possible_selectors = [
                "div.categories_content-cell",
                ".categories_content-cell",
                "div[class*='categories_content-cell']",
                "div[class*='content-cell']",
                ".content-cell",
                "div[class*='cell']"
            ]
            
            cells = []
            for selector in possible_selectors:
                try:
                    cells = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if len(cells) >= 7: 
                        print(f"Células encontradas com seletor: {selector} ({len(cells)} células)")
                        break
                except:
                    continue
            
            if len(cells) < 7:  
                print(f"células Insuficientes: {len(cells)} (precisa de pelo menos 7)")
                return {}
            
            # Mapeia as células para os atributos
            attribute_mapping = [
                "NAME",        # índice 0 - ignora
                "HP",          # índice 1
                "Weapons",     # índice 2
                "Resistance",  # índice 3
                "Weakness",    # índice 4
                "Immunity",    # índice 5
                "Optional"     # índice 6
            ]
            
            print(f"Processando {len(cells)} células encontradas:")
            
            for i, cell in enumerate(cells[:7]):  # Pega apenas as primeiras 7 células
                classes = cell.get_attribute("class") or ""
                text = cell.text.strip()
                print(f"Célula {i}: classes='{classes}' texto='{text}'")
                
                if i == 0:  # Pula NAME
                    continue
                    
                if i >= len(attribute_mapping):
                    break
                    
                attr = attribute_mapping[i]
                
                if attr == "HP":
                    # HP tem lógica especial para as setas 
                    if "green" in classes:
                        feedback[attr] = "IGUAL"
                    elif "red" in classes:
                        if "arrow-up" in classes:
                            feedback[attr] = "MAIOR"
                        elif "arrow-down" in classes:
                            feedback[attr] = "MENOR" 
                        else:
                            feedback[attr] = "DIFERENTE"  # red sem seta
                    else:
                        feedback[attr] = "—"
                else:
                    # Para outros atributos
                    if "green" in classes:
                        feedback[attr] = "IGUAL"
                    elif "orange" in classes:
                        feedback[attr] = "PERTO"
                    elif "red" in classes:
                        feedback[attr] = "DIFERENTE"
                    else:
                        feedback[attr] = "—"
            
            print(f"Feedback capturado: {feedback}")
            return feedback
            
        except Exception as e:
            print(f"Erro ao capturar feedback: {e}")
            import traceback
            traceback.print_exc()
            return {}



# DearPyGui App


class App:
    def __init__(self):
        self.bosses = load_bosses()
        self.filtered_bosses = self.bosses.copy()  
        self.restrictions = build_restrictions_state()
        self.current_ranking = []  
        self.attempt = 0
        self.max_attempts = 7

        # selenium 
        self.scraper: Optional[SuggestionScraper] = None

        # DearPyGui IDs
        self.ui = {}

    #  GUI Helpers 
    def _update_attempt_counter(self):
        """Atualiza o contador de tentativas na interface."""
        dpg.set_value(self.ui["attempt_counter"], f"Tentativas: {self.attempt}/{self.max_attempts}")

    def _refresh_top_table(self):
        """Atualiza a tabela do top 10."""
        # Limpa linhas antigas
        rows = dpg.get_item_children(self.ui["table_top"])[1]
        for r in rows:
            dpg.delete_item(r)

        top = self.current_ranking[:10]
        for idx, (b, sc, bd) in enumerate(top, start=1):
            row = dpg.add_table_row(parent=self.ui["table_top"])
            dpg.add_text(str(idx), parent=row)
            dpg.add_text(b["name"], parent=row)
            dpg.add_text(f"{sc:.2f}", parent=row)
            # Barra de progresso para o score
            dpg.add_progress_bar(default_value=sc/15.0, width=80, parent=row)
            dpg.add_text(str(b["hp"]), parent=row)
            dpg.add_text(str(len(b["weapons"])), parent=row)
            dpg.add_text(str(len(b["resistance"])), parent=row)
            dpg.add_text(str(len(b["weakness"])), parent=row)
            dpg.add_text(str(len(b["immunity"])), parent=row)
            dpg.add_text("optional" if optional_to_int(b["optional"]) == 1 else "required", parent=row)

        if self.current_ranking:
            b, sc, bd = self.current_ranking[0]
            dpg.set_value(self.ui["best_title"], f" Melhor candidato provável: {b['name']} (score {sc:.2f})")
            detail = (f"HP: {bd['HP']:.3f} | "
                     f"Weapons: {bd['Weapons']:.3f} | "
                     f"Resistance: {bd['Resistance']:.3f}\n"
                     f"Weakness: {bd['Weakness']:.3f} | "
                     f"Immunity: {bd['Immunity']:.3f} | "
                     f"Optional: {bd['Optional']:.3f}")
            dpg.set_value(self.ui["best_breakdown"], detail)
            
            # Atualizar barras de score individuais
            dpg.set_value(self.ui["bar_hp"], bd['HP'])
            dpg.set_value(self.ui["bar_weapons"], bd['Weapons'])
            dpg.set_value(self.ui["bar_resistance"], bd['Resistance'])
            dpg.set_value(self.ui["bar_weakness"], bd['Weakness'])
            dpg.set_value(self.ui["bar_immunity"], bd['Immunity'])
            dpg.set_value(self.ui["bar_optional"], bd['Optional'])
        else:
            dpg.set_value(self.ui["best_title"], " Melhor candidato provável: —")
            dpg.set_value(self.ui["best_breakdown"], "")
            # Reset barras
            for bar in ["bar_hp", "bar_weapons", "bar_resistance", "bar_weakness", "bar_immunity", "bar_optional"]:
                dpg.set_value(self.ui[bar], 0.0)

    def _refresh_restrictions_panel(self):
        """Atualiza o painel de restrições."""
        r = self.restrictions
        text = []
        text.append(f"HP: min={r['HP']['min']}, max={r['HP']['max']}")        
        text.append(f"Weapons: exact={r['Weapons']['exact']}")        
        for k in ["Resistance", "Weakness", "Immunity"]:
            x = r[k]
            text.append(f"{k}: exact={x['exact']} | close={x['close']} | not={x['not']}")
        opt = r["Optional"]["exact"]
        opt_text = "N/A" if opt is None else ("required" if opt == 0 else "optional")
        text.append(f"Optional: {opt_text}")

        dpg.set_value(self.ui["restr_text"], "\n".join(text))

    def _filter_bosses(self, sender, app_data, user_data):
        """Filtro de busca manual."""
        search_text = dpg.get_value(self.ui["search_input"]).lower()
        if not search_text:
            self.filtered_bosses = self.bosses.copy()
        else:
            self.filtered_bosses = [b for b in self.bosses if search_text in b["name"].lower()]
        
        # Atualiza a tabela de bosses filtrados
        self._refresh_filtered_table()

    def _refresh_filtered_table(self):
        """Atualiza tabela com bosses filtrados."""
        rows = dpg.get_item_children(self.ui["table_filtered"])[1]
        for r in rows:
            dpg.delete_item(r)

        # Mostra apenas os primeiros 20 para não sobrecarregar
        for b in self.filtered_bosses[:20]:
            row = dpg.add_table_row(parent=self.ui["table_filtered"])
            dpg.add_text(b["name"], parent=row)
            dpg.add_text(str(b["hp"]), parent=row)
            dpg.add_text(str(len(b["weapons"])), parent=row)
            dpg.add_text(str(len(b["resistance"])), parent=row)
            dpg.add_text(str(len(b["weakness"])), parent=row)
            dpg.add_text(str(len(b["immunity"])), parent=row)
            dpg.add_text("optional" if optional_to_int(b["optional"]) == 1 else "required", parent=row)

    def _recompute_ranking(self, suggestions: Optional[List[str]] = None):
        """Recomputa o ranking e atualiza a GUI."""
        self.current_ranking = rank_bosses(self.bosses, self.restrictions, suggestions_whitelist=suggestions)
        self._refresh_top_table()

    #  Callbacks 
    def cb_start_automation(self):
        """Callback para iniciar automação."""
        self.start_automation()

    def cb_stop_automation(self):
        """Callback para parar automação."""
        self.stop_automation()

    def cb_do_attempt(self):
        """Callback para fazer uma tentativa."""
        self.do_attempt()

    def cb_apply_feedback(self):
        """Callback para aplicar feedback."""
        self.apply_feedback_and_update()

    def cb_auto_feedback(self):
        """Callback para captura automática de feedback."""
        self.auto_capture_feedback()

    def cb_reset_quiz(self):
        """Callback para resetar o quiz."""
        self.reset_quiz()

    #  Fluxo 
    def start_automation(self):
        """Inicia a automação."""
        self.attempt = 0
        self.restrictions = build_restrictions_state()
        dpg.set_value(self.ui["log"], "")
        log(self.ui, " Bot iniciado")

        use_selenium = dpg.get_value(self.ui["cb_use_selenium"])
        suggestions = None
        
        if use_selenium and SELENIUM_OK:
            url = dpg.get_value(self.ui["inp_url"])
            sel_sug = dpg.get_value(self.ui["inp_sel_sug"])
            sel_inp = dpg.get_value(self.ui["inp_sel_input"])
            sel_btn = dpg.get_value(self.ui["inp_sel_submit"])
            headless = dpg.get_value(self.ui["cb_headless"])
            
            self.scraper = SuggestionScraper(url, sel_sug, sel_inp, sel_btn, headless=headless)
            ok = self.scraper.start()
            
            if ok:
                log(self.ui, " Selenium ON: sessão iniciada")
                suggestions = self.scraper.get_suggestions()
                if suggestions:
                    log(self.ui, f" Sugestões encontradas: {suggestions}")
                else:
                    log(self.ui, " Sem sugestões (usando todos os bosses)")
            else:
                log(self.ui, " Selenium falhou — seguindo sem ele")
                self.scraper = None
        else:
            if use_selenium and not SELENIUM_OK:
                log(self.ui, " Selenium não disponível neste ambiente.")
            self.scraper = None

        # Ranking inicial
        self._recompute_ranking(suggestions)
        self._refresh_restrictions_panel()
        self._update_attempt_counter()

        # Controles da interface 
        dpg.enable_item(self.ui["btn_attempt"])
        dpg.enable_item(self.ui["btn_apply_feedback"])
        dpg.enable_item(self.ui["btn_auto_feedback"])
        dpg.enable_item(self.ui["btn_stop"])
        dpg.enable_item(self.ui["btn_reset"])
        dpg.disable_item(self.ui["btn_start"])

    def stop_automation(self):
        """Para a automação."""
        if self.scraper:
            self.scraper.stop()
            self.scraper = None
        log(self.ui, " Bot parado")
        
        # Controles da interface 
        dpg.disable_item(self.ui["btn_attempt"])
        dpg.disable_item(self.ui["btn_apply_feedback"])
        dpg.disable_item(self.ui["btn_auto_feedback"])
        dpg.disable_item(self.ui["btn_stop"])
        dpg.disable_item(self.ui["btn_reset"])
        dpg.enable_item(self.ui["btn_start"])

    def reset_quiz(self):
        """Reseta o quiz completamente."""
        self.attempt = 0
        self.restrictions = build_restrictions_state()
        self.current_ranking = []
        
        # Atualiza contador
        self._update_attempt_counter()
        
        # Limpar feedback
        feedback_controls = ["fb_hp", "fb_wep", "fb_res", "fb_weak", "fb_imm", "fb_opt"]
        for control in feedback_controls:
            dpg.set_value(self.ui[control], "—")
        
        # Limpar último palpite
        dpg.set_value(self.ui["last_guess"], "")
        
        # Limpar log
        dpg.set_value(self.ui["log"], "")
        
        log(self.ui, " Quiz resetado")  
        # Sempre recomputa o ranking após reset
        self._recompute_ranking()
        self._refresh_restrictions_panel()

    def do_attempt(self):
        """Executa uma tentativa."""
        if self.attempt >= self.max_attempts:
            log(self.ui, " Limite de tentativas alcançado.")
            return
        if not self.current_ranking:
            log(self.ui, " Sem candidatos no ranking atual.")
            return

        self.attempt += 1
        top_boss, top_score, _ = self.current_ranking[0]

        # Atualiza contador
        self._update_attempt_counter()

        log(self.ui, f" Tentativa {self.attempt}/{self.max_attempts}")
        log(self.ui, f" Palpite escolhido: {top_boss['name']} (Score: {top_score:.2f})")

        # Se selenium ativo, envia palpite
        if self.scraper:
            ok = self.scraper.send_guess(top_boss["name"])
            if ok:
                log(self.ui, " Palpite enviado ao site (aguardando feedback).")
            else:
                log(self.ui, " Falha ao enviar palpite ao site (forneça feedback manual).")

        guess_info = (f" {top_boss['name']}\n"
                     f"HP: {top_boss['hp']} | Weapons: {len(top_boss['weapons'])} | "
                     f"Res: {len(top_boss['resistance'])} | Weak: {len(top_boss['weakness'])}\n"
                     f"Imm: {len(top_boss['immunity'])} | "
                     f"Type: {'optional' if optional_to_int(top_boss['optional']) else 'required'}")
        dpg.set_value(self.ui["last_guess"], guess_info)

    def auto_capture_feedback(self):
        """
        Captura feedback automaticamente e aplica às restrições.
        """
        if not self.scraper:
            log(self.ui, " Selenium nao esta ativo para captura automatica.")
            return False
        
        if not self.current_ranking:
            log(self.ui, " Nenhum ranking atual para aplicar feedback.")
            return False
        
        # Captura feedback do site
        feedback = self.scraper.get_feedback_from_site()
        
        if not feedback:
            log(self.ui, " Nao foi possivel capturar feedback do site.")
            return False
        
        # Atualiza os controles da interface com o feedback capturado
        feedback_mapping = {
            "HP": self.ui["fb_hp"],
            "Weapons": self.ui["fb_wep"], 
            "Resistance": self.ui["fb_res"],
            "Weakness": self.ui["fb_weak"],
            "Immunity": self.ui["fb_imm"],
            "Optional": self.ui["fb_opt"]
        }
        
        for attr, control in feedback_mapping.items():
            if attr in feedback:
                dpg.set_value(control, feedback[attr])
        
        # Log do feedback capturado
        log(self.ui, " Feedback capturado automaticamente:")
        for attr, value in feedback.items():
            if value != "—":
                log(self.ui, f"   {attr}: {value}")
        
        # Aplica o feedback normalmente
        self.apply_feedback_and_update()
        
        return True

    def apply_feedback_and_update(self):
        """Aplica feedback e atualiza ranking."""
        if not self.current_ranking:
            log(self.ui, " Nenhum ranking atual para aplicar feedback.")
            return

        guess_boss = self.current_ranking[0][0]

        # Mapear feedback em texto para símbolos internos 
        feedback_mapping = {
            "HP": {"MAIOR": "MAIOR", "MENOR": "MENOR", "IGUAL": "IGUAL", "—": "—"},
            "Weapons": {"IGUAL": "IGUAL", "DIFERENTE": "DIFERENTE", "—": "—"},
            "Resistance": {"IGUAL": "IGUAL", "PERTO": "PERTO", "DIFERENTE": "DIFERENTE", "—": "—"},
            "Weakness": {"IGUAL": "IGUAL", "PERTO": "PERTO", "DIFERENTE": "DIFERENTE", "—": "—"},
            "Immunity": {"IGUAL": "IGUAL", "PERTO": "PERTO", "DIFERENTE": "DIFERENTE", "—": "—"},
            "Optional": {"IGUAL": "IGUAL", "DIFERENTE": "DIFERENTE", "—": "—"}
        }

        # Ler e converter feedback
        fb_raw = {
            "HP": dpg.get_value(self.ui["fb_hp"]),
            "Weapons": dpg.get_value(self.ui["fb_wep"]),
            "Resistance": dpg.get_value(self.ui["fb_res"]),
            "Weakness": dpg.get_value(self.ui["fb_weak"]),
            "Immunity": dpg.get_value(self.ui["fb_imm"]),
            "Optional": dpg.get_value(self.ui["fb_opt"]),
        }
        
        # Converter para símbolos internos
        fb = {}
        for key, value in fb_raw.items():
            fb[key] = feedback_mapping[key].get(value, "—")

        # Log do feedback
        log(self.ui, " Feedback aplicado:")
        for k, v in fb.items():
            if v and v != "—":
                log(self.ui, f"  {k}: {v}")

        apply_feedback_to_restrictions(self.restrictions, fb, guess_boss)

        # Sugestões
        suggestions = None
        if self.scraper:
            suggestions = self.scraper.get_suggestions()
            if suggestions:
                log(self.ui, f" Sugestões atualizadas: {suggestions}")
            else:
                log(self.ui, " Sem sugestões (usando todos os bosses)")

        # Reclassifica
        self._recompute_ranking(suggestions)
        self._refresh_restrictions_panel()

        # Verifica se encontrou o boss
        if (fb.get("HP") == "IGUAL" and fb.get("Weapons") == "IGUAL" and 
            fb.get("Resistance") == "IGUAL" and fb.get("Weakness") == "IGUAL" and 
            fb.get("Immunity") == "IGUAL" and fb.get("Optional") == "IGUAL"):
            log(self.ui, f"\nBOSS ENCONTRADO: {guess_boss['name']}!\n")

        if self.attempt >= self.max_attempts:
            log(self.ui, "\n Fim das tentativas. Ranking final calculado.")

    def setup_gui(self):
        """Configura toda a interface gráfica."""
        dpg.create_context()

        # Tema escuro personalizado
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (30, 30, 30))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (40, 40, 40))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (70, 70, 70))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (90, 90, 90))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (50, 50, 150))
                dpg.add_theme_color(dpg.mvThemeCol_Header, (60, 60, 60))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (80, 80, 80))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (70, 70, 120))

        # Janela principal
        with dpg.window(label="QuizSoulsLOL", width=1400, height=900, tag="primary_window"):
            
            # Header com controles principais
            with dpg.group(horizontal=True):
                self.ui["btn_start"] = dpg.add_button(label="INICIAR BOT", callback=self.cb_start_automation, 
                              width=120)
                self.ui["btn_stop"] = dpg.add_button(label="PARAR BOT", callback=self.cb_stop_automation, 
                              width=120, enabled=False)
                self.ui["btn_attempt"] = dpg.add_button(label="FAZER TENTATIVA", callback=self.cb_do_attempt,
                              width=140, enabled=False)
                self.ui["btn_apply_feedback"] = dpg.add_button(label="APLICAR FEEDBACK", callback=self.cb_apply_feedback,
                              width=150, enabled=False)
                self.ui["btn_auto_feedback"] = dpg.add_button(label="CAPTURAR FEEDBACK", callback=self.cb_auto_feedback,
                              width=160, enabled=False)
                self.ui["btn_reset"] = dpg.add_button(label="RESET QUIZ", callback=self.cb_reset_quiz,
                              width=120, enabled=False)
                self.ui["attempt_counter"] = dpg.add_text(f"Tentativas: 0/{self.max_attempts}")

            dpg.add_separator()

            # Layout principal em colunas
            with dpg.group(horizontal=True):
                
                # COLUNA ESQUERDA - Controles e Config
                with dpg.child_window(width=350, height=800):
                    dpg.add_text("CONFIGURACOES", color=[100, 200, 255])
                    dpg.add_separator()
                    
                    # Selenium Config
                    with dpg.collapsing_header(label="Configuracao Selenium", default_open=False):
                        self.ui["cb_use_selenium"] = dpg.add_checkbox(label="Usar Selenium", default_value=True)
                        self.ui["cb_headless"] = dpg.add_checkbox(label="Modo Headless", default_value=False)
                        dpg.add_text("URL do Quiz:")
                        self.ui["inp_url"] = dpg.add_input_text(default_value="https://daily-souls.netlify.app/classic/", width=-1)
                        dpg.add_text("Seletor Sugestoes:")
                        self.ui["inp_sel_sug"] = dpg.add_input_text(default_value=".suggestion", width=-1)
                        dpg.add_text("Seletor Input:")
                        self.ui["inp_sel_input"] = dpg.add_input_text(default_value="input[type='text']", width=-1)
                        dpg.add_text("Seletor Submit:")
                        self.ui["inp_sel_submit"] = dpg.add_input_text(default_value="button[type='submit']", width=-1)

                    dpg.add_separator()

                    # Feedback Controls
                    dpg.add_text("FEEDBACK DA TENTATIVA", color=[255, 200, 100])
                    dpg.add_separator()
                    
                    with dpg.group():
                        dpg.add_text("HP:")
                        self.ui["fb_hp"] = dpg.add_combo(items=["—", "MAIOR", "MENOR", "IGUAL"], default_value="—", width=-1)
                        
                        dpg.add_text("Weapons:")
                        self.ui["fb_wep"] = dpg.add_combo(items=["—", "IGUAL", "DIFERENTE"], default_value="—", width=-1)
                        
                        dpg.add_text("Resistance:")
                        self.ui["fb_res"] = dpg.add_combo(items=["—", "IGUAL", "PERTO", "DIFERENTE"], default_value="—", width=-1)
                        
                        dpg.add_text("Weakness:")
                        self.ui["fb_weak"] = dpg.add_combo(items=["—", "IGUAL", "PERTO", "DIFERENTE"], default_value="—", width=-1)
                        
                        dpg.add_text("Immunity:")
                        self.ui["fb_imm"] = dpg.add_combo(items=["—", "IGUAL", "PERTO", "DIFERENTE"], default_value="—", width=-1)
                        
                        dpg.add_text("Optional:")
                        self.ui["fb_opt"] = dpg.add_combo(items=["—", "IGUAL", "DIFERENTE"], default_value="—", width=-1)

                    dpg.add_separator()

                    # Último palpite
                    dpg.add_text(" ÚLTIMO PALPITE", color=[255, 150, 150])
                    self.ui["last_guess"] = dpg.add_text("", wrap=320)

                    dpg.add_separator()

                    # Restrições acumuladas
                    dpg.add_text(" RESTRIÇÕES ATIVAS", color=[150, 255, 150])
                    self.ui["restr_text"] = dpg.add_text("", wrap=320)

                # COLUNA CENTRAL - Ranking e Melhor Candidato
                with dpg.child_window(width=550, height=800):
                    # Melhor candidato
                    dpg.add_text(" MELHOR CANDIDATO", color=[255, 215, 0])
                    dpg.add_separator()
                    
                    self.ui["best_title"] = dpg.add_text(" Melhor candidato provável: —")
                    self.ui["best_breakdown"] = dpg.add_text("", wrap=520)
                    
                    # Barras de score individuais
                    dpg.add_text(" Score Breakdown:")
                    with dpg.group(horizontal=True):
                        dpg.add_text("HP:")
                        self.ui["bar_hp"] = dpg.add_progress_bar(width=100)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Weapons:")
                        self.ui["bar_weapons"] = dpg.add_progress_bar(width=100)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Resistance:")
                        self.ui["bar_resistance"] = dpg.add_progress_bar(width=100)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Weakness:")
                        self.ui["bar_weakness"] = dpg.add_progress_bar(width=100)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Immunity:")
                        self.ui["bar_immunity"] = dpg.add_progress_bar(width=100)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Optional:")
                        self.ui["bar_optional"] = dpg.add_progress_bar(width=100)

                    dpg.add_separator()

                    # Top 10 Ranking
                    dpg.add_text(" TOP 10 RANKING", color=[100, 255, 100])
                    
                    self.ui["table_top"] = dpg.add_table(header_row=True, borders_innerH=True, 
                                                        borders_outerH=True, borders_innerV=True,
                                                        borders_outerV=True, scrollY=True, height=350)
                    
                    dpg.add_table_column(label="#", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="Nome", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=150)
                    dpg.add_table_column(label="Score", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=60)
                    dpg.add_table_column(label="Barra", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=80)
                    dpg.add_table_column(label="HP", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=50)
                    dpg.add_table_column(label="Wep", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=40)
                    dpg.add_table_column(label="Res", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=40)
                    dpg.add_table_column(label="Weak", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=50)
                    dpg.add_table_column(label="Imm", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=40)
                    dpg.add_table_column(label="Opt", parent=self.ui["table_top"], width_fixed=True, init_width_or_weight=70)

                # COLUNA DIREITA - Log e Busca
                with dpg.child_window(width=480, height=800):
                    
                    # Campo de busca
                    dpg.add_text(" BUSCA DE BOSSES", color=[255, 255, 100])
                    dpg.add_separator()
                    
                    dpg.add_text("Filtrar bosses:")
                    self.ui["search_input"] = dpg.add_input_text(hint="Digite o nome...", 
                                                               callback=self._filter_bosses, width=-1)
                    
                    # Tabela de bosses filtrados
                    self.ui["table_filtered"] = dpg.add_table(header_row=True, borders_innerH=True,
                                                             borders_outerH=True, borders_innerV=True,
                                                             borders_outerV=True, scrollY=True, height=250)
                    
                    dpg.add_table_column(label="Nome", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=120)
                    dpg.add_table_column(label="HP", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=50)
                    dpg.add_table_column(label="W", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="R", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="Wk", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="Im", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=30)
                    dpg.add_table_column(label="Opt", parent=self.ui["table_filtered"], width_fixed=True, init_width_or_weight=60)

                    dpg.add_separator()

                    # Log em tempo real
                    dpg.add_text(" LOG EM TEMPO REAL", color=[200, 200, 255])
                    
                    self.ui["log_child"] = dpg.add_child_window(height=300, horizontal_scrollbar=True)
                    self.ui["log"] = dpg.add_text("", wrap=-1, parent=self.ui["log_child"])

        # Inicializa tabelas
        self._refresh_filtered_table()
        self._refresh_restrictions_panel()
        self._update_attempt_counter()

        # Aplica tema
        dpg.bind_theme(global_theme)
        dpg.set_primary_window("primary_window", True)

    def run(self):
        """Executa a aplicação."""
        self.setup_gui()
        
        dpg.create_viewport(title="By Ga v2.0", width=1420, height=920)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        
        log(self.ui, f" QuizSoulsLOL iniciado!")
        log(self.ui, f" Bosses carregados: {len(self.bosses)}")
        if not SELENIUM_OK:
            log(self.ui, " Selenium nao disponivel - modo offline apenas")
        else:
            log(self.ui, " Selenium disponivel - captura automatica ativada!")
        
        dpg.start_dearpygui()
        dpg.destroy_context()

# Main Entry Point

if __name__ == "__main__":
    app = App()
    app.run()