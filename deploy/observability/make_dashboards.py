"""Writes the Grafana dashboards in deploy/observability/dashboards/; edit the queries here, not the JSON."""
import json
import sys
from pathlib import Path

PG = {"type": "grafana-postgresql-datasource", "uid": "ordo-postgres"}
PROM = {"type": "prometheus", "uid": "prometheus"}
NS = 'namespace="cfo-ai"'


def sql(ref, q, fmt="table"):
    return {"refId": ref, "datasource": PG, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": q.strip()}


def prom(ref, expr, legend=""):
    return {"refId": ref, "datasource": PROM, "editorMode": "code", "expr": expr, "legendFormat": legend,
            "range": True, "instant": False}


def steps(*pairs):
    it = iter(pairs)
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in zip(it, it)]}


class Board:
    def __init__(self):
        self.panels = []

    def add(self, type_, title, x, y, w, h, targets, ds, *, desc="", unit=None, thresholds=None, min_=None,
            max_=None, decimals=None, custom=None, options=None, overrides=None, mappings=None, interval=None,
            color=None):
        defaults = {}
        if unit:
            defaults["unit"] = unit
        if thresholds:
            defaults["thresholds"] = thresholds
        if min_ is not None:
            defaults["min"] = min_
        if max_ is not None:
            defaults["max"] = max_
        if decimals is not None:
            defaults["decimals"] = decimals
        if custom:
            defaults["custom"] = custom
        if mappings:
            defaults["mappings"] = mappings
        if color:
            defaults["color"] = color
        panel = {"id": len(self.panels) + 1, "type": type_, "title": title, "description": desc,
                 "gridPos": {"x": x, "y": y, "w": w, "h": h}, "datasource": ds, "targets": targets,
                 "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options or {}}
        if interval:
            panel["interval"] = interval
        self.panels.append(panel)

    def stat(self, title, x, y, w, h, target, ds, **kw):
        kw.setdefault("options", {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                                  "colorMode": "background", "graphMode": "none", "textMode": "value",
                                  "justifyMode": "center", "wideLayout": True})
        self.add("stat", title, x, y, w, h, [target], ds, **kw)

    def series(self, title, x, y, w, h, targets, ds, *, bars=False, stack=False, **kw):
        custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 1 if bars else 2,
                  "fillOpacity": 70 if bars else 10, "showPoints": "never", "spanNulls": False,
                  "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
        custom.update(kw.pop("custom", {}) or {})
        kw.setdefault("options", {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                                  "tooltip": {"mode": "multi", "sort": "desc"}})
        self.add("timeseries", title, x, y, w, h, targets, ds, custom=custom, **kw)

    def table(self, title, x, y, w, h, target, ds, **kw):
        kw.setdefault("options", {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}})
        kw.setdefault("custom", {"align": "auto", "filterable": False})
        self.add("table", title, x, y, w, h, [target], ds, **kw)


def column(name, *props):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": k, "value": v} for k, v in props]}


def cell_color(thresholds, unit=None):
    props = [("custom.cellOptions", {"type": "color-background", "mode": "basic"}), ("thresholds", thresholds)]
    if unit:
        props.append(("unit", unit))
    return props


def dashboard(uid, title, desc, board, *, time_from, refresh="10s"):
    return {
        "uid": uid, "title": title, "description": desc, "tags": ["ordo"], "timezone": "browser",
        "editable": False, "graphTooltip": 1, "schemaVersion": 41, "version": 1, "refresh": refresh,
        "time": {"from": time_from, "to": "now"}, "templating": {"list": []}, "annotations": {"list": []},
        "links": [{"type": "dashboards", "tags": ["ordo"], "asDropdown": False, "title": "Ordo",
                   "includeVars": False, "keepTime": True}],
        "panels": board.panels,
    }


PROCESS = """case
      when o.producer in ('connector', 'connector-mail') then 'connectors'
      when o.producer = 'finance-engine' then 'finance'
      when o.producer = 'pipeline' and o.type in ('transaction.ingested', 'document.extracted') then 'normaliser'
      when o.producer = 'pipeline' then 'matcher'
      else o.producer
    end"""

