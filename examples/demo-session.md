# Demo session

Three runs of `capiv ask` on 2026-10-30, against the real unconventional Capítulo IV
file (431 k rows, data to 2026-09) and the synthetic company in
[`my_company.csv`](my_company.csv). Model `claude-opus-5-5`, adaptive thinking,
`--max-budget-usd 3`. Lines starting with `→` are the tool calls the agent chose
(echoed to stderr by the CLI); everything else is the model's answer, verbatim.

---

## 1. ¿Mis pozos están sobre la curva tipo de los bloques vecinos de Vaca Muerta? Identificá cuáles están por debajo y cuánto.

```
  → company_summary()
Los 12 pozos son de Vaca Muerta shale (petrolíferos) en BLOQUE DEMO, con primera producción entre 2022-03 y 2025-06. Ahora busco las áreas análogas para esa misma ventana de vintage.
  → list_areas(cuenca='NEUQUINA', formacion='vaca muerta', sub_tipo_recurso='SHALE', fluid='oil', vintage_from='2022-01', vintage_to='2025-06', min_wells=10, limit=40)
  → type_curve(cuenca='NEUQUINA', formacion='vaca muerta', sub_tipo_recurso='SHALE', fluid='oil', vintage_from='2022-01', vintage_to='2025-06', areas=['LA AMARGA CHICA', 'BANDURRIA SUR', 'LOMA CAMPANA-LLL', 'LOMA CAMPANA', 'BAJADA DEL PALO OESTE', 'BAJADA DEL PALO ESTE', 'LOMA COLORADA', 'COIRON AMARGO SUR OESTE', 'CRUZ DE LORENA', 'SIERRAS BLANCAS', 'LA ANGOSTURA SUR I', 'MATA MORA NORTE', 'LINDERO ATRAVESADO OCCIDENTAL'], months=36)
  → well_benchmark(cuenca='NEUQUINA', formacion='vaca muerta', sub_tipo_recurso='SHALE', fluid='oil', vintage_from='2022-01', vintage_to='2025-06', areas=[...same 13 areas...], metric='cum12')
```

En conjunto sí están sobre la curva: 10 de los 12 pozos caen en o por encima de la P50 de los análogos en el acumulado de 12 meses, y la mediana del bloque queda en torno a P60. Hay dos pozos claramente por debajo, **BD-9** y **BD-3**, y un tercero algo flojo, **BD-6**.

**Contra qué comparé.** BLOQUE DEMO no está en los datos públicos, así que no sé dónde queda ni cuáles son sus vecinos reales. Usé 13 bloques del núcleo petrolero de Vaca Muerta: La Amarga Chica, Bandurria Sur, Loma Campana y Loma Campana-LLL, Bajada del Palo Oeste y Este, Loma Colorada, Coirón Amargo Sur Oeste, Cruz de Lorena, Sierras Blancas, La Angostura Sur I, Mata Mora Norte y Lindero Atravesado Occidental. Son 804 pozos de petróleo shale de la cuenca Neuquina que empezaron a producir entre 2022-01 y 2025-06. Si me pasás los bloques que realmente lindan con el tuyo, repito el análisis solo con esos.

**Rango de los análogos (acumulado 12 meses):** P10 = 21.785 m³, P50 = 37.355 m³, P90 = 55.487 m³.

**Pozos por debajo de la curva:**

| Pozo | Primera producción | Acum. 12 meses (m³) | Percentil | vs P50 | Caudal vs P50 (meses 3 / 6 / 12 / 24) |
|---|---|---|---|---|---|
| **BD-9** | 2024-05 | 17.308 | P5 | **−54%** | −61% / −58% / −57% / −59% |
| **BD-3** | 2022-09 | 20.873 | P8 | **−44%** | −55% / −50% / −34% / −39% |
| BD-6 | 2023-07 | 33.061 | P35 | −11% | −32% / −13% / +3% / +8% |
| BD-1 | 2022-03 | 36.512 | P47 | −2% | −28% / −4% / +21% / +24% |

**Cómo leerlo:**
- **BD-9 y BD-3** arrancan muy por debajo (caudal máximo de 82–91 m³/d contra unos 161 m³/d de la P50) y se mantienen 35–60% abajo durante toda su vida. No es que declinen más rápido: el problema viene desde el inicio, lo que apunta a la terminación, al landing o a la interferencia con pozos vecinos. Ninguno de los dos produce agua fuera de lo normal.
- **BD-6** arranca 32% abajo y después alcanza la P50, pero acumula 89.340 m³ de agua contra 66.599 m³ de petróleo, un corte de agua de alrededor de 57%. El resto de los pozos está en 15–20%. Conviene revisarlo: puede ser comunicación con agua o un problema de flowback.
- BD-1 y, en menor grado, BD-5, BD-8, BD-2 y BD-12 arrancan bajo la P50 pero declinan más lento y quedan por encima desde el mes 6–12. Esa forma de declinación es mejor que la de los análogos.
- Los mejores son **BD-7** (P92, +55%), **BD-4** (P88, +41%) y **BD-11** (P82, +33%).

**Limitaciones:**
- Los caudales son por día calendario, sin corregir por días efectivos de producción, y los datos públicos no traen el largo de rama, así que un pozo con rama más corta va a parecer peor de lo que es.
- BD-12 tiene apenas 15 meses de historia y BD-11, 20: su acumulado de 12 meses ya está definido, pero no hay historia larga para confirmar la tendencia.
- El grupo de análogos es grande (804 pozos), pero mezcla operadores con diseños distintos.

Si querés, puedo correr `gor_water_cut` para confirmar lo de BD-6 o `operator_benchmark` para ver dónde queda tu compañía frente a cada operador.

Gráficos: `capiv_out/type_curve_oil_-_...png`, `capiv_out/well_benchmark_cum12_oil_-_...png`

`[5 turns, 33s, cost $0.667]`

![type curve](../docs/type_curve.png)
![well benchmark](../docs/well_benchmark.png)

---
