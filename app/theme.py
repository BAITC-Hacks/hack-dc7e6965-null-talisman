"""
<!--
THESIS: Точность важнее украшательства. Визуальный язык методичного расчёта —
строгая сетка чисел, ноль decorative-хрома, один сдержанный акцент для
действия и срочности. Refuses the card-shell default: Streamlit expanders
become flat divided sections, not boxed cards with shadow.
OWN-WORLD: графитовый текст на холодном очень светлом фоне; один синий
акцент (#2454E0 — действие/фокус/ссылки), отдельный приглушённый красный
только для critical-состояния. IBM Plex Sans — интерфейс, IBM Plex Mono —
числа, деньги, артикулы, id: инструмент инженера закупа, не маркетинговый
дашборд. Тонкие 1px разделители вместо теней; радиусы малые (4-6px), не
"дружелюбно-круглые".
STORY: менеджер отличает срочное от обычного по цвету и весу текста бейджа
за долю секунды, не по эмодзи; фокус всегда на числе и обосновании под ним.
FIRST VIEWPORT: сайдбар — тонкая вертикальная линия-разделитель, не тень.
KPI — ряд моноширинных чисел без карточек-метрик. Список поставщиков —
плоские секции с разделителем сверху, не боксы.
FORM: code-led (нет image-gen в среде); сокращённая процедура new-work
(без concept-seed dice-roll и decision-page — непропорционально объёму
задачи "переключаемая тема" при жёстком тайм-боксе хакатона; раскрыто
пользователю в чате). Ключ: null-talisman-corporate-2026-09-23.
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying
its provenance. (Здесь — самопроверка скриншотом вместо отдельного
finish-reviewer субагента: тот же тайм-бокс.)
-->

Переключаемая тема "Строгий корпоративный" для Streamlit-приложения.
Ничего не меняет в расчёте/данных — только CSS поверх стоковых компонентов
Streamlit. Управляется через st.session_state["theme"] ("classic" | "corporate"),
общий для всех страниц (multipage app делит session_state одной сессии).

Использование на каждой странице:
    from app.theme import theme_toggle, apply_theme
    theme_toggle()   # в сайдбаре, один раз в начале страницы
    apply_theme()    # внедряет CSS, если выбрана новая тема
"""
from __future__ import annotations

import streamlit as st

THEME_KEY = "theme"
DEFAULT_THEME = "classic"

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --nt-ink: #14181f;
  --nt-ink-soft: #4a5264;
  --nt-line: #d8dce3;
  --nt-line-soft: #e8eaef;
  --nt-bg: #f6f7f9;
  --nt-surface: #ffffff;
  --nt-accent: #2454e0;
  --nt-accent-ink: #ffffff;
  --nt-accent-soft: #e8edfc;
  --nt-critical: #b3261e;
  --nt-critical-soft: #fbeae9;
  --nt-high: #9a5b00;
  --nt-high-soft: #fdf1de;
  --nt-normal: #1b7a4d;
  --nt-normal-soft: #e7f5ee;
  --nt-radius: 6px;
  --nt-radius-sm: 4px;
}