FLOWS = f"""
with ev as (
  select o.id, o.type, o.occurred_at,
    {PROCESS} as source
  from outbox o
  where $__timeFilter(o.occurred_at)
),
flows as (
  -- one row per (event, consumer group); events no worker subscribes to only reach the browser
  select ev.id, ev.type, ev.occurred_at, ev.source, coalesce(s.consumer, 'ui') as target, d.status
  from ev
  left join outbox_subscription s on s.event_type = ev.type
  left join outbox_delivery d on d.event_id = ev.id and d.consumer = s.consumer
)"""

EDGES = FLOWS + """
select source || '->' || target as id, source, target,
  count(*) || ' events' as mainstat,
  count(*) filter (where status = 'pending') || ' waiting, '
    || count(*) filter (where status = 'dead') || ' dead' as secondarystat,
  string_agg(distinct type, ', ') as detail__types,
  least(1 + ln(count(*)::float8), 8) as thickness,
  case
    when count(*) filter (where status = 'dead') > 0 then 'red'
    when count(*) filter (where status = 'pending' and occurred_at < now() - interval '2 minutes') > 0 then 'orange'
    else '#73bf69'
  end as color
from flows
group by source, target
order by source, target"""

NODES = FLOWS + """,
names as (select source as id from flows union select target from flows),
produced as (select source as id, count(distinct id) as n from flows group by source),
backlog as (
  -- all time, not only the time range: a waiting delivery matters however old it is
  select d.consumer as id,
    count(*) filter (where d.status = 'pending') as waiting,
    count(*) filter (where d.status = 'dead') as dead,
    extract(epoch from now() - min(o.occurred_at) filter (where d.status = 'pending')) as oldest
  from outbox_delivery d join outbox o on o.id = d.event_id
  where d.consumer <> 'sse'
  group by d.consumer
)
select n.id, n.id as title,
  case n.id
    when 'connectors' then 'ordo-connectors'
    when 'extractor' then 'ordo-extractor'
    when 'normaliser' then 'ordo-pipeline'
    when 'matcher' then 'ordo-pipeline'
    when 'agents' then 'ordo-agents'
    when 'api' then 'ordo-api'
    when 'executor' then 'ordo-api'
    when 'finance' then 'backend/finance'
    when 'ui' then 'browser, over SSE'
    else ''
  end as subtitle,
  case when b.id is null then coalesce(p.n, 0) || ' sent' else b.waiting || ' waiting' end as mainstat,
  case when b.id is null then '' else b.dead || ' dead' end as secondarystat,
  case
    when coalesce(b.dead, 0) > 0 then 'red'
    when coalesce(b.oldest, 0) > 120 then 'orange'
    else '#73bf69'
  end as color
from names n
left join produced p on p.id = n.id
left join backlog b on b.id = n.id"""

QUEUES = """
select d.consumer as "Consumer group",
  count(*) filter (where d.status = 'pending') as "Waiting",
  count(*) filter (where d.status = 'dead') as "Dead",
  count(*) filter (where d.status = 'done') as "Done",
  coalesce(extract(epoch from now() - min(o.occurred_at) filter (where d.status = 'pending')), 0) as "Oldest waiting"
from outbox_delivery d
join outbox o on o.id = d.event_id
where d.consumer <> 'sse'
group by d.consumer
order by 2 desc, 1"""

TO_CARD = """
  from outbox m
  join recommendations r on r.subject_id = m.payload->>'match_id'
  join outbox rc on rc.type = 'recommendation.created' and rc.payload->>'recommendation_id' = r.id
  where m.type = 'match.suggested' and $__timeFilter(rc.occurred_at)"""

