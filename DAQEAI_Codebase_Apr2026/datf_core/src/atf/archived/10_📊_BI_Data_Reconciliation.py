"""
PowerBI Insight Engine — Extended
Uses browser-use to open the report, perform the requested action,
read all widget/graph values, and produce a structured JSON + DataFrame.
"""
import requests
import json
import io
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from testconfig import *

VERIFY_SSL = False
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
 
# ─────────────────────────────────────────────────────────────────────────────
# URL PARSERS
# ─────────────────────────────────────────────────────────────────────────────
 
def parse_powerbi_url(url: str) -> dict:
    ids = {"tenant_id": "", "workspace_id": "", "report_id": "", "dashboard_id": ""}
    if not url:
        return ids
    parsed = urlparse(url)
    qs     = parse_qs(parsed.query)
    path   = parsed.path
    ids["tenant_id"]    = qs.get("ctid", [""])[0] or qs.get("tid", [""])[0]
    m = re.search(rf"/groups/({UUID_RE})", path, re.I)
    ids["workspace_id"] = m.group(1) if m else qs.get("groupId", [""])[0]
    m = re.search(rf"/reports/({UUID_RE})", path, re.I)
    ids["report_id"]    = m.group(1) if m else qs.get("reportId", [""])[0]
    m = re.search(rf"/dashboards/({UUID_RE})", path, re.I)
    ids["dashboard_id"] = m.group(1) if m else ""
    return ids
 
 
def parse_tableau_url(url: str) -> dict:
    ids = {"server": "", "site": "", "workbook": "", "view": ""}
    if not url:
        return ids
    parsed = urlparse(url)
    ids["server"] = f"{parsed.scheme}://{parsed.netloc}"
    combined = parsed.path + parsed.fragment
    m = re.search(r"(?:/t/|/site/)([^/#?]+)", combined, re.I)
    ids["site"] = m.group(1) if m else ""
    m = re.search(r"/views/([^/#?]+)/([^/#?]+)", combined, re.I)
    if m:
        ids["workbook"] = m.group(1)
        ids["view"]     = m.group(2)
    return ids
 
 
def parse_mstr_url(url: str) -> dict:
    ids = {"base_url": "", "project_id": "", "report_id": ""}
    if not url:
        return ids
    parsed = urlparse(url)
    m = re.search(r"(/\w+Library)", parsed.path, re.I)
    lib   = m.group(1) if m else ""
    ids["base_url"] = f"{parsed.scheme}://{parsed.netloc}{lib}/api"
    full  = parsed.path + parsed.fragment
    m = re.search(rf"projects?/({UUID_RE})", full, re.I)
    ids["project_id"] = m.group(1) if m else ""
    m = re.search(rf"reports?/({UUID_RE})", full, re.I)
    ids["report_id"]  = m.group(1) if m else ""
    return ids
 
 
def parse_qlik_url(url: str) -> dict:
    ids = {"tenant_url": "", "app_id": "", "sheet_id": ""}
    if not url:
        return ids
    parsed = urlparse(url)
    ids["tenant_url"] = f"{parsed.scheme}://{parsed.netloc}"
    m = re.search(rf"/app/({UUID_RE})", parsed.path, re.I)
    ids["app_id"]   = m.group(1) if m else ""
    m = re.search(rf"/sheet/({UUID_RE})", parsed.path, re.I)
    ids["sheet_id"] = m.group(1) if m else ""
    return ids
 
 
def detect_tool(url: str) -> str:
    if not url:
        return "Power BI"
    u = url.lower()
    if "powerbi.com" in u or "fabric.microsoft" in u:
        return "Power BI"
    if "tableau" in u:
        return "Tableau"
    if "microstrategy" in u or "mstr" in u:
        return "MicroStrategy"
    if "qlik" in u:
        return "Qlik Cloud"
    return "Power BI"

# ─────────────────────────────────────────────────────────────────────────────
# POWER BI
# ─────────────────────────────────────────────────────────────────────────────
 