/* --- фон и типографика ---
   stApp — корневой контейнер, его тёмный фон просвечивает сквозь прозрачные
   виджеты (дата/число/селектбокс рисуют только рамку, не заливку) везде,
   где ниже по дереву нет собственного непрозрачного фона. Красим и его, и
   stAppViewContainer (видимая область под хедером). */
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
  background: var(--nt-bg);
}
[data-testid="stTextInputRootElement"],
[data-testid="stDateInputField"],
[data-testid="stNumberInputContainer"],
[data-testid="stSelectbox"] div[role="group"],
[data-testid="stMultiSelect"] div[role="group"] {
  background: var(--nt-surface) !important;
  border: 1px solid var(--nt-line) !important;
  border-radius: var(--nt-radius-sm) !important;
}
[data-testid="stTextInputRootElement"] input,
[data-testid="stDateInputField"] input,
[data-testid="stNumberInputContainer"] input,
[data-testid="stSelectbox"] input,
[data-testid="stMultiSelect"] input {
  color: var(--nt-ink) !important;
}
/* Всплывающий список опций селектбокса — тоже отдельный слой поверх stApp */
[data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] {
  background: var(--nt-surface) !important;
  border: 1px solid var(--nt-line) !important;
}
[data-baseweb="popover"] [role="option"] {
  color: var(--nt-ink) !important;
}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [role="option"][aria-selected="true"] {
  background: var(--nt-accent-soft) !important;
}
html, body, [data-testid="stAppViewContainer"] * {
  font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  color: var(--nt-ink);
}
/* Material Symbols рендерится через лигатуры (текст = имя иконки) — свой
   font-family для них обязателен, иначе вместо стрелочки видно "arrow_right" */
[data-testid="stIconMaterial"] {
  font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
}
h1, h2, h3, h4, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--nt-ink);
}
[data-testid="stCaptionContainer"], .stCaption, small {
  color: var(--nt-ink-soft) !important;
}
code, .stCodeBlock, [data-testid="stMetricValue"],
[data-testid="stDataFrame"] * {
  font-family: 'IBM Plex Mono', ui-monospace, monospace !important;
}

/* --- боковая панель: тонкая линия, не тень --- */
[data-testid="stSidebar"] {
  background: var(--nt-surface);
  border-right: 1px solid var(--nt-line);
  box-shadow: none;
}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--nt-ink-soft);
  font-weight: 600;
}

/* --- заголовок страницы --- */
[data-testid="stAppViewContainer"] > .main .block-container {
  padding-top: 2rem;
}

/* --- кнопки: один акцент, без градиентов и теней --- */
[data-testid="stBaseButton-primary"], .stButton > button[kind="primary"] {
  background: var(--nt-accent);
  color: var(--nt-accent-ink);
  border: 1px solid var(--nt-accent);
  border-radius: var(--nt-radius-sm);
  font-weight: 500;
  box-shadow: none;
  transition: background-color 120ms ease-out, border-color 120ms ease-out;
}
[data-testid="stBaseButton-primary"]:hover, .stButton > button[kind="primary"]:hover {
  background: #1a3fb8;
  border-color: #1a3fb8;
}
[data-testid="stBaseButton-secondary"], .stButton > button[kind="secondary"] {
  background: var(--nt-surface);
  color: var(--nt-ink);
  border: 1px solid var(--nt-line);
  border-radius: var(--nt-radius-sm);
  box-shadow: none;
  transition: border-color 120ms ease-out, background-color 120ms ease-out;
}
[data-testid="stBaseButton-secondary"]:hover, .stButton > button[kind="secondary"]:hover {
  border-color: var(--nt-accent);
  background: var(--nt-accent-soft);
}
button:focus-visible, a:focus-visible, input:focus-visible {
  outline: 2px solid var(--nt-accent) !important;
  outline-offset: 2px;
}

/* --- метрики (KPI-строка): ряд чисел, не карточки-плашки --- */
[data-testid="stMetric"] {
  background: transparent;
  border: none;
  border-top: 2px solid var(--nt-line);
  padding-top: 0.5rem;
}
[data-testid="stMetricLabel"] {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--nt-ink-soft) !important;
  font-weight: 500;
}
[data-testid="stMetricValue"] {
  font-size: 1.6rem;
  font-weight: 600;
  color: var(--nt-ink);
}