RECEIPTS = """
select r.occurred_at as "Received", r.company_id as "Company", r.payload->>'kind' as "Kind",
  d.payload->>'status' as "Document",
  extract(epoch from d.occurred_at - r.occurred_at) as "To document",
  extract(epoch from m.occurred_at - r.occurred_at) as "To match",
  extract(epoch from rc.occurred_at - r.occurred_at) as "To inbox card",
  r.correlation_id as "Correlation id"
from outbox r
left join lateral (select x.* from outbox x where x.correlation_id = r.correlation_id
                   and x.type = 'document.extracted' order by x.seq limit 1) d on true
left join lateral (select x.* from outbox x where x.correlation_id = r.correlation_id
                   and x.type in ('match.suggested', 'match.decided') order by x.seq limit 1) m on true
left join lateral (select rec.id from recommendations rec where rec.subject_id = m.payload->>'match_id'
                   order by rec.seq limit 1) rec on true
left join lateral (select x.* from outbox x where x.type = 'recommendation.created'
                   and x.payload->>'recommendation_id' = rec.id order by x.seq limit 1) rc on true
where r.type = 'raw_item.received'
  and r.payload->>'kind' in ('email_attachment', 'upload', 'chat_photo', 'ksef_invoice_xml')
  and $__timeFilter(r.occurred_at)
order by r.seq desc
limit 50"""

CONNECTORS = """
select s.connector as "Connector", s.company_id as "Company", s.doc->>'display_name' as "Source",
  last.doc->>'status' as "Last run", (last.doc->>'items_new')::int as "New items",
  extract(epoch from now() - last.started_at::timestamptz) as "Last run age",
  (select count(*) from sync_runs f where f.source_id = s.id and f.doc->>'status' <> 'success'
     and $__timeFilter(f.started_at::timestamptz)) as "Failed runs",
  coalesce(last.doc->>'error', '') as "Error"
from sources s
left join lateral (select r.* from sync_runs r where r.source_id = s.id order by r.seq desc limit 1) last on true
order by 1, 2"""

DEAD = """
select o.occurred_at as "Event time", d.consumer as "Consumer group", o.type as "Event", d.attempts as "Attempts",
  o.company_id as "Company", o.id as "Event id", o.payload::text as "Payload"
from outbox_delivery d
join outbox o on o.id = d.event_id
where d.status = 'dead'
order by o.seq desc
limit 50"""

OCR_KINDS = "'email_attachment', 'upload', 'chat_photo'"

NOT_YET = ("mappings", [{"type": "special", "options": {"match": "null",
                                                        "result": {"text": "not yet", "color": "transparent"}}}])
LEGEND_RIGHT = {"legend": {"displayMode": "table", "placement": "right", "showLegend": True},
                "tooltip": {"mode": "multi", "sort": "desc"}}

p = Board()
p.stat("Events", 0, 0, 4, 4,
       sql("A", "select count(*) from outbox where $__timeFilter(occurred_at)"), PG,
       thresholds=steps("blue", None),
       desc="Events written to the outbox in the selected time range (contracts/events.md).")
p.stat("Waiting", 4, 0, 4, 4,
       sql("A", "select count(*) from outbox_delivery where status = 'pending' and consumer <> 'sse'"), PG,
       thresholds=steps("green", None, "orange", 1, "red", 100),
       desc="Deliveries a consumer group has not handled yet, all time. Should be near 0. A group with no running "
            "process only grows; the Queues table says which group.")
p.stat("Oldest wait", 8, 0, 4, 4,
       sql("A", """select coalesce(extract(epoch from now() - min(o.occurred_at)), 0)
from outbox_delivery d join outbox o on o.id = d.event_id
where d.status = 'pending' and d.consumer <> 'sse'"""), PG,
       unit="s", thresholds=steps("green", None, "orange", 60, "red", 300),
       desc="How long the oldest waiting delivery has waited. Healthy: seconds.")
p.stat("Dead", 12, 0, 4, 4,
       sql("A", "select count(*) from outbox_delivery where status = 'dead'"), PG,
       thresholds=steps("green", None, "red", 1),
       desc="Deliveries whose handler failed 3 times and gave up. The table at the bottom lists them.")
p.stat("To document", 16, 0, 4, 4,
       sql("A", f"""select percentile_cont(0.5) within group (order by extract(epoch from c.occurred_at - p.occurred_at))
from outbox c join outbox p on p.id = c.causation_id
where c.type = 'document.extracted' and p.type = 'raw_item.received'
  and p.payload->>'kind' in ({OCR_KINDS}) and $__timeFilter(c.occurred_at)"""), PG,
       unit="s", decimals=0, thresholds=steps("green", None, "orange", 15, "red", 30),
       desc="Median seconds from a photo or PDF arriving to its Document: docling-serve OCR plus the gpt-oss-20b "
            "extraction. KSeF XML invoices skip OCR (about 5 s) and are left out, so they do not hide the slow path.")
