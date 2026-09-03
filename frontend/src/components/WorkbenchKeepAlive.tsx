import { Navigate, useLocation } from "react-router-dom";
import { useEffect, useState, type ComponentType } from "react";
import InputDataPage from "../pages/InputDataPage";
import ParamsPage from "../pages/ParamsPage";
import ResultsPage from "../pages/ResultsPage";
import AttributionPage from "../pages/AttributionPage";
import WhatIfPage from "../pages/WhatIfPage";
import PriceElasticityPage from "../pages/PriceElasticityPage";
import StrategyKnowledgePage from "../pages/StrategyKnowledgePage";

/**
 * 工作台页面保活：首次进入才挂载并拉数，栏目切换只隐藏 DOM，
 * 浏览器整页刷新才会重新加载。
 */
const WORKBENCH_PAGES: { path: string; Component: ComponentType }[] = [
  { path: "/workbench/input", Component: InputDataPage },
  { path: "/workbench/params", Component: ParamsPage },
  { path: "/workbench/results", Component: ResultsPage },
  { path: "/workbench/attribution", Component: AttributionPage },
  { path: "/workbench/what-if", Component: WhatIfPage },
  { path: "/workbench/what-if/elasticity", Component: PriceElasticityPage },
  { path: "/workbench/what-if/knowledge", Component: StrategyKnowledgePage },
];

const PATH_SET = new Set(WORKBENCH_PAGES.map((p) => p.path));

function notifyChartsResize() {
  window.dispatchEvent(new Event("resize"));
}

export function WorkbenchKeepAlive() {
  const { pathname } = useLocation();
  const [visited, setVisited] = useState<string[]>(() =>
    PATH_SET.has(pathname) ? [pathname] : [],
  );

  if (PATH_SET.has(pathname) && !visited.includes(pathname)) {
    setVisited((prev) => (prev.includes(pathname) ? prev : [...prev, pathname]));
  }

  useEffect(() => {
    if (!PATH_SET.has(pathname)) return;
    const id = window.setTimeout(notifyChartsResize, 50);
    return () => window.clearTimeout(id);
  }, [pathname]);

  if (pathname === "/workbench" || pathname === "/workbench/") {
    return <Navigate to="/workbench/input" replace />;
  }

  if (pathname.startsWith("/workbench/") && !PATH_SET.has(pathname)) {
    return <Navigate to="/workbench/input" replace />;
  }

  return (
    <div className="h-full min-h-0">
      {WORKBENCH_PAGES.map(({ path, Component }) => {
        if (!visited.includes(path)) return null;
        const active = pathname === path;
        return (
          <div
            key={path}
            className={active ? "h-full min-h-0" : "hidden"}
            aria-hidden={!active}
          >
            <Component />
          </div>
        );
      })}
    </div>
  );
}
