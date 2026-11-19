import { DatabaseSync } from "node:sqlite";
import { mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Build a deterministic, evenly spaced sample from the full scraped index.
// The output is a real SQLite index usable by the High Court APIs.
const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(process.argv[2] || resolve(here, "../../high_court_decisions.sqlite3"));
const outputPath = resolve(process.argv[3] || resolve(here, "high_court_decisions.sqlite3"));
const stride = Math.max(2, Number(process.argv[4] || 32));

const source = new DatabaseSync(sourcePath, { readOnly: true });
const sourceTotals = source.prepare("SELECT total_cases FROM high_court_overview_stats WHERE id = 1").get();
if (!sourceTotals) throw new Error(`No High Court index summary found in ${sourcePath}`);

mkdirSync(dirname(outputPath), { recursive: true });
rmSync(outputPath, { force: true });
rmSync(`${outputPath}-journal`, { force: true });
rmSync(`${outputPath}-wal`, { force: true });
rmSync(`${outputPath}-shm`, { force: true });
const target = new DatabaseSync(outputPath);
target.exec("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY;");

const decisionsSql = source.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'").get()?.sql;
const judgesSql = source.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='high_court_judges'").get()?.sql;
if (!decisionsSql || !judgesSql) throw new Error("Source index is missing required tables.");
target.exec(decisionsSql);
target.exec(judgesSql);
target.exec(`
  CREATE TABLE decision_judges (
    decision_id INTEGER NOT NULL,
    normalized_name TEXT NOT NULL,
    PRIMARY KEY (decision_id, normalized_name)
  ) WITHOUT ROWID;
  CREATE TABLE high_court_overview_stats (
    id INTEGER PRIMARY KEY CHECK (id = 1), total_cases INTEGER NOT NULL,
    total_judges INTEGER NOT NULL, rows_with_judge INTEGER NOT NULL,
    rows_with_disposition INTEGER NOT NULL, candidate_appeals INTEGER NOT NULL,
    classified_appeals INTEGER NOT NULL, upheld INTEGER NOT NULL,
    set_aside INTEGER NOT NULL, modified INTEGER NOT NULL
  );
  CREATE TABLE high_court_judge_stats (
    normalized_name TEXT PRIMARY KEY, record_count INTEGER NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, court_names TEXT NOT NULL
  );
  CREATE TABLE high_court_judge_outcomes (
    normalized_name TEXT PRIMARY KEY, candidate_appeals INTEGER NOT NULL,
    classified_appeals INTEGER NOT NULL, upheld INTEGER NOT NULL,
    set_aside INTEGER NOT NULL, modified INTEGER NOT NULL
  );
  CREATE TABLE high_court_judge_metrics (
    normalized_name TEXT PRIMARY KEY, median_duration_days REAL,
    max_duration_days INTEGER, duration_records INTEGER NOT NULL
  );
`);

const columns = [
  "id", "case_title", "docket_number", "cnr_number", "citation", "court_name",
  "court_code", "bench_name", "judge_names", "judge_search_text",
  "party_petitioner", "party_respondent", "decision_date", "registration_date",
  "disposition_text", "source_pdf_url",
];
const copyDecision = target.prepare(`INSERT INTO decisions (${columns.join(",")}) VALUES (${columns.map(() => "?").join(",")})`);
const decisionRows = source.prepare(`
  SELECT d.id, d.case_title, d.docket_number, d.cnr_number, d.citation, d.court_name,
         d.court_code, d.bench_name,
         COALESCE((SELECT group_concat(j.judge_name, ' | ')
                   FROM decision_judges dj JOIN high_court_judges j USING (normalized_name)
                   WHERE dj.decision_id=d.id), '') AS judge_names,
         COALESCE((SELECT '|' || group_concat(dj.normalized_name, '|') || '|'
                   FROM decision_judges dj WHERE dj.decision_id=d.id), '') AS judge_search_text,
         d.party_petitioner, d.party_respondent, d.decision_date, d.registration_date,
         d.disposition_text, NULL AS source_pdf_url
  FROM decisions d WHERE d.id % ? = 0 ORDER BY d.id
`);
let copied = 0;
target.exec("BEGIN");
for (const row of decisionRows.iterate(stride)) {
  copyDecision.run(...columns.map((column) => row[column] ?? null));
  copied += 1;
  if (copied % 50000 === 0) console.log(`Sampled records: ${copied.toLocaleString()}`);
}
const copyLink = target.prepare("INSERT INTO decision_judges VALUES (?, ?)");
const copyJudge = target.prepare("INSERT INTO high_court_judges VALUES (?, ?, ?, ?)");
const seenJudges = new Set();
for (const row of source.prepare(`
  SELECT dj.decision_id, dj.normalized_name, j.judge_name, j.criminal_cases, j.conviction_cases
  FROM decision_judges dj JOIN high_court_judges j USING (normalized_name)
  WHERE dj.decision_id % ? = 0 ORDER BY dj.decision_id, dj.normalized_name
`).iterate(stride)) {
  copyLink.run(row.decision_id, row.normalized_name);
  if (!seenJudges.has(row.normalized_name)) {
    copyJudge.run(row.normalized_name, row.judge_name, row.criminal_cases, row.conviction_cases);
    seenJudges.add(row.normalized_name);
  }
}
target.exec("COMMIT");

target.exec("BEGIN");
const cleanToken = (value) => String(value || "").replace(/[^A-Z0-9]+/gi, " ").trim();
const government = /^(?:THE\s+)?(?:STATE(?:\s+\(NCT\))?(?:\s+OF\b|\s+REP(?:RESENTED)?\b|\s+GOVT\b|$)|UNION\s+OF\s+INDIA\b|CENTRAL\s+BURO?EAU\b|CBI\b|DIRECTORATE\s+OF\s+ENFORCEMENT\b|ENFORCEMENT\s+DIRECTORATE\b|NARCOTICS\s+CONTROL\s+BURO?EAU\b|CUSTOMS\b|INCOME\s+TAX\b|GOVERNMENT\s+OF\b|GOVT\.?\s+OF\b|(?:INSPECTOR|OFFICER|SUPERINTENDENT|STATION\s+HOUSE\s+OFFICER)\s+OF\s+POLICE\b|POLICE\s+STATION\b|PUBLIC\s+PROSECUTOR\b|STATE\s+PROSECUTOR\b)/i;
const appeal = /\b(?:CRL\.?\s*(?:A|APPEAL)(?:\s*\([^)]+\))?|C\.?\s*R\.?\s*A\.?|CR\.?\s*(?:APP(?:EAL)?|A)|CRIMINAL\s+APPEAL|CRA)\b/i;
function outcome(row) {
  const docket = row.docket_number || "";
  const petitioner = String(row.party_petitioner || "").trim();
  const respondent = String(row.party_respondent || "").trim();
  const rawDisposition = String(row.disposition_text || "").trim();
  if (!appeal.test(docket) || !petitioner || !respondent || !rawDisposition || government.test(petitioner) || !government.test(respondent)) return null;
  const disposition = cleanToken(rawDisposition.toUpperCase());
  if (/\b(?:ACQUITTED|CONVICTION SET ASIDE|CONVICTION REVERSED|CONVICTION QUASHED|CONVICTION OVERTURNED)\b/.test(disposition)) return "set_aside";
  if (/\b(?:CONVICTION MODIFIED|SENTENCE REDUCED|SENTENCE MODIFIED|SENTENCE ALTERED|PARTLY ALLOWED|PARTIALLY ALLOWED)\b/.test(disposition)) return "modified";
  if (/\b(?:ADMISSION STAGE|ADM STAGE|DEFAULT|WITHDRAWN|GRANTED|ADMITTED|REMANDED|REMAND|DE NOVO)\b/.test(disposition)) return null;
  if (/\b(?:DISMISSED|RULE DISCHARGED|CONVICTION AFFIRMED|CONVICTION UPHELD|SENTENCE CONFIRMED)\b/.test(disposition)) return "upheld";
  if (/\b(?:ALLOWED|RULE ABSOLUTE)\b/.test(disposition)) return "set_aside";
  return null;
}
function parsedDay(value) {
  const match = String(value || "").slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? Math.floor((Date.UTC(+match[1], +match[2] - 1, +match[3]) - Date.UTC(1970, 0, 1)) / 86400000) : null;
}
const stats = new Map();
const totals = { rowsWithJudge: 0, rowsWithDisposition: 0, candidate: 0, upheld: 0, setAside: 0, modified: 0 };
const rows = target.prepare(`
  SELECT d.*, group_concat(dj.normalized_name, char(31)) AS linked_names
  FROM decisions d LEFT JOIN decision_judges dj ON dj.decision_id=d.id
  GROUP BY d.id ORDER BY d.id
`);
for (const row of rows.iterate()) {
  const names = row.linked_names ? row.linked_names.split("\x1f").filter(Boolean) : [];
  const disposition = String(row.disposition_text || "").trim();
  totals.rowsWithJudge += names.length > 0 ? 1 : 0;
  totals.rowsWithDisposition += disposition ? 1 : 0;
  const isCandidate = appeal.test(row.docket_number || "")
    && Boolean(String(row.party_petitioner || "").trim())
    && Boolean(String(row.party_respondent || "").trim())
    && Boolean(disposition)
    && !government.test(row.party_petitioner || "")
    && government.test(row.party_respondent || "");
  const result = outcome(row);
  if (isCandidate) totals.candidate += 1;
  if (result === "upheld") totals.upheld += 1;
  if (result === "set_aside") totals.setAside += 1;
  if (result === "modified") totals.modified += 1;
  const decisionDay = parsedDay(row.decision_date);
  const filedDay = parsedDay(row.registration_date);
  const duration = decisionDay !== null && filedDay !== null && decisionDay >= filedDay ? decisionDay - filedDay : null;
  for (const name of names) {
    let item = stats.get(name);
    if (!item) {
      item = { records: 0, first: "", last: "", courts: new Set(), durations: [], candidate: 0, upheld: 0, setAside: 0, modified: 0, criminal: 0 };
      stats.set(name, item);
    }
    item.records += 1;
    if (row.decision_date && (!item.first || row.decision_date < item.first)) item.first = row.decision_date;
    if (row.decision_date && row.decision_date > item.last) item.last = row.decision_date;
    if (row.court_name) item.courts.add(row.court_name);
    if (duration !== null) item.durations.push(duration);
    if (/^(?:CRL|CRIM|CRIMINAL|CR|BAIL|NDPS|POCSO)\b/i.test(String(row.docket_number || "").replace(/[^A-Z0-9]+/gi, " ").trim()) && disposition) item.criminal += 1;
    if (isCandidate) item.candidate += 1;
    if (result === "upheld") item.upheld += 1;
    if (result === "set_aside") item.setAside += 1;
    if (result === "modified") item.modified += 1;
  }
}
const insertStats = target.prepare("INSERT INTO high_court_judge_stats VALUES (?, ?, ?, ?, ?)");
const insertOutcomes = target.prepare("INSERT INTO high_court_judge_outcomes VALUES (?, ?, ?, ?, ?, ?)");
const insertMetrics = target.prepare("INSERT INTO high_court_judge_metrics VALUES (?, ?, ?, ?)");
const updateJudgeBase = target.prepare("UPDATE high_court_judges SET criminal_cases=?, conviction_cases=? WHERE normalized_name=?");
const median = (values) => {
  if (!values.length) return null;
  values.sort((a, b) => a - b);
  const mid = Math.floor(values.length / 2);
  return values.length % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
};
for (const [name, item] of stats) {
  const classified = item.upheld + item.setAside + item.modified;
  insertStats.run(name, item.records, item.first, item.last, JSON.stringify([...item.courts].sort()));
  insertOutcomes.run(name, item.candidate, classified, item.upheld, item.setAside, item.modified);
  insertMetrics.run(name, median(item.durations), item.durations.length ? item.durations.reduce((max, value) => Math.max(max, value), 0) : null, item.durations.length);
  updateJudgeBase.run(item.criminal, item.upheld + item.modified, name);
}
const classified = totals.upheld + totals.setAside + totals.modified;
target.prepare("INSERT INTO high_court_overview_stats VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
  copied, stats.size, totals.rowsWithJudge, totals.rowsWithDisposition,
  totals.candidate, classified, totals.upheld, totals.setAside, totals.modified,
);
target.exec("COMMIT");