p.stat("To inbox card", 20, 0, 4, 4,
       sql("A", f"""select percentile_cont(0.5) within group (order by extract(epoch from rc.occurred_at - raw.occurred_at))
  from outbox m
  join outbox raw on raw.type = 'raw_item.received' and raw.correlation_id = m.correlation_id
  join recommendations r on r.subject_id = m.payload->>'match_id'
  join outbox rc on rc.type = 'recommendation.created' and rc.payload->>'recommendation_id' = r.id
  where m.type = 'match.suggested' and raw.payload->>'kind' in ({OCR_KINDS})
    and $__timeFilter(rc.occurred_at)"""), PG,
       unit="s", decimals=0, thresholds=steps("green", None, "orange", 30, "red", 120),
       desc="Median seconds from a photo or PDF arriving to its card in the owner's inbox: the live-demo chain, "
            "target under 30 s. The last hop joins through recommendations.subject_id, because "
            "recommendation.created carries no correlation_id.")

p.add("nodeGraph", "Data flow in the time range", 0, 4, 13, 15,
      [sql("nodes", NODES), sql("edges", EDGES)], PG,
      desc="Processes and the events between them. Circle: a process; inside, what waits for it (all time) or, "
           "for a process that only sends, how many events it sent. Arrow: events from one process to another in "
           "the time range; hover it for the event types. Green: fine; orange: something waits over 2 min; red: "
           "dead deliveries. 'ui' is the browser, which gets events no worker reads (toasts, inbox badge). Use "
           "the + and - buttons to zoom, drag to move.",
      options={"nodes": {}, "edges": {}},
      overrides=[column("mainstat", ("displayName", "count")),
                 column("secondarystat", ("displayName", "dead or waiting")),
                 column("color", ("displayName", "green ok · orange waits > 2 min · red dead"))])
p.table("Queues per consumer group", 13, 4, 11, 15, sql("A", QUEUES), PG,
        custom={"align": "auto", "minWidth": 60},
        overrides=[column("Consumer group", ("custom.width", 125)),
                   column("Oldest waiting", *cell_color(steps("green", None, "orange", 60, "red", 300), "s")),
                   column("Dead", *cell_color(steps("transparent", None, "red", 1))),
                   column("Waiting", *cell_color(steps("transparent", None, "orange", 1, "red", 100)))],
        desc="outbox_delivery by consumer group, all time. 'sse' is left out: the browser stream reads by sequence "
             "and never marks its rows done.")

p.series("Events per minute by type", 0, 19, 24, 8,
         [sql("A", """select $__timeGroupAlias(occurred_at, $__interval), type as metric, count(*) as value
from outbox
where $__timeFilter(occurred_at)
group by 1, 2
order by 1""", "time_series")], PG, bars=True, stack=True, interval="1m",
         options={**LEGEND_RIGHT, "legend": {**LEGEND_RIGHT["legend"], "calcs": ["sum"],
                                             "sortBy": "Total", "sortDesc": True}},
         desc="How busy the pipeline is. A tall bar of raw_item.received is a connector backfill; drag across a "
              "region to zoom in.")
p.series("Time per stage (average)", 0, 27, 24, 8,
         [sql("A", f"""select $__timeGroupAlias(c.occurred_at, $__interval), p.type || ' → ' || c.type as metric,
  avg(extract(epoch from c.occurred_at - p.occurred_at)) as value
from outbox c
join outbox p on p.id = c.causation_id
where $__timeFilter(c.occurred_at)
group by 1, 2
union all
select $__timeGroupAlias(rc.occurred_at, $__interval), 'match.suggested → recommendation.created' as metric,
  avg(extract(epoch from rc.occurred_at - m.occurred_at)) as value
{TO_CARD}
group by 1
order by 1""", "time_series")], PG, unit="s", interval="1m",
         options={**LEGEND_RIGHT, "legend": {**LEGEND_RIGHT["legend"], "calcs": ["mean", "max"],
                                             "sortBy": "Max", "sortDesc": True}},
         desc="Seconds between an event and the event that caused it, averaged per minute. The slowest step is at "
              "the top of the legend. Event times have whole-second precision.")

