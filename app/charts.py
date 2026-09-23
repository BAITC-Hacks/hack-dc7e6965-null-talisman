import pandas as pd
import plotly.graph_objects as go


def demand_chart(series: pd.DataFrame) -> go.Figure:
    table = series.copy()
    table["month"] = pd.to_datetime(table["month"].astype(str))
    table = table.sort_values("month")
    figure = go.Figure()
    for column, title, color, dash in [
        ("raw", "Фактические продажи", "#94a3b8", "solid"),
        ("clean", "Очищенный спрос", "#2563eb", "solid"),
        ("forecast", "Прогноз", "#0f766e", "dash"),
    ]:
        figure.add_trace(go.Scatter(x=table["month"], y=table[column], name=title,
                                   mode="lines+markers", connectgaps=False,
                                   line={"color": color, "dash": dash, "width": 2}))
    if "oneoff" in table:
        points = table[table["oneoff"].fillna(0) > 0]
        figure.add_trace(go.Scatter(x=points["month"], y=points["raw"], mode="markers",
                                   name="Разовый сверхобъём", marker={"color": "#dc2626", "size": 10},
                                   customdata=points["oneoff"],
                                   hovertemplate="Исключено %{customdata:.0f} шт.<extra></extra>"))
    if "stockout_days" in table:
        for month in table.loc[table["stockout_days"].fillna(0) > 0, "month"]:
            figure.add_vrect(x0=month, x1=month + pd.offsets.MonthBegin(1),
                             fillcolor="#f59e0b", opacity=.12, line_width=0, layer="below")
    figure.update_layout(height=360, margin={"l": 10, "r": 10, "t": 20, "b": 10},
                         yaxis_title="Количество, шт.", xaxis_title=None,
                         legend={"orientation": "h", "y": 1.15}, hovermode="x unified",
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return figure