/* --- expander (карточки поставщиков): плоская секция с разделителем, не бокс с тенью --- */
[data-testid="stExpander"] {
  border: none;
  border-top: 1px solid var(--nt-line);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
[data-testid="stExpander"] summary {
  font-weight: 600;
  padding: 0.85rem 0;
  background: transparent !important;
}
[data-testid="stExpander"] summary:hover {
  color: var(--nt-accent);
}
[data-testid="stExpanderDetails"] {
  padding-left: 0;
  padding-right: 0;
}

/* --- таблицы/data_editor: чёткая сетка, moнoширинные числа --- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  border: 1px solid var(--nt-line);
  border-radius: var(--nt-radius-sm);
}
[data-testid="stDataFrame"] thead tr th, [data-testid="stDataEditor"] thead tr th {
  background: var(--nt-line-soft) !important;
  color: var(--nt-ink-soft) !important;
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.68rem;
  letter-spacing: 0.04em;
}

/* --- вкладки (сайдбар-страницы) --- */
[data-testid="stTabs"] [data-baseweb="tab"] {
  font-weight: 500;
}
[data-testid="stTabs"] [aria-selected="true"] {
  color: var(--nt-accent) !important;
  border-bottom-color: var(--nt-accent) !important;
}

/* --- алерты: убираем цветную заливку по умолчанию, тонкая верхняя линия --- */
[data-testid="stAlert"] {
  border-radius: var(--nt-radius-sm);
  border: 1px solid var(--nt-line);
  box-shadow: none;
}

/* --- прогресс-бар: акцентный цвет вместо дефолтного красного --- */
[data-testid="stProgress"] > div > div > div {
  background-color: var(--nt-accent) !important;
}

/* --- радио/чекбокс акцент --- */
input[type="radio"]:checked + div, input[type="checkbox"]:checked + div {
  accent-color: var(--nt-accent);
}

/* --- выделение текста и скроллбар: тоже часть темы, не дефолт браузера --- */
::selection { background: var(--nt-accent-soft); color: var(--nt-ink); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--nt-bg); }
::-webkit-scrollbar-thumb { background: var(--nt-line); border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: var(--nt-ink-soft); }

/* --- срочность: сдержанные текстовые бейджи вместо ярких плашек/эмодзи --- */
.nt-badge {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: var(--nt-radius-sm);
  font-size: 0.75rem;
  font-weight: 600;
  font-family: 'IBM Plex Mono', monospace;
}
.nt-badge-critical { background: var(--nt-critical-soft); color: var(--nt-critical); }
.nt-badge-high { background: var(--nt-high-soft); color: var(--nt-high); }
.nt-badge-normal { background: var(--nt-normal-soft); color: var(--nt-normal); }
</style>
"""


def theme_toggle(location: str = "sidebar") -> str:
    """Рисует переключатель темы (radio из двух пунктов) и возвращает текущее
    значение. Хранится в session_state, разделяется всеми страницами."""
    target = st.sidebar if location == "sidebar" else st
    current = st.session_state.get(THEME_KEY, DEFAULT_THEME)
    with target.expander("Оформление", expanded=False):
        choice = st.radio(
            "Тема интерфейса",
            options=["classic", "corporate"],
            format_func=lambda v: "Стандартная Streamlit" if v == "classic" else "Строгий корпоративный",
            index=0 if current == DEFAULT_THEME else 1,
            key="_nt_theme_radio",
            label_visibility="collapsed",
        )
    st.session_state[THEME_KEY] = choice
    return choice


def apply_theme() -> None:
    """Внедряет CSS темы, если в session_state выбрана 'corporate'. Ничего не
    делает для 'classic' — дефолтный вид Streamlit остаётся нетронутым."""
    if st.session_state.get(THEME_KEY, DEFAULT_THEME) == "corporate":
        st.markdown(_CSS, unsafe_allow_html=True)


def urgency_badge(urgency: str, label: str) -> str:
    """HTML-бейдж срочности для темы 'corporate' — используется вместо эмодзи
    там, где вызывающий код явно решил его показать (не меняет данные)."""
    css_class = {"critical": "nt-badge-critical", "high": "nt-badge-high"}.get(urgency, "nt-badge-normal")
    return f'<span class="nt-badge {css_class}">{label}</span>'