p.table("Receipts and invoices, newest first", 0, 35, 24, 10, sql("A", RECEIPTS), PG,
        overrides=[column("To document", *cell_color(steps("green", None, "orange", 15, "red", 30), "s"), NOT_YET),
                   column("To match", *cell_color(steps("green", None, "orange", 20, "red", 60), "s"), NOT_YET),
                   column("To inbox card", *cell_color(steps("green", None, "orange", 30, "red", 120), "s"),
                          NOT_YET),
                   column("Received", ("unit", "dateTimeAsLocal"))],
        desc="One line per document that entered the pipeline, followed through its correlation_id: seconds from "
             "arrival to its Document, its Match and its inbox card. 'not yet': that step has not happened.")

p.table("Connectors: last sync per source", 0, 45, 12, 8, sql("A", CONNECTORS), PG,
        overrides=[column("Last run age", *cell_color(steps("green", None, "orange", 120, "red", 600), "s")),
                   column("Failed runs", *cell_color(steps("transparent", None, "red", 1)))],
        desc="Is each source still being read? Last run age should stay below a few poll intervals.")
p.table("Dead deliveries", 12, 45, 12, 8, sql("A", DEAD), PG,
        overrides=[column("Event time", ("unit", "dateTimeAsLocal"))],
        desc="Handlers that failed 3 times (contracts/events.md rule 5).")

pipeline = dashboard("ordo-pipeline", "Ordo pipeline",
                     "The data flow through the outbox: what each process sent, what waits, how long each step took.",
                     p, time_from="now-6h")


def quantile(q, metric):
    return f"histogram_quantile({q}, sum by (le) (rate({metric}_bucket{{{NS}}}[$__rate_interval])))"


m = Board()
m.stat("Model", 0, 0, 4, 4, prom("A", f'max(up{{{NS},job="gpt-oss-20b-metrics"}})'), PROM,
       thresholds=steps("red", None, "green", 1),
       mappings=[{"type": "value", "options": {"0": {"text": "Down", "color": "red"},
                                               "1": {"text": "Up", "color": "green"}}}],
       desc="Prometheus can scrape the vLLM pod of gpt-oss-20b.")
m.stat("Running", 4, 0, 4, 4, prom("A", f"sum(vllm:num_requests_running{{{NS}}})"), PROM,
       thresholds=steps("blue", None), desc="Requests gpt-oss-20b is working on right now.")
m.stat("Waiting", 8, 0, 4, 4, prom("A", f"sum(vllm:num_requests_waiting{{{NS}}})"), PROM,
       thresholds=steps("green", None, "red", 1),
       desc="Requests queued because the GPU is full. Above 0 for long = the extractor and the agents slow each "
            "other down.")
m.stat("KV cache", 12, 0, 4, 4, prom("A", f"max(vllm:kv_cache_usage_perc{{{NS}}})"), PROM,
       unit="percentunit", decimals=0, thresholds=steps("green", None, "orange", 0.7, "red", 0.9),
       desc="The model's working memory for requests in flight. Near 100 % means new requests wait.")
m.stat("First token", 16, 0, 4, 4,
       prom("A", f"max(model_name:vllm_time_to_first_token_seconds:p95_5m{{{NS}}})"), PROM,
       unit="s", decimals=2, thresholds=steps("green", None, "orange", 1, "red", 2),
       desc="p95 over 5 min of the time until the first token of an answer. Normal: under 0.25 s. Empty when "
            "there were no requests.")
m.stat("Tokens/s", 20, 0, 4, 4, prom("A", f"sum(model_name:vllm_generation_tokens:rate1m{{{NS}}})"),
       PROM, decimals=0, thresholds=steps("blue", None),
       desc="Tokens generated per second over the last minute. gpt-oss-20b does about 50 for one request on the L4.")

