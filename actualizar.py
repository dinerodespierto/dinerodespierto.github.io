"""Actualiza el bloque DATOS DE MERCADO de index.html.

Lo ejecuta GitHub Actions cada día hábil después del cierre de la bolsa de EE.UU.
(ver .github/workflows/actualizar.yml). También se puede correr a mano:
    pip install yfinance requests
    python actualizar.py
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import requests
import yfinance as yf

INDEX = Path(__file__).with_name("index.html")
TICKERS = ["SPY", "QQQ", "XLK", "VT", "SCHG", "SCHD", "GLD", "AAPL", "MSFT", "NVDA",
           "AMZN", "GOOGL", "META", "TSLA", "KO", "INTC", "NKE", "BND", "TLT", "SGOV"]
INICIO = "2022-09-21"
INI = "/* ===== DATOS DE MERCADO"
FIN = "/* ===== FIN DATOS DE MERCADO ===== */"


def leer_bloque(html):
    a = html.index(INI)
    b = html.index(FIN) + len(FIN)
    return a, b, html[a:b]


def valor_js(bloque, clave):
    m = re.search(clave + r":\s*(.+?),\n", bloque)
    return m.group(1) if m else None


def precios_yahoo():
    """Cierres ajustados por splits y dividendos desde el 1 sep 2022."""
    df = yf.download(TICKERS, start="2022-09-01", auto_adjust=True, progress=False, group_by="column")
    cierres = df["Close"].dropna(how="all")
    return cierres


def trm_hoy(anterior):
    try:
        r = requests.get(
            "https://www.datos.gov.co/resource/32sa-8pi3.json",
            params={"$order": "vigenciadesde DESC", "$limit": 1}, timeout=30)
        r.raise_for_status()
        v = float(r.json()[0]["valor"])
        if 1000 < v < 10000:
            return round(v, 2)
    except Exception as e:  # noqa: BLE001
        print("TRM: no se pudo actualizar, se deja la anterior:", e)
    return anterior


def main():
    html = INDEX.read_text(encoding="utf-8")
    a, b, bloque = leer_bloque(html)
    trm_ant = float(valor_js(bloque, "trm"))
    cdt = re.search(r"cdt:\s*(\[\[.*?\]\])", bloque, re.S).group(1)

    cierres = precios_yahoo()
    ultimo_dia = cierres.index.max().date()
    hoy = dt.date.today()

    precios, series = {}, {}
    fallidos = []
    for t in TICKERS:
        s = cierres[t].dropna() if t in cierres else None
        if s is None or s.empty:
            fallidos.append(t)
            continue
        ini = s[s.index <= INICIO]
        if ini.empty:
            fallidos.append(t)
            continue
        precios[t] = [round(float(ini.iloc[-1]), 4), round(float(s.iloc[-1]), 4)]
        mensual = s.resample("ME").last()
        # solo meses ya cerrados (el mes en curso no va)
        mensual = mensual[mensual.index.to_period("M") < hoy.strftime("%Y-%m")]
        series[t] = [round(float(v), 4) for v in mensual.values]

    if fallidos:
        # conserva los valores anteriores de los tickers que fallaron
        viejo = json.loads(re.sub(r"(\w+):", r'"\1":', re.search(r"precios:\s*(\{.*?\})", bloque, re.S).group(1)))
        for t in fallidos:
            if t in viejo:
                precios[t] = viejo[t]
        print("Sin datos nuevos para:", ", ".join(fallidos))

    largo = max(len(v) for v in series.values())
    viejas = json.loads(re.sub(r"(\w+):", r'"\1":', re.search(r"series:\s*(\{.*?\})", bloque, re.S).group(1)))
    for t in TICKERS:
        if len(series.get(t, [])) != largo and t in viejas:
            series[t] = viejas[t]  # conserva la serie anterior si la nueva quedó incompleta
    series = {t: series[t] for t in TICKERS if t in series}

    fecha = ultimo_dia.isoformat()
    trm = trm_hoy(trm_ant)
    lp = lambda d: ", ".join(f"{t}: {json.dumps(v)}" for t, v in d.items())  # noqa: E731
    nuevo = (
        INI + ": los actualiza la tarea programada. No cambies la forma de este bloque. ===== */\n"
        "window.DATOS = {\n"
        f"  fecha: '{fecha}',\n"
        f"  trm: {trm},\n"
        "  // [precio ajustado al 21 sep 2022, precio de cierre en \"fecha\"]\n"
        "  precios: {\n    " + lp(precios) + "\n  },\n"
        "  // Cierres ajustados de fin de mes, uno por mes, empezando en septiembre de 2022\n"
        "  series: {\n" + ",\n".join(f"    {t}: {json.dumps(v)}" for t, v in series.items()) + "\n  },\n"
        "  // CDT a 1 año renovado cada 21 de septiembre: [fecha de renovación, tasa E.A.]\n"
        f"  cdt: {cdt}\n"
        "};\n" + FIN
    )
    if nuevo == bloque:
        print("Sin cambios.")
        return 0
    INDEX.write_text(html[:a] + nuevo + html[b:], encoding="utf-8")
    print(f"Actualizado al {fecha}: {len(precios)} tickers, {largo} meses, TRM {trm}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