target.exec(`
  CREATE INDEX idx_decision_judges_name_id ON decision_judges(normalized_name, decision_id);
  CREATE INDEX idx_decisions_court ON decisions(court_name);
  CREATE INDEX idx_decisions_court_cnr ON decisions(court_name, cnr_number);
  CREATE INDEX idx_decisions_judge_date ON decisions(judge_search_text, decision_date DESC);
  ANALYZE;
  VACUUM;
`);
const result = {
  sourcePath, outputPath, samplingRule: `decision id divisible by ${stride}`,
  sourceRecords: Number(sourceTotals.total_cases), sampleRecords: copied,
  sampleJudges: stats.size, rowsWithJudge: totals.rowsWithJudge,
  classifiableAppeals: classified, convictionUpheld: totals.upheld,
  setAside: totals.setAside, modified: totals.modified,
  bytes: statSync(outputPath).size,
};
const range = target.prepare("SELECT MIN(decision_date) AS first_date, MAX(decision_date) AS last_date FROM decisions").get();
result.firstDecisionDate = range.first_date || null;
result.lastDecisionDate = range.last_date || null;
const mb = (result.bytes / (1024 * 1024)).toFixed(1);
writeFileSync(resolve(here, "demo-data-details.md"), `# Demo data details\n\n- Source: scraped High Court records from the project’s merged SQLite index.\n- Sample rule: retain records whose source index ID is divisible by ${stride}; this gives a reproducible spread across the source index.\n- Source index records: ${Number(sourceTotals.total_cases).toLocaleString("en-IN")}\n- Demo records: ${copied.toLocaleString("en-IN")}\n- Judges represented: ${stats.size.toLocaleString("en-IN")}\n- Records with a judge: ${totals.rowsWithJudge.toLocaleString("en-IN")}\n- Classified appeal outcomes: ${classified.toLocaleString("en-IN")} (upheld ${totals.upheld.toLocaleString("en-IN")}, set aside ${totals.setAside.toLocaleString("en-IN")}, modified ${totals.modified.toLocaleString("en-IN")})\n- Decision dates represented: ${range.first_date || "not recorded"} to ${range.last_date || "not recorded"}\n- SQLite file size: ${mb} MiB\n\nThis is a sample for demonstrating the app, not the complete High Court index. The app’s outcome figures are estimates derived from scraped docket, party, and disposition text; they are not verified trial-court conviction rates. The sample contains case metadata, not judgment PDF contents.\n`);
target.close();
source.close();
console.log(JSON.stringify(result, null, 2));