m.series("Time to first token", 0, 4, 12, 8,
         [prom("A", quantile(0.5, "vllm:time_to_first_token_seconds"), "p50"),
          prom("B", quantile(0.95, "vllm:time_to_first_token_seconds"), "p95")], PROM, unit="s")
m.series("Whole request", 12, 4, 12, 8,
         [prom("A", quantile(0.5, "vllm:e2e_request_latency_seconds"), "p50"),
          prom("B", quantile(0.95, "vllm:e2e_request_latency_seconds"), "p95")], PROM, unit="s")
m.series("Tokens per second", 0, 12, 12, 8,
         [prom("A", f"sum(rate(vllm:prompt_tokens_total{{{NS}}}[$__rate_interval]))", "prompt (prefill)"),
          prom("B", f"sum(rate(vllm:generation_tokens_total{{{NS}}}[$__rate_interval]))", "generated")], PROM)
m.series("Requests in vLLM", 12, 12, 12, 8,
         [prom("A", f"sum(vllm:num_requests_running{{{NS}}})", "running"),
          prom("B", f"sum(vllm:num_requests_waiting{{{NS}}})", "waiting")], PROM, decimals=0)
m.series("KV cache use", 0, 20, 12, 8, [prom("A", f"max(vllm:kv_cache_usage_perc{{{NS}}})", "KV cache")], PROM,
         unit="percentunit", min_=0, max_=1)
m.series("Answers by finish reason", 12, 20, 12, 8,
         [prom("A", f"sum by (finished_reason) (rate(vllm:request_success_total{{{NS}}}[$__rate_interval]))",
               "{{finished_reason}}")], PROM, unit="reqps", stack=True,
         desc="'length' = the answer stopped at max_tokens: not valid JSON, so extraction fails and cards fall "
              "back to templates. A guidellm run with fixed output length also shows up here.")
m.series("GPU use", 0, 28, 8, 8, [prom("A", "DCGM_FI_DEV_GPU_UTIL", "GPU {{gpu}} ({{modelName}})")], PROM,
         unit="percent", min_=0, max_=100)
m.series("GPU memory", 8, 28, 8, 8,
         [prom("A", "DCGM_FI_DEV_FB_USED", "used"), prom("B", "DCGM_FI_DEV_FB_FREE", "free")], PROM,
         unit="mbytes", stack=True, min_=0,
         desc="Flat by design: vLLM reserves 90 % of the GPU at start (--gpu-memory-utilization=0.90), so "
              "gpt-oss-20b holds about 21.7 GB of the L4's 23 GB whether busy or idle (D-12).")
m.series("GPU power and temperature", 16, 28, 8, 8,
         [prom("A", "DCGM_FI_DEV_POWER_USAGE", "power"), prom("B", "DCGM_FI_DEV_GPU_TEMP", "temperature")], PROM,
         overrides=[column("power", ("unit", "watt")),
                    column("temperature", ("unit", "celsius"), ("custom.axisPlacement", "right"))])
CONTAINERS = f'{NS},container!="",container!~"POD|git-clone|manage-dockerfile|.*build"'
m.series("CPU by container in cfo-ai", 0, 36, 12, 9,
         [prom("A", f"sum by (container) (rate(container_cpu_usage_seconds_total{{{CONTAINERS}}}[$__rate_interval]))",
               "{{container}}")], PROM, unit="short", decimals=2,
         desc="Cores. docling-serve v1.9.0 has no metrics of its own, so its CPU here is the OCR load.")
m.series("Memory by container in cfo-ai", 12, 36, 12, 9,
         [prom("A", f"sum by (container) (container_memory_working_set_bytes{{{CONTAINERS}}})", "{{container}}")],
         PROM, unit="bytes")

model = dashboard("ordo-model", "Ordo model and GPU",
                  "gpt-oss-20b on vLLM, the L4 GPU, and CPU and memory of every container in cfo-ai.",
                  m, time_from="now-3h")

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "dashboards"
out.mkdir(parents=True, exist_ok=True)
for name, board in (("ordo-pipeline.json", pipeline), ("ordo-model.json", model)):
    (out / name).write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out / name}: {len(board['panels'])} panels")
