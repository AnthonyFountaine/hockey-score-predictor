"use client";

import { useState, useCallback } from "react";
import styles from "./page.module.css";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Player {
  rank:            number;
  name:            string;
  team_abbrev:     string;
  position:        string;
  home_or_away:    string;
  goals_per_game:  number | null;
  goals_last5:     number | null;
  shots_per_game:  number | null;
  opp_ga_per_game: number | null;
  score:           number;
}

interface ListResult {
  extracted_names: string[];
  ranked_picks:    Player[];
  top_pick:        Player | null;
}

interface AnalyzeResponse {
  date:    string;
  results: {
    list1: ListResult | [];
    list2: ListResult | [];
    list3: ListResult | [];
  };
}

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const LIST_LABELS = [
  { key: "list1", label: "List 1 — Likely to Score",         color: "#2ecc71" },
  { key: "list2", label: "List 2 — Less Likely to Score",    color: "#f39c12" },
  { key: "list3", label: "List 3 — Unlikely to Score",       color: "#e74c3c" },
] as const;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(val: number | null | undefined, decimals = 3): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(decimals);
}

function scoreBar(score: number) {
  const pct = Math.round(score * 100);
  return (
    <div className={styles.scoreBar}>
      <div className={styles.scoreBarFill} style={{ width: `${pct}%` }} />
      <span className={styles.scoreLabel}>{score.toFixed(4)}</span>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function RankBadge({ rank }: { rank: number }) {
  const gold   = rank === 1;
  const silver = rank === 2;
  const bronze = rank === 3;
  return (
    <span
      className={styles.rankBadge}
      style={{
        background: gold ? "#f1c40f" : silver ? "#bdc3c7" : bronze ? "#cd7f32" : "var(--surface2)",
        color:      gold || silver || bronze ? "#0d1117" : "var(--muted)",
      }}
    >
      {rank}
    </span>
  );
}

function PlayerRow({ player }: { player: Player }) {
  return (
    <tr className={styles.playerRow}>
      <td><RankBadge rank={player.rank} /></td>
      <td className={styles.nameCell}>{player.name}</td>
      <td>{player.team_abbrev}</td>
      <td>
        <span className={styles.posBadge} data-pos={player.position[0]}>
          {player.position}
        </span>
      </td>
      <td>
        <span className={player.home_or_away === "HOME" ? styles.home : styles.away}>
          {player.home_or_away}
        </span>
      </td>
      <td className={styles.statCell}>{fmt(player.goals_per_game)}</td>
      <td className={styles.statCell}>{player.goals_last5 ?? "—"}</td>
      <td className={styles.statCell}>{fmt(player.shots_per_game, 2)}</td>
      <td className={styles.statCell}>{fmt(player.opp_ga_per_game)}</td>
      <td className={styles.scoreCell}>{scoreBar(player.score)}</td>
    </tr>
  );
}

function ImageUploadZone({
  label,
  color,
  files,
  onChange,
}: {
  label:    string;
  color:    string;
  files:    File[];
  onChange: (files: File[]) => void;
}) {
  const [dragging, setDragging] = useState(false);

  const add = (incoming: FileList | null) => {
    if (!incoming) return;
    const valid = Array.from(incoming).filter(f => f.type.startsWith("image/"));
    onChange([...files, ...valid]);
  };

  const remove = (idx: number) => {
    onChange(files.filter((_, i) => i !== idx));
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      add(e.dataTransfer.files);
    },
    [files]
  );

  return (
    <div className={styles.uploadZone} style={{ borderColor: color }}>
      <p className={styles.uploadLabel} style={{ color }}>{label}</p>

      <label
        className={styles.dropArea}
        style={{ borderColor: dragging ? color : undefined }}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={e => add(e.target.files)}
        />
        <span className={styles.dropIcon}>📸</span>
        <span className={styles.dropText}>
          {files.length === 0
            ? "Tap or drag screenshots here (multiple allowed)"
            : `${files.length} screenshot${files.length > 1 ? "s" : ""} selected`}
        </span>
      </label>

      {files.length > 0 && (
        <div className={styles.thumbRow}>
          {files.map((f, i) => (
            <div key={i} className={styles.thumb}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={URL.createObjectURL(f)} alt={f.name} />
              <button className={styles.removeBtn} onClick={() => remove(i)}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ListResultPanel({ listKey, result }: { listKey: string; result: ListResult | [] }) {
  const meta = LIST_LABELS.find(l => l.key === listKey)!;
  const res  = Array.isArray(result) ? null : result as ListResult;
  if (!res || res.ranked_picks.length === 0) return null;

  return (
    <div className={styles.listResult}>
      <h3 style={{ color: meta.color }}>{meta.label}</h3>

      {res.top_pick && (
        <div className={styles.topPick}>
          <span className={styles.topPickLabel}>⭐ Top Pick</span>
          <span className={styles.topPickName}>{res.top_pick.name}</span>
          <span className={styles.topPickTeam}>
            {res.top_pick.team_abbrev} · {res.top_pick.position} · {res.top_pick.home_or_away}
          </span>
          <span className={styles.topPickScore}>Score: {res.top_pick.score.toFixed(4)}</span>
        </div>
      )}

      <details>
        <summary className={styles.detailsSummary}>
          All {res.ranked_picks.length} matched players
        </summary>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>RK</th><th>Name</th><th>Team</th><th>Pos</th><th>H/A</th>
                <th>G/GP</th><th>L5G</th><th>SOG/G</th><th>OppGA</th><th>Score</th>
              </tr>
            </thead>
            <tbody>
              {res.ranked_picks.map(p => <PlayerRow key={p.name} player={p} />)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Home() {
  // Rankings data fetched on demand (button click) rather than SSR
  // so the page always shows live data without a server restart
  const [rankings, setRankings]   = useState<{ date: string; ranking: Player[] } | null>(null);
  const [loadingRanks, setLoadingRanks] = useState(false);
  const [ranksError, setRanksError]     = useState<string | null>(null);

  const [list1Files, setList1Files] = useState<File[]>([]);
  const [list2Files, setList2Files] = useState<File[]>([]);
  const [list3Files, setList3Files] = useState<File[]>([]);

  const [analyzing, setAnalyzing]     = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);
  const [analyzeError, setAnalyzeError]   = useState<string | null>(null);

  async function loadRankings() {
    setLoadingRanks(true);
    setRanksError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/rankings`);
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setRankings(data);
    } catch (e: unknown) {
      setRanksError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoadingRanks(false);
    }
  }

  async function analyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalyzeResult(null);

    const body = new FormData();
    list1Files.forEach(f => body.append("list1", f));
    list2Files.forEach(f => body.append("list2", f));
    list3Files.forEach(f => body.append("list3", f));

    try {
      const res  = await fetch(`${API_BASE}/api/analyze`, { method: "POST", body });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setAnalyzeResult(data);
    } catch (e: unknown) {
      setAnalyzeError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setAnalyzing(false);
    }
  }

  const hasFiles = list1Files.length + list2Files.length + list3Files.length > 0;

  return (
    <main className={styles.main}>
      {/* ── Header ── */}
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <div className={styles.logo}>
            <span className={styles.logoIcon}>🏒</span>
            <div>
              <h1 className={styles.title}>Hockey Score Predictor</h1>
              <p className={styles.subtitle}>
                Daily NHL goal-scorer rankings · powered by real stats
              </p>
            </div>
          </div>
          {rankings && (
            <span className={styles.dateBadge}>📅 {rankings.date}</span>
          )}
        </div>
      </header>

      <div className={styles.content}>

        {/* ── Full Rankings Section ── */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Tonight&apos;s Full Rankings</h2>
            <button
              className={styles.btn}
              onClick={loadRankings}
              disabled={loadingRanks}
            >
              {loadingRanks ? "Loading…" : rankings ? "↻ Refresh" : "Load Rankings"}
            </button>
          </div>

          {ranksError && <p className={styles.error}>{ranksError}</p>}

          {rankings && (
            <div className={styles.tableContainer}>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>RK</th>
                      <th>Name</th>
                      <th>Team</th>
                      <th>Pos</th>
                      <th>H/A</th>
                      <th>G/GP</th>
                      <th>L5G</th>
                      <th>SOG/G</th>
                      <th>OppGA</th>
                      <th>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rankings.ranking.map(p => (
                      <PlayerRow key={`${p.name}-${p.team_abbrev}`} player={p} />
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={styles.tableNote}>
                {rankings.ranking.length} skaters · Scroll to see all
              </p>
            </div>
          )}

          {!rankings && !loadingRanks && (
            <p className={styles.emptyState}>
              Click &ldquo;Load Rankings&rdquo; to fetch today&apos;s data.
            </p>
          )}
        </section>

        {/* ── Screenshot Upload Section ── */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Analyze Your Tim Hortons Lists</h2>
          </div>
          <p className={styles.helpText}>
            Upload screenshots of each list from the Tim Hortons app.
            You can upload multiple screenshots per list if the list spans more than one screen.
          </p>

          <div className={styles.uploadGrid}>
            {LIST_LABELS.map(({ key, label, color }) => (
              <ImageUploadZone
                key={key}
                label={label}
                color={color}
                files={key === "list1" ? list1Files : key === "list2" ? list2Files : list3Files}
                onChange={key === "list1" ? setList1Files : key === "list2" ? setList2Files : setList3Files}
              />
            ))}
          </div>

          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={analyze}
            disabled={!hasFiles || analyzing}
          >
            {analyzing ? "Analyzing screenshots…" : "⚡ Analyze & Rank My Lists"}
          </button>

          {analyzeError && <p className={styles.error}>{analyzeError}</p>}
        </section>

        {/* ── Analysis Results ── */}
        {analyzeResult && (
          <section className={styles.section}>
            <h2>Your Picks for {analyzeResult.date}</h2>
            <p className={styles.helpText}>
              Players are ranked by their composite score — pick the top player
              from each list for the best chance at a goal.
            </p>
            {LIST_LABELS.map(({ key }) => (
              <ListResultPanel
                key={key}
                listKey={key}
                result={(analyzeResult.results as Record<string, ListResult | []>)[key]}
              />
            ))}
          </section>
        )}
      </div>

      <footer className={styles.footer}>
        <p>Stats refresh daily at 3 AM ET · Data from NHL.com · Not affiliated with Tim Hortons or the NHL</p>
      </footer>
    </main>
  );
}
