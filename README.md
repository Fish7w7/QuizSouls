# ⚔️ QuizSouls Bot  

Um bot para jogar automaticamente o **Daily Souls (Dark Souls II Quiz)**.  
O projeto tem duas versões principais:  

- **QuizSoulsV1.py** → versão inicial simples, roda no terminal usando **Selenium**.  
- **QuizSoulsLOL.py** → versão avançada com **GUI (DearPyGui)** e suporte opcional a Selenium.  

---

## 🚀 Funcionalidades
- Carregamento dos dados dos bosses (`bosses.json` e `bosses_indexed.json`).  
- Uso de `legend.json` para mapear armas, resistências, fraquezas e imunidades.  
- Automação do site Daily Souls via **Selenium**.  
- Interface gráfica interativa feita em **DearPyGui**.  
- Sistema de ranking e pontuação dos candidatos.  
- Opção de captura automática de feedback direto do site.  

---

## 📦 Instalação

Clone o repositório:
```bash
git clone https://github.com/SEU_USUARIO/QuizSouls.git
cd QuizSouls

Instale as dependências:
pip install -r requirements.txt