class PowerBIClient:
    AUTHORITY = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    SCOPE     = "https://analysis.windows.net/powerbi/api/.default"
    BASE      = "https://api.powerbi.com/v1.0/myorg"
 
    def __init__(self, tenant_id, client_id, client_secret):
        self.tenant_id     = tenant_id
        self.client_id     = client_id
        self.client_secret = client_secret
        self._token        = None
 
    @property
    def token(self):
        if not self._token:
            r = requests.post(
                self.AUTHORITY.format(tenant=self.tenant_id),
                data={"grant_type": "client_credentials",
                      "client_id": self.client_id,
                      "client_secret": self.client_secret,
                      "scope": self.SCOPE},
                verify=VERIFY_SSL, timeout=30)
            r.raise_for_status()
            self._token = r.json()["access_token"]
        return self._token
 
    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
 
    def _get(self, path):
        r = requests.get(f"{self.BASE}{path}", headers=self._h(), verify=VERIFY_SSL, timeout=30)
        r.raise_for_status()
        return r.json()

    def _export_pbix_layout(self, workspace_id: str, report_id: str, log: list) -> tuple:
        """
        Export the PBIX and extract:
          • Report/Layout  — visual layout JSON (UTF-16-LE)
          • DataModelSchema — tabular model JSON with tables/columns/measures

        Returns (page_visuals_map, measure_set) where:
          • page_visuals_map: dict keyed by page name -> list of raw visual dicts
          • measure_set: set of 'TableName.MeasureName' strings from the model schema,
            used to distinguish DAX measures (bare ref ok) from columns (need MIN()).
        Both are empty on failure — callers fall back gracefully.
        """
        import zipfile, io as _io
        page_visuals_map: dict = {}
        measure_set: set = set()
        try:
            log.append("  Exporting PBIX to extract visual layout...")
            export_url = (
                f"{self.BASE}/groups/{workspace_id}/reports/{report_id}/Export"
            )
            r = requests.get(export_url, headers=self._h(),
                             verify=VERIFY_SSL, timeout=120, stream=True)
            r.raise_for_status()

            pbix_bytes = _io.BytesIO(r.content)
            with zipfile.ZipFile(pbix_bytes) as zf:
                names_lower = {n.lower(): n for n in zf.namelist()}

                # ── Report/Layout ────────────────────────────────────────────
                layout_entry = names_lower.get("report/layout")
                if not layout_entry:
                    log.append("  Warning: 'Report/Layout' not found in PBIX ZIP.")
                    return {}, set()

                raw = zf.read(layout_entry)
                # Layout is UTF-16-LE; strip BOM if present
                layout_json = raw.decode("utf-16-le").lstrip("\ufeff")
                layout = json.loads(layout_json)

                # ── DataModelSchema (measures vs columns) ────────────────────
                schema_entry = names_lower.get("datamodelschema") or names_lower.get("model.bim")
                if schema_entry:
                    try:
                        schema_raw = zf.read(schema_entry)
                        for enc in ("utf-8-sig", "utf-16-le", "utf-8"):
                            try:
                                schema = json.loads(schema_raw.decode(enc).lstrip("\ufeff"))
                                break
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue
                        else:
                            schema = {}
                        model = schema.get("model", schema)
                        for tbl in model.get("tables", []):
                            tname = tbl.get("name", "")
                            for meas in tbl.get("measures", []):
                                mname = meas.get("name", "")
                                if tname and mname:
                                    measure_set.add(f"{tname}.{mname}")
                        log.append(f"  Schema: {len(measure_set)} measures identified from DataModelSchema")
                    except Exception as se:
                        log.append(f"  Warning: DataModelSchema parse failed: {se}")

            for section in layout.get("sections", []):
                page_name = section.get("name", "")
                visuals = []
                for vc in section.get("visualContainers", []):
                    # config and filters are JSON strings embedded inside the layout
                    try:
                        cfg = json.loads(vc.get("config", "{}"))
                    except Exception:
                        cfg = {}
                    try:
                        vc_query = json.loads(vc.get("query", "{}"))
                    except Exception:
                        vc_query = {}

                    single_visual = cfg.get("singleVisual", {})
                    vis_type  = single_visual.get("visualType", "")
                    title_obj = (single_visual
                                 .get("vcObjects", {})
                                 .get("title", [{}])[0]
                                 .get("properties", {})
                                 .get("text", {})
                                 .get("expr", {})
                                 .get("Literal", {})
                                 .get("Value", "''"))
                    title = title_obj.strip("'") if title_obj else ""

                    # Collect all bound measure/column display names
                    projections = single_visual.get("projections", {})
                    measure_refs = []
                    for _role, role_items in projections.items():
                        for item in role_items:
                            qref = item.get("queryRef", "")
                            if qref:
                                measure_refs.append(qref)

                    visuals.append({
                        "id":           cfg.get("name", ""),
                        "title":        title,
                        "type":         vis_type,
                        "x":            vc.get("x", 0),
                        "y":            vc.get("y", 0),
                        "width":        vc.get("width", 0),
                        "height":       vc.get("height", 0),
                        "measure_refs": measure_refs,
                        "tile_value":   None,
                    })
                page_visuals_map[page_name] = visuals

            total = sum(len(v) for v in page_visuals_map.values())
            log.append(f"  OK: layout parsed — {len(page_visuals_map)} pages, {total} visuals total")

        except Exception as e:
            log.append(f"  Warning: PBIX export/parse failed: {e}")

        return page_visuals_map, measure_set

    def _resolve_tile_values(self, workspace_id: str, dataset_id: str,
                            page_visuals_map: dict, log: list,
                            measure_set: set = None) -> None:
        """
        Resolved 400 errors by fully qualifying names and capturing API error messages.
        measure_set: 'TableName.MeasureName' strings from the PBIX DataModelSchema.
          Measures use a bare ref in EVALUATE ROW; plain columns need MIN() wrapper.
          Pass an empty set (or omit) to wrap everything with MIN() as a safe fallback.
        """
        QUERY_TYPES = {"card", "tableEx", "pivotTable", "clusteredColumnChart", "lineChart", "areaChart"}
        if measure_set is None:
            measure_set = set()

        def get_safe_dax(ref):
            # Skip structural/hierarchy items — they are not scalar values
            if any(x in ref for x in ["Hierarchy", "Variation"]):
                return None

            # Handle aggregated refs like Sum(TableName.FieldName) — split on '.' inside parens
            # was previously producing malformed DAX like 'Sum(TableName'[FieldName)]
            m = re.match(r'^(\w+)\((.+?)\.(.+)\)$', ref)
            if m:
                func  = m.group(1).upper()
                table = m.group(2)
                field = m.group(3)
                return f"{func}('{table}'[{field}])"

            parts = ref.split('.')
            if len(parts) < 2: return f"[{ref}]"

            table = parts[0]
            # Rejoin remaining parts in case field name itself contains dots
            field = ".".join(parts[1:]).replace("[", "").replace("]", "")

            # Measures evaluate as scalars in EVALUATE ROW — use bare ref.
            # Plain columns have no row context and need MIN() to produce a scalar.
            # Fields prefixed with '#' follow Power BI naming convention for DAX measures.
            if field.startswith('#') or ref in measure_set:
                return f"'{table}'[{field}]"
            return f"MIN('{table}'[{field}])"

        for page_name, visuals in page_visuals_map.items():
            eligible = [v for v in visuals if v.get("type") in QUERY_TYPES and v.get("measure_refs")]
            if not eligible: continue

            # label_map: normalised label -> original qref (for reverse lookup after query)
            pairs, seen, label_map = [], set(), {}
            for vis in eligible:
                for qref in vis["measure_refs"]:
                    dax_expr = get_safe_dax(qref)
                    if dax_expr and dax_expr not in seen:
                        seen.add(dax_expr)
                        label = qref.replace('"', "").replace("'", "")
                        # Wrap with IFERROR so one bad expression doesn't fail the whole page
                        pairs.append(f'"{label}", IFERROR({dax_expr}, BLANK())')
                        label_map[label] = qref

            if not pairs: continue
            dax_query = f"EVALUATE ROW({', '.join(pairs)})"

            try:
                r = requests.post(
                    f"{self.BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
                    headers=self._h(),
                    json={"queries": [{"query": dax_query}]},
                    verify=False, timeout=30
                )

                if not r.ok:
                    # Capture the actual DAX error from the response body
                    error_msg = r.json().get('error', {}).get('message', 'Unknown Error')
                    log.append(f"    DAX failed for {page_name}: {r.status_code}")
                    log.append(f"      [ERROR] {error_msg}")
                    log.append(f"      [QUERY] {dax_query}")
                    continue

                results = r.json().get("results", [{}])[0].get("tables", [{}])[0].get("rows", [{}])
                if results:
                    # Power BI wraps label names in [ ] in the response keys — strip them
                    val_map = {k.strip("[]"): v for k, v in results[0].items()}
                    resolved = 0
                    for vis in eligible:
                        for qref in vis["measure_refs"]:
                            label = qref.replace('"', "").replace("'", "")
                            if label in val_map and val_map[label] is not None:
                                vis["tile_value"] = val_map[label]
                                resolved += 1
                                break
                    log.append(f"    Resolved {resolved}/{len(eligible)} visuals on page '{page_name}'")
            except Exception as e:
                log.append(f"    Exception: {str(e)}")

    def _extract_visual_tables(self, workspace_id: str, dataset_id: str,
                               page_visuals_map: dict, log: list,
                               measure_set: set = None) -> None:
        """
        For table/matrix/chart visuals, runs EVALUATE SUMMARIZECOLUMNS DAX
        queries to extract full multi-row tabular data and stores the result
        in vis["table_data"] as a list of dicts (one per row).
        Card visuals are intentionally skipped — they are already handled by
        _resolve_tile_values as scalar tile_value entries.
        """
        TABLE_TYPES = {
            "tableEx", "pivotTable", "clusteredColumnChart", "lineChart",
            "areaChart", "clusteredBarChart", "barChart",
            "lineStackedColumnComboChart", "ribbonChart", "waterfallChart",
            "scatterChart", "pieChart", "donutChart", "funnel", "treemap",
            "multiRowCard",
        }
        if measure_set is None:
            measure_set = set()

        for page_name, visuals in page_visuals_map.items():
            eligible = [
                v for v in visuals
                if v.get("type") in TABLE_TYPES and v.get("measure_refs")
            ]
            if not eligible:
                continue

            for vis in eligible:
                groupby_cols, measure_exprs = [], []

                for ref in vis["measure_refs"]:
                    if any(x in ref for x in ["Hierarchy", "Variation"]):
                        continue

                    # Handle aggregated refs like Sum(TableName.FieldName)
                    m = re.match(r'^(\w+)\((.+?)\.(.+)\)$', ref)
                    if m:
                        func  = m.group(1).upper()
                        table = m.group(2)
                        field = m.group(3)
                        label = ref.replace('"', '').replace("'", '')
                        measure_exprs.append(f'"{label}", {func}(\'{table}\'[{field}])')
                        continue

                    parts = ref.split('.')
                    if len(parts) < 2:
                        continue
                    table = parts[0]
                    field = ".".join(parts[1:]).replace("[", "").replace("]", "")

                    if field.startswith('#') or ref in measure_set:
                        # DAX measure — add as a named expression pair
                        label = ref.replace('"', '').replace("'", '')
                        measure_exprs.append(f'"{label}", \'{table}\'[{field}]')
                    else:
                        # Plain column — use as a group-by dimension
                        groupby_cols.append(f"'{table}'[{field}]")

                if not groupby_cols and not measure_exprs:
                    continue

                dax_parts = groupby_cols + measure_exprs
                dax_query = f"EVALUATE SUMMARIZECOLUMNS({', '.join(dax_parts)})"

                try:
                    r = requests.post(
                        f"{self.BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
                        headers=self._h(),
                        json={"queries": [{"query": dax_query}]},
                        verify=False, timeout=60,
                    )
                    if r.ok:
                        rows = (r.json()
                                .get("results", [{}])[0]
                                .get("tables", [{}])[0]
                                .get("rows", []))
                        # Power BI wraps column names in [brackets] — strip them
                        clean_rows = [
                            {k.strip("[]"): v for k, v in row.items()}
                            for row in rows
                        ]
                        vis["table_data"] = clean_rows
                        log.append(
                            f"    Table data: '{vis.get('title','?')}' on "
                            f"'{page_name}' — {len(clean_rows)} rows"
                        )
                    else:
                        err = r.json().get('error', {}).get('message', 'Unknown')
                        log.append(
                            f"    Table DAX failed for "
                            f"'{vis.get('title','?')}': {err}"
                        )
                except Exception as e:
                    log.append(
                        f"    Table DAX exception for "
                        f"'{vis.get('title','?')}': {e}"
                    )

    def _fetch_visuals_via_admin(self, workspace_id: str, report_id: str,
                                pages: list, log: list) -> dict:
        """
        Fallback: use the Power BI Admin API to fetch visual metadata per page.
        Requires the service principal to have Tenant.Read.All or
        Tenant.ReadWrite.All (i.e. Power BI Admin role).
        Returns page_visuals_map dict (same shape as _export_pbix_layout) or {}
        if the Admin API is not available / permission denied.
        """
        page_visuals_map = {}
        log.append("  Falling back to Admin API for visual metadata...")
        for p in pages:
            page_name = p["name"]
            try:
                data = self._get(
                    f"/admin/reports/{report_id}/pages/{page_name}/visuals"
                )
                visuals = []
                for v in data.get("value", []):
                    visuals.append({
                        "id":           v.get("id", ""),
                        "title":        v.get("title", ""),
                        "type":         v.get("type", ""),
                        "x":            v.get("x", 0),
                        "y":            v.get("y", 0),
                        "width":        v.get("width", 0),
                        "height":       v.get("height", 0),
                        "measure_refs": [],   # Admin API does not expose DAX refs
                        "tile_value":   None,
                    })
                page_visuals_map[page_name] = visuals
            except Exception as e:
                log.append(f"    Admin API unavailable for page '{page_name}': {e}")
                return {}
        total = sum(len(v) for v in page_visuals_map.values())
        log.append(f"  OK: Admin API — {len(page_visuals_map)} pages, {total} visuals")
        return page_visuals_map

    def scrape(self, workspace_id, report_id, dashboard_id, log):
        result = {
            "tool": "Power BI", "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "workspace_id": workspace_id, "report_id": report_id,
            "report": {}, "pages": [], "dataset": {}, "datasources": [],
            "refresh_history": [], "dax_results": [],
            "dashboard": {}, "tiles": [], "errors": [],
        }

        if report_id:
            log.append("Fetching report metadata...")
            try:
                rep = self._get(f"/groups/{workspace_id}/reports/{report_id}")
                result["report"] = {k: rep.get(k, "") for k in
                    ["id", "name", "webUrl", "embedUrl", "datasetId",
                     "createdDateTime", "modifiedDateTime"]}
                log.append(f"  OK: {rep['name']}")

                log.append("  Fetching pages...")
                pages = self._get(f"/groups/{workspace_id}/reports/{report_id}/pages")["value"]

                # ── Step 1: extract visual layout from PBIX export ───────────
                page_visuals_map, measure_set = self._export_pbix_layout(workspace_id, report_id, log)

                # ── Step 1b: Admin API fallback if PBIX layout unavailable ───
                if not page_visuals_map:
                    page_visuals_map = self._fetch_visuals_via_admin(
                        workspace_id, report_id, pages, log
                    )

                # ── Step 2: resolve DAX tile values for card visuals ─────────
                dataset_id_early = rep.get("datasetId", "")
                if page_visuals_map and dataset_id_early:
                    log.append("  Resolving DAX tile values for card visuals...")
                    self._resolve_tile_values(
                        workspace_id, dataset_id_early, page_visuals_map, log,
                        measure_set=measure_set
                    )
                    log.append("  Extracting tabular data for table/chart visuals...")
                    self._extract_visual_tables(
                        workspace_id, dataset_id_early, page_visuals_map, log,
                        measure_set=measure_set
                    )

                # ── Step 3: merge into enriched pages list ───────────────────
                enriched_pages = []
                for p in pages:
                    page_entry = {
                        "name":        p["name"],
                        "displayName": p["displayName"],
                        "order":       p.get("order", 0),
                        "visuals":     page_visuals_map.get(p["name"], []),
                    }
                    enriched_pages.append(page_entry)

                result["pages"] = enriched_pages
                # ─────────────────────────────────────────────────────────────

                log.append(f"  OK: {len(pages)} pages")
 
                dataset_id = rep.get("datasetId", "")
                if dataset_id:
                    log.append("  Fetching dataset...")
                    try:
                        ds = self._get(f"/groups/{workspace_id}/datasets/{dataset_id}")
                        result["dataset"] = {k: ds.get(k, "") for k in
                            ["id", "name", "configuredBy", "isRefreshable",
                             "targetStorageMode", "createReportEmbedURL"]}
                        log.append(f"  OK: dataset {ds['name']}")
                    except Exception as e:
                        result["errors"].append(f"dataset: {e}")
 
                    log.append("  Fetching datasources...")
                    try:
                        sources = self._get(f"/groups/{workspace_id}/datasets/{dataset_id}/datasources")["value"]
                        result["datasources"] = [
                            {"datasourceType": s.get("datasourceType", ""),
                             "connectionDetails": s.get("connectionDetails", {})}
                            for s in sources]
                        log.append(f"  OK: {len(sources)} datasources")
                    except Exception as e:
                        result["errors"].append(f"datasources: {e}")
 
                    log.append("  Fetching refresh history...")
                    try:
                        hist = self._get(f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes")["value"]
                        result["refresh_history"] = [
                            {k: h.get(k, "") for k in ["refreshType", "startTime", "endTime", "status"]}
                            for h in hist[:10]]
                        log.append(f"  OK: {len(hist)} refresh records")
                    except Exception as e:
                        result["errors"].append(f"refresh: {e}")
 
            except Exception as e:
                result["errors"].append(f"report: {e}")
                log.append(f"  Error: {e}")
 
        if dashboard_id:
            log.append("Fetching dashboard...")
            try:
                db = self._get(f"/groups/{workspace_id}/dashboards/{dashboard_id}")
                result["dashboard"] = {k: db.get(k, "") for k in
                    ["id", "displayName", "embedUrl", "webUrl", "isReadOnly"]}
                tiles = self._get(f"/groups/{workspace_id}/dashboards/{dashboard_id}/tiles")["value"]

                # ── NEW: enrich each dashboard tile with its embed value ────
                enriched_tiles = []
                for t in tiles:
                    tile_entry = {k: t.get(k, "") for k in
                        ["id", "title", "rowSpan", "colSpan", "reportId", "datasetId"]}
                    # Attempt to read the tile's current value from embedData
                    tile_entry["tile_value"] = t.get("embedData", {}) or t.get("embedUrl", "")
                    enriched_tiles.append(tile_entry)

                result["tiles"] = enriched_tiles
                # ─────────────────────────────────────────────────────────────

                log.append(f"  OK: {db.get('displayName','')} — {len(tiles)} tiles")
            except Exception as e:
                result["errors"].append(f"dashboard: {e}")
                log.append(f"  Error: {e}")
 
        return result
 
 
# ─────────────────────────────────────────────────────────────────────────────
# TABLEAU
# ─────────────────────────────────────────────────────────────────────────────
 
class TableauClient:
    def __init__(self, server, token_name, token_value, site=""):
        self.server = server
        self.token_name = token_name
        self.token_value = token_value
        self.site = site
 
    def scrape(self, workbook_name, view_name, log):
        result = {"tool": "Tableau", "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                  "server": self.server, "view": {}, "data": [], "errors": []}
        try:
            import tableauserverclient as TSC
        except ImportError:
            result["errors"].append("pip install tableauserverclient")
            return result
        auth   = TSC.PersonalAccessTokenAuth(self.token_name, self.token_value, self.site)
        server = TSC.Server(self.server, use_server_version=True)
        server.add_http_options({"verify": VERIFY_SSL})
        try:
            with server.auth.sign_in(auth):
                log.append("OK: Signed in to Tableau")

                # ── NEW: enumerate all workbooks and their views per sheet ──
                result["pages"] = []
                workbooks_pager = TSC.Pager(server.workbooks)
                for wb in workbooks_pager:
                    server.workbooks.populate_views(wb)
                    page_entry = {
                        "workbook_id":   wb.id,
                        "workbook_name": wb.name,
                        "project":       wb.project_name,
                        "visuals":       [],   # one entry per view/sheet
                    }
                    for v in wb.views:
                        visual_entry = {
                            "view_id":    v.id,
                            "view_name":  v.name,
                            "content_url": v.content_url,
                            "tile_value": None,   # populated below
                        }
                        # Populate CSV data as the tile value for this view
                        try:
                            server.views.populate_csv(v)
                            df_view = pd.read_csv(
                                io.StringIO(b"".join(v.csv).decode("utf-8", errors="replace"))
                            )
                            # Summarise: first numeric cell or row-count as tile value
                            numeric_cols = df_view.select_dtypes(include="number").columns.tolist()
                            if numeric_cols:
                                visual_entry["tile_value"] = df_view[numeric_cols[0]].sum()
                            else:
                                visual_entry["tile_value"] = f"{len(df_view)} rows"
                            visual_entry["columns"] = list(df_view.columns)
                            visual_entry["rows"]    = len(df_view)
                            visual_entry["data"]    = df_view.to_dict(orient="records")
                        except Exception as csv_err:
                            log.append(f"    CSV error for view '{v.name}': {csv_err}")

                        page_entry["visuals"].append(visual_entry)

                    result["pages"].append(page_entry)
                    log.append(
                        f"  OK: workbook '{wb.name}' — {len(page_entry['visuals'])} views"
                    )
                # ─────────────────────────────────────────────────────────────

                # Legacy single-view extraction (unchanged)
                req = TSC.RequestOptions()
                req.filter.add(TSC.Filter("name", TSC.RequestOptions.Operator.Equals, view_name))
                views, _ = server.views.get(req)
                if not views:
                    result["errors"].append(f"View not found: {view_name}")
                    return result
                view = views[0]
                result["view"] = {"id": view.id, "name": view.name}
                log.append(f"  OK: View {view.name}")
                server.views.populate_csv(view)
                df = pd.read_csv(io.StringIO(b"".join(view.csv).decode("utf-8", errors="replace")))
                result["data"]    = df.to_dict(orient="records")
                result["columns"] = list(df.columns)
                result["rows"]    = len(df)
                log.append(f"  OK: {len(df)} rows")
        except Exception as e:
            result["errors"].append(str(e))
            log.append(f"  Error: {e}")
        return result
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MICROSTRATEGY
# ─────────────────────────────────────────────────────────────────────────────
 
class MicroStrategyClient:
    def __init__(self, base_url, username, password, login_mode=1):
        self.base_url   = base_url.rstrip("/")
        self.username   = username
        self.password   = password
        self.login_mode = login_mode
        self.token      = None
        self.cookies    = {}
 
    def login(self):
        r = requests.post(f"{self.base_url}/auth/login",
                          json={"username": self.username, "password": self.password,
                                "loginMode": self.login_mode},
                          verify=VERIFY_SSL, timeout=30)
        r.raise_for_status()
        self.token   = r.headers["X-MSTR-AuthToken"]
        self.cookies = dict(r.cookies)
 
    def logout(self):
        if self.token:
            try:
                requests.post(f"{self.base_url}/auth/logout",
                              headers={"X-MSTR-AuthToken": self.token},
                              cookies=self.cookies, verify=VERIFY_SSL, timeout=10)
            except Exception:
                pass

    def _auth_headers(self, project_id: str = "") -> dict:
        """Return auth headers, optionally including the project ID."""
        h = {"X-MSTR-AuthToken": self.token, "Accept": "application/json"}
        if project_id:
            h["X-MSTR-ProjectID"] = project_id
        return h

    def _get_dossier_pages(self, project_id: str, dossier_id: str, log: list) -> list:
        """
        Fetch all chapters/pages of an MSTR dossier and extract widget
        metadata + tile values from each visualization on each page.
        Returns a list of page dicts compatible with result["pages"].
        """
        pages_out = []
        try:
            # Create a dossier instance
            r = requests.post(
                f"{self.base_url}/dossiers/{dossier_id}/instances",
                headers=self._auth_headers(project_id),
                cookies=self.cookies,
                json={},
                verify=VERIFY_SSL,
                timeout=60,
            )
            r.raise_for_status()
            instance_id = r.json().get("mid", "")
            log.append(f"  Dossier instance created: {instance_id}")

            # Fetch chapter/page definitions
            r2 = requests.get(
                f"{self.base_url}/dossiers/{dossier_id}/instances/{instance_id}/chapters",
                headers=self._auth_headers(project_id),
                cookies=self.cookies,
                verify=VERIFY_SSL,
                timeout=30,
            )
            r2.raise_for_status()
            chapters = r2.json().get("chapters", [])

            for chapter in chapters:
                for page in chapter.get("pages", []):
                    page_entry = {
                        "chapter_key":  chapter.get("key", ""),
                        "chapter_name": chapter.get("name", ""),
                        "page_key":     page.get("key", ""),
                        "page_name":    page.get("name", ""),
                        "visuals":      [],
                    }

                    # Fetch visualizations on this page
                    try:
                        r3 = requests.get(
                            f"{self.base_url}/dossiers/{dossier_id}"
                            f"/instances/{instance_id}"
                            f"/chapters/{chapter['key']}/pages/{page['key']}/visualizations",
                            headers=self._auth_headers(project_id),
                            cookies=self.cookies,
                            verify=VERIFY_SSL,
                            timeout=30,
                        )
                        r3.raise_for_status()
                        viz_list = r3.json().get("visualizations", [])

                        for viz in viz_list:
                            visual_entry = {
                                "id":         viz.get("key", ""),
                                "title":      viz.get("name", ""),
                                "type":       viz.get("visualizationType", ""),
                                "tile_value": None,
                            }
                            # Extract tile value from metric data if present
                            data_block = viz.get("result", {}).get("data", {})
                            metric_vals = (
                                data_block
                                .get("metricValues", {})
                                .get("raw", [[]])
                            )
                            if metric_vals and metric_vals[0]:
                                visual_entry["tile_value"] = metric_vals[0][0]

                            # Attach full definition for widget metadata
                            visual_entry["definition"] = viz.get("definition", {})
                            page_entry["visuals"].append(visual_entry)

                        log.append(
                            f"    Page '{page['name']}': {len(viz_list)} visualizations"
                        )
                    except Exception as ve:
                        log.append(f"    Warning: viz fetch failed for page '{page['name']}': {ve}")

                    pages_out.append(page_entry)

        except Exception as e:
            log.append(f"  Warning: dossier page fetch failed: {e}")

        return pages_out

    def scrape(self, project_id, report_id, log):
        result = {"tool": "MicroStrategy", "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                  "report_id": report_id, "data": {}, "rows": [], "columns": [], "errors": []}
        try:
            self.login()
            log.append("OK: Logged in to MicroStrategy")
            h = {"X-MSTR-AuthToken": self.token, "X-MSTR-ProjectID": project_id,
                 "Accept": "application/json"}
            log.append(f"  Fetching report {report_id}...")
            r = requests.post(f"{self.base_url}/reports/{report_id}/instances",
                              headers=h, cookies=self.cookies,
                              json={}, verify=VERIFY_SSL, timeout=60)
            r.raise_for_status()
            data = r.json()
            result["data"]    = data
            result["rows"]    = data.get("data", {}).get("rows", [])
            result["columns"] = data.get("definition", {}).get("columns", [])
            log.append(f"  OK: {len(result['rows'])} rows")

            # ── NEW: fetch dossier pages + visuals if report_id is a dossier
            log.append("  Fetching dossier pages and visuals...")
            result["pages"] = self._get_dossier_pages(project_id, report_id, log)
            log.append(f"  OK: {len(result['pages'])} pages extracted")
            # ─────────────────────────────────────────────────────────────────

        except Exception as e:
            result["errors"].append(str(e))
            log.append(f"  Error: {e}")
        finally:
            self.logout()
        return result
 
 
# ─────────────────────────────────────────────────────────────────────────────
# QLIK
# ─────────────────────────────────────────────────────────────────────────────
 
class QlikClient:
    def __init__(self, tenant_url, api_key):
        self.base    = tenant_url.rstrip("/") + "/api/v1"
        self.api_key = api_key
 
    def _h(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _get_sheets_and_objects(self, app_id: str, log: list) -> list:
        """
        Connect to the Qlik Engine JSON API (WebSocket) to enumerate all sheets
        and the objects (widgets) on each sheet, extracting their layout and
        current hypercube / measure tile values.

        Falls back to the REST /items endpoint if websocket is unavailable.
        Returns a list of page dicts compatible with result["pages"].
        """
        pages_out = []

        # ── Approach 1: Engine API via REST app/objects listing ──────────────
        try:
            r = requests.get(
                f"{self.base}/apps/{app_id}/objects",
                headers=self._h(),
                verify=VERIFY_SSL,
                timeout=30,
            )
            r.raise_for_status()
            all_objects = r.json().get("data", [])

            # Group objects by their sheet
            sheet_map: dict = {}
            for obj in all_objects:
                attrs = obj.get("attributes", {})
                sheet_id = attrs.get("sheetId") or attrs.get("parentId") or "__root__"
                if sheet_id not in sheet_map:
                    sheet_map[sheet_id] = {
                        "sheet_id":   sheet_id,
                        "sheet_name": attrs.get("sheetName", sheet_id),
                        "visuals":    [],
                    }
                visual_entry = {
                    "id":         attrs.get("id", obj.get("id", "")),
                    "title":      attrs.get("title", attrs.get("name", "")),
                    "type":       attrs.get("visualizationType", attrs.get("type", "")),
                    "tile_value": None,
                }
                # Pull hypercube measure values if present
                hc = attrs.get("qHyperCubeDef") or attrs.get("hypercube") or {}
                measure_vals = hc.get("qMeasureInfo", [])
                if measure_vals:
                    visual_entry["tile_value"] = measure_vals[0].get("qMin") or measure_vals[0].get("qMax")
                visual_entry["layout"] = {
                    k: attrs.get(k)
                    for k in ("col", "row", "colspan", "rowspan")
                    if attrs.get(k) is not None
                }
                sheet_map[sheet_id]["visuals"].append(visual_entry)

            pages_out = list(sheet_map.values())
            log.append(f"  OK: {len(pages_out)} sheets with objects via REST")

        except Exception as rest_err:
            log.append(f"  Warning: REST sheet/object fetch failed: {rest_err}")

            # ── Approach 2: /items endpoint fallback ─────────────────────────
            try:
                r2 = requests.get(
                    f"{self.base}/items?resourceType=app&resourceId={app_id}",
                    headers=self._h(),
                    verify=VERIFY_SSL,
                    timeout=30,
                )
                r2.raise_for_status()
                items = r2.json().get("data", [])
                fallback_page: dict = {
                    "sheet_id":   "__items__",
                    "sheet_name": "Items (fallback)",
                    "visuals":    [],
                }
                for item in items:
                    fallback_page["visuals"].append({
                        "id":         item.get("id", ""),
                        "title":      item.get("name", ""),
                        "type":       item.get("resourceType", ""),
                        "tile_value": None,
                        "layout":     {},
                    })
                pages_out = [fallback_page]
                log.append(f"  OK (fallback): {len(items)} items listed")
            except Exception as fb_err:
                log.append(f"  Warning: fallback items fetch also failed: {fb_err}")

        return pages_out

    def scrape(self, app_id, log):
        result = {"tool": "Qlik Cloud", "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                  "app_id": app_id, "app": {}, "metadata": {}, "errors": []}
        log.append(f"  Fetching app {app_id}...")
        try:
            r = requests.get(f"{self.base}/apps/{app_id}", headers=self._h(),
                             verify=VERIFY_SSL, timeout=30)
            r.raise_for_status()
            app = r.json()
            attrs = app.get("attributes", {})
            result["app"] = {k: attrs.get(k, "") for k in
                ["id", "name", "description", "owner", "published", "lastReloadTime"]}
            log.append(f"  OK: {attrs.get('name', app_id)}")
        except Exception as e:
            result["errors"].append(f"app: {e}")
 
        log.append("  Fetching metadata...")
        try:
            r = requests.get(f"{self.base}/apps/{app_id}/data/metadata",
                             headers=self._h(), verify=VERIFY_SSL, timeout=30)
            r.raise_for_status()
            meta = r.json()
            result["metadata"] = meta
            log.append(f"  OK: {len(meta.get('fields',[]))} fields, {len(meta.get('tables',[]))} tables")
        except Exception as e:
            result["errors"].append(f"metadata: {e}")

        # ── NEW: fetch all sheets + widget visuals + tile values ──────────────
        log.append("  Fetching sheets and widget objects...")
        result["pages"] = self._get_sheets_and_objects(app_id, log)
        log.append(f"  OK: {len(result['pages'])} pages extracted")
        # ─────────────────────────────────────────────────────────────────────

        return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
# DataFrame flattener
# ══════════════════════════════════════════════════════════════════════════════
def generate_reconciliation_template(json_file_path):
    """
    Converts the extracted JSON into a flat reconciliation table.
    """
    with open(json_file_path, 'r') as f:
        json_data = json.load(f)
    
    reco_rows = []
    
    for page in json_data.get('pages', []):
        page_label = (
            page.get('displayName')
            or page.get('page_name')
            or page.get('sheet_name')
            or page.get('workbook_name')
            or 'page'
        )
        for vis in page.get('visuals', []):
            if vis.get('tile_value') is not None:
                # measure_refs is Power BI-specific; fall back gracefully for other tools
                refs = vis.get('measure_refs') or []
                metric_ref = refs[0] if refs else (vis.get('title') or vis.get('id') or '')
                reco_rows.append({
                    "Page":      page_label,
                    "Visual":    vis.get('title') or vis.get('view_name') or vis.get('type'),
                    "Metric":    metric_ref,
                    "BI Value":  vis.get('tile_value'),
                    "SQL_Query": f"/* Compare with {metric_ref} */ SELECT ... ",
                })
    
    df = pd.DataFrame(reco_rows)
    if "BI Value" in df.columns:
        df["BI Value"] = df["BI Value"].astype(str)
    return df
 
def generate_excel_workbook(json_file_path, excel_filepath):
    """
    Builds a single Excel workbook from the extracted BI JSON:
      • 'Summary' sheet  — flat reconciliation table (one row per visual/metric)
      • One sheet per visual that has multi-row table_data extracted via DAX
    Returns the workbook as raw bytes suitable for st.download_button.
    """
    with open(json_file_path, 'r') as f:
        json_data = json.load(f)

    summary_rows = []
    visual_sheets: list[tuple[str, pd.DataFrame]] = []   # (sheet_name, df)

    for page in json_data.get('pages', []):
        page_label = (
            page.get('displayName')
            or page.get('page_name')
            or page.get('sheet_name')
            or page.get('workbook_name')
            or 'page'
        )
        for vis in page.get('visuals', []):
            vis_title = vis.get('title') or vis.get('view_name') or vis.get('type') or 'visual'

            # ── Summary row (scalar tile_value) ──────────────────────────────
            if vis.get('tile_value') is not None:
                refs = vis.get('measure_refs') or []
                metric_ref = refs[0] if refs else (vis.get('title') or vis.get('id') or '')
                summary_rows.append({
                    "Page":      page_label,
                    "Visual":    vis_title,
                    "Metric":    metric_ref,
                    "BI Value":  str(vis.get('tile_value')),
                    "SQL_Query": f"/* Compare with {metric_ref} */ SELECT ... ",
                })

            # ── Per-visual tabular sheet ──────────────────────────────────────
            table_data = vis.get('table_data')
            if table_data:
                vis_df = pd.DataFrame(table_data)
                vis_df = vis_df.astype(str)   # ensure Arrow-safe types
                # Excel sheet names: max 31 chars, no invalid chars
                raw_name = f"{page_label[:12]}_{vis_title[:16]}"
                sheet_name = re.sub(r'[\\/*?\[\]:]', '_', raw_name)[:31]
                # Deduplicate sheet names
                existing = [s for s, _ in visual_sheets]
                if sheet_name in existing:
                    sheet_name = sheet_name[:28] + f"_{len(existing)}"
                visual_sheets.append((sheet_name, vis_df))

    output = excel_filepath
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Summary sheet first
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # One sheet per visual with tabular data
        for sheet_name, vis_df in visual_sheets:
            vis_df.to_excel(writer, sheet_name=sheet_name, index=False)


def flatten_to_df(data: dict) -> pd.DataFrame:
    tool      = data.get("tool", "")
    timestamp = data.get("timestamp", "")
    rows      = []
 
    def add(section, name, metric, value, extra=""):
        rows.append({
            "tool":      tool,
            "section":   section,
            "name":      name,
            "metric":    metric,
            "value":     str(value),
            "extra":     extra,
            "timestamp": timestamp,
        })
 
    # Power BI
    for ws in data.get("workspaces", []):
        add("workspace", ws.get("name"), "id", ws.get("id"))
    for rp in data.get("reports", []):
        add("report", rp.get("name"), "id", rp.get("id"), rp.get("webUrl", ""))
    for ds in data.get("datasets", []):
        for measure in ds.get("measures", []):
            for k, v in measure.items():
                add("dataset_measure", ds.get("name"), k, v)
    for db in data.get("dashboards", []):
        for tile in db.get("tiles", []):
            add("dashboard_tile", db.get("name"), tile.get("title", "tile"), tile.get("id"))

    # ── NEW: flatten pages → visuals for all tools ────────────────────────────
    for page in data.get("pages", []):
        page_label = (
            page.get("displayName")       # Power BI
            or page.get("page_name")      # MicroStrategy
            or page.get("sheet_name")     # Qlik
            or page.get("workbook_name")  # Tableau
            or "page"
        )
        for vis in page.get("visuals", []):
            vis_name = vis.get("title") or vis.get("view_name") or vis.get("id") or "visual"
            add("page_visual", page_label, "type",       vis.get("type", ""),       vis_name)
            add("page_visual", page_label, "tile_value", vis.get("tile_value", ""), vis_name)
    # ─────────────────────────────────────────────────────────────────────────
 
    # Tableau
    for view in data.get("views", []):
        for row in view.get("data", []):
            for k, v in row.items():
                add("view", view.get("name"), k, v)
    for wb in data.get("workbooks", []):
        add("workbook", wb.get("name"), "project", wb.get("project", ""))
 
    # MicroStrategy
    for proj in data.get("projects", []):
        add("project", proj.get("name"), "id", proj.get("id"))
    for rep in data.get("reports", []):
        for i, row in enumerate(rep.get("data", [])):
            if isinstance(row, dict):
                for k, v in row.items():
                    add("report_row", rep.get("name"), k, v, f"row_{i}")
            else:
                add("report_row", rep.get("name"), f"row_{i}", row)
 
    # Qlik
    for sp in data.get("spaces", []):
        add("space", sp.get("name"), "id", sp.get("id"), sp.get("type", ""))
    for app in data.get("apps", []):
        add("app", app.get("name"), "id", app.get("id"), app.get("space", ""))
 
    return pd.DataFrame(rows) if rows else pd.DataFrame()
 
# ══════════════════════════════════════════════════════════════════════════════
# Streamlit UI
# ══════════════════════════════════════════════════════════════════════════════
 
st.set_page_config(
    page_title="BI Data Reconciliation",
    page_icon="🔬",
    layout="wide"
)
 
st.title("📊 BI Data Reconciliation")
st.caption("Connects via native APIs — no browser required")
 
# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {"result": None, "df": None, "log": [], "parsed": {}, "tool": "Power BI"}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# URL input
report_url = st.text_input(
    "Report URL",
    placeholder="Paste any Power BI / Tableau / MicroStrategy / Qlik URL…",
)
 
# Parse + detect
tool = detect_tool(report_url)
parsed = {}
if report_url:
    if tool == "Power BI":          parsed = parse_powerbi_url(report_url)
    elif tool == "Tableau":         parsed = parse_tableau_url(report_url)
    elif tool == "MicroStrategy":   parsed = parse_mstr_url(report_url)
    elif tool == "Qlik Cloud":      parsed = parse_qlik_url(report_url)
    else:                           parsed = parse_powerbi_url(report_url)
    st.session_state.parsed = parsed
    st.session_state.tool   = tool
 
    with st.expander(f"🔍 Detected: **{tool}** — parsed IDs (editable)", expanded=True):
        id_cols = st.columns(max(len(parsed), 1))
        edited  = {}
        for col, (k, v) in zip(id_cols, parsed.items()):
            edited[k] = col.text_input(k.replace("_", " ").title(), value=v, key=f"id_{k}")
        parsed = edited

st.header("🔧 Credentials")
tool_display = st.session_state.tool
pbi_client = pbi_secret = ""
tab_token_name = tab_token_value = ""
mstr_user = mstr_pass = ""
mstr_mode = ("Standard", 1)
qlik_apikey = ""

if tool_display == "Power BI":
    pbi_client = st.text_input("Client ID",     value=os.environ.get("PBI_CLIENT_ID", ""))
    pbi_secret = st.text_input("Client Secret", value=os.environ.get("PBI_CLIENT_SECRET", ""), type="password")

elif tool_display == "Tableau":
    tab_token_name  = st.text_input("Token Name",  value=os.environ.get("TABLEAU_TOKEN_NAME", ""))
    tab_token_value = st.text_input("Token Value", value=os.environ.get("TABLEAU_TOKEN_VALUE", ""), type="password")

elif tool_display == "MicroStrategy":
    mstr_user = st.text_input("Username", value=os.environ.get("MSTR_USER", ""))
    mstr_pass = st.text_input("Password", value=os.environ.get("MSTR_PASS", ""), type="password")
    mstr_mode = st.selectbox("Login Mode", [("Standard", 1), ("LDAP", 16)], format_func=lambda x: x[0])

elif tool_display == "Qlik Cloud":
    qlik_apikey = st.text_input("API Key", value=os.environ.get("QLIK_API_KEY", ""), type="password")

st.divider()
run_btn = st.button("🚀 Fetch Data", use_container_width=True, type="primary")

# ── Main area ─────────────────────────────────────────────────────────────────
st.subheader("📋 Log")
log_box = st.empty()

if st.session_state.log:
    log_box.code("\n".join(st.session_state.log), language=None)
else:
    log_box.info("Logs will appear here when you click Fetch Data.")
 
 
# ── DataFrame ─────────────────────────────────────────────────────────────────
if st.session_state.df is not None and not st.session_state.df.empty:
    df: pd.DataFrame = st.session_state.df
    st.subheader("📊 Processing Summary")
 
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Rows",    len(df))
    c2.metric("Sections",      df["section"].nunique()   if "section" in df.columns else "—")
    c3.metric("Unique Names",  df["name"].nunique()      if "name" in df.columns else "—")
    c4.metric("Unique Metrics",df["metric"].nunique()    if "metric" in df.columns else "—")
 
    st.dataframe(df, use_container_width=True, height=360)
    download_csv = st.download_button(
        "⬇ Download CSV (above data)",
        data=df.to_csv(index=False),
        file_name=f"bi_df_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    if st.session_state.result:
        bi_json_filename = f"bi_extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        bi_json_filepath = os.path.join(bi_step1_path, bi_json_filename)
        with open(bi_json_filepath, "w", encoding="utf-8") as f:
            json.dump(st.session_state.result, f, indent=2, ensure_ascii=False)
        
        bi_excel_filename = f"bi_visuals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        bi_excel_filepath = os.path.join(bi_step1_path, bi_excel_filename)
        st.divider()
        st.subheader("📊 Extracted Visual Data")

        try:
            if st.button("⬇ Save Visual Data to Excel ", type="secondary"):
                generate_excel_workbook(bi_json_filepath, bi_excel_filepath)
                st.success(f"Excel workbook generated at: {bi_excel_filepath}")
        except Exception as _exc:
            st.warning(f"Excel export failed: {_exc}")
 
    errs = st.session_state.result.get("errors", [])
    if errs:
        st.warning("API reported issues:\n" + "\n".join(f"• {e}" for e in errs))
 
# Run logic
if run_btn:
    if not report_url:
        st.error("Please paste a report URL first.")
        st.stop()
 
    p   = parsed or st.session_state.parsed
    log = []
    errs = []
 
    if tool_display == "Power BI":
        if not p.get("tenant_id"):    errs.append("Tenant ID not found — check URL contains ?ctid=…")
        if not p.get("workspace_id"): errs.append("Workspace ID not found in URL")
        if not p.get("report_id") and not p.get("dashboard_id"):
            errs.append("Report or Dashboard ID not found in URL")
        if not pbi_client: errs.append("Client ID required")
        if not pbi_secret: errs.append("Client Secret required")
    elif tool_display == "Tableau":
        if not tab_token_name:  errs.append("Token Name required")
        if not tab_token_value: errs.append("Token Value required")
    elif tool_display == "MicroStrategy":
        if not p.get("base_url"): errs.append("Could not parse MicroStrategy base URL")
        if not mstr_user: errs.append("Username required")
        if not mstr_pass: errs.append("Password required")
    elif tool_display == "Qlik Cloud":
        if not p.get("tenant_url"): errs.append("Could not parse Qlik tenant URL")
        if not qlik_apikey: errs.append("API Key required")
 
    if errs:
        for e in errs:
            st.error(e)
        st.stop()
 
    st.session_state.log = st.session_state.result = st.session_state.df = None
    st.session_state.log = []
 
    with st.spinner(f"Fetching from {tool_display}..."):
        try:
            if tool_display == "Power BI":
                log.append(f"Authenticating (tenant: {p['tenant_id'][:8]}...)")
                client = PowerBIClient(p["tenant_id"], pbi_client, pbi_secret)
                log.append("OK: Token obtained")
                result = client.scrape(p["workspace_id"], p.get("report_id", ""),
                                       p.get("dashboard_id", ""), log)
            elif tool_display == "Tableau":
                log.append(f"Connecting to Tableau: {p['server']}")
                client = TableauClient(p["server"], tab_token_name, tab_token_value, p.get("site", ""))
                result = client.scrape(p.get("workbook", ""), p.get("view", ""), log)
            elif tool_display == "MicroStrategy":
                log.append(f"Connecting to MicroStrategy: {p['base_url']}")
                client = MicroStrategyClient(p["base_url"], mstr_user, mstr_pass, mstr_mode[1])
                result = client.scrape(p.get("project_id", ""), p.get("report_id", ""), log)
            elif tool_display == "Qlik Cloud":
                log.append(f"Connecting to Qlik: {p['tenant_url']}")
                client = QlikClient(p["tenant_url"], qlik_apikey)
                result = client.scrape(p.get("app_id", ""), log)
 
            log.append("Done.")
            st.session_state.log    = log
            st.session_state.result = result
            st.session_state.df     = flatten_to_df(result)
            st.rerun()

        except Exception as exc:
            log.append(f"Error: {exc}")
            st.session_state.log = log
            st.error(f"Error: {exc}")