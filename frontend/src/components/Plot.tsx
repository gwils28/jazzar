"use client";

import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { useI18n } from "@/lib/i18n";

const PlotComp = createPlotlyComponent(Plotly);
const SERIES = ["#F4A261", "#8A90B3", "#F0B5B5", "#8FBF8A", "#F4F1DE", "#C9742F", "#7A1C1C"];

export default function Plot({ figure }: { figure: { data: Record<string, unknown>[]; layout: Record<string, unknown> } }) {
  const { theme } = useI18n();
  const fg = theme === "dark" ? "#F4F1DE" : "#2B1E1A";
  const grid = theme === "dark" ? "rgba(244,241,222,.08)" : "rgba(43,30,26,.1)";
  const data = figure.data.map((tr, i) => ({ ...tr, marker: { ...(tr.marker as object ?? {}), color: SERIES[i % SERIES.length] }, line: { ...(tr.line as object ?? {}), color: SERIES[i % SERIES.length], width: 2.5 } }));
  const layout = {
    ...figure.layout,
    autosize: true, height: 380, margin: { l: 56, r: 20, t: 48, b: 48 },
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { color: fg, family: "var(--font-inter), system-ui" },
    title: { ...(figure.layout.title as object ?? {}), font: { family: "var(--font-fraunces), Georgia, serif", size: 18, color: fg }, x: 0.02 },
    xaxis: { ...(figure.layout.xaxis as object ?? {}), gridcolor: grid, zerolinecolor: grid },
    yaxis: { ...(figure.layout.yaxis as object ?? {}), gridcolor: grid, zerolinecolor: grid },
    legend: { orientation: "h", y: -0.2 },
    hoverlabel: { bgcolor: "#2B1E1A", bordercolor: "#F4A261", font: { color: "#F4F1DE" } },
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return <PlotComp data={data as any} layout={layout as any} config={{ displaylogo: false, responsive: true }} style={{ width: "100%" }} useResizeHandler />;
}
