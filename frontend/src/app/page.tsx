"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "./page.module.css";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Player {
  rank:            number;
  player_id:       number | null;
  name:            string;
  team_abbrev:     string;
  position:        string;
  home_or_away:    string;
  goals_per_game:  number | null;
  points_per_game: number | null;
  goals_last5:     number | null;
  shots_per_game:  number | null;
  shooting_pct:    number | null;
  power_play_goals_per_game:  number | null;
  power_play_points_per_game: number | null;
  avg_toi_minutes: number | null;
  last5_shots_per_game: number | null;
  last5_points:    number | null;
  opp_ga_per_game: number | null;
  opp_save_pct:    number | null;
  in_playoffs:     boolean;
  score:           number;
}

interface ListResult {
  ranked_picks: Player[];
  top_pick:     Player | null;
}

interface AnalyzeResponse {
  date:    string;
  results: {
    list1: ListResult;
    list2: ListResult;
    list3: ListResult;
  };
}

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const LIST_LABELS = [
  { key: "list1", label: "List 1 — Likely to Score",      color: "#2ecc71" },
  { key: "list2", label: "List 2 — Less Likely to Score", color: "#f39c12" },
  { key: "list3", label: "List 3 — Unlikely to Score",    color: "#e74c3c" },
] as const;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function scoreBar(score: number) {
  const pct = Math.round(score * 100);
  return (
    <div className={styles.scoreBar}>
      <div className={styles.scoreBarFill} style={{ width: `${pct}%` }} />
      <span className={styles.scoreLabel}>{score.toFixed(4)}</span>
    </div>
  );
}

const INFLUENTIAL_STATS = [
  { key: "goals_per_game", weightKey: "gpg_bayesian", label: "G/GP", decimals: 3 },
  { key: "shots_per_game", weightKey: "shots_per_game", label: "SOG/G", decimals: 2 },
  { key: "goals_last5", weightKey: "goals_last5", label: "L5G", decimals: 0 },
  { key: "points_per_game", weightKey: "points_per_game", label: "P/GP", decimals: 3 },
  { key: "power_play_goals_per_game", weightKey: "power_play_goals_per_game", label: "PPG/G", decimals: 3 },
  { key: "avg_toi_minutes", weightKey: "avg_toi_minutes", label: "TOI", decimals: 1 },
  { key: "shooting_pct", weightKey: "shooting_pct", label: "SH%", decimals: 3 },
  { key: "last5_shots_per_game", weightKey: "last5_shots_per_game", label: "L5 SOG/G", decimals: 2 },
  { key: "last5_points", weightKey: "last5_points", label: "L5 PTS", decimals: 0 },
  { key: "opp_ga_per_game", weightKey: "opp_ga_per_game", label: "Opp GA/G", decimals: 3 },
  { key: "opp_save_pct", weightKey: "opp_save_pct", label: "Opp SV%", decimals: 3 },
  { key: "power_play_points_per_game", weightKey: "power_play_points_per_game", label: "PPP/G", decimals: 3 },
  { key: "home_or_away", weightKey: "home_binary", label: "H/A", decimals: 0 },
] as const;

type StatKey = (typeof INFLUENTIAL_STATS)[number]["key"];
type StatColumn = (typeof INFLUENTIAL_STATS)[number];

function statColumns(featureWeights?: Record<string, number>): StatColumn[] {
  if (!featureWeights) return [...INFLUENTIAL_STATS];
  return [...INFLUENTIAL_STATS].sort((a, b) => {
    const weightDiff = (featureWeights[b.weightKey] ?? 0) - (featureWeights[a.weightKey] ?? 0);
    return weightDiff || INFLUENTIAL_STATS.indexOf(a) - INFLUENTIAL_STATS.indexOf(b);
  });
}

function renderStat(player: Player, key: StatKey, decimals: number) {
  if (key === "home_or_away") {
    return (
      <span className={player.home_or_away === "HOME" ? styles.home : styles.away}>
        {player.home_or_away}
      </span>
    );
  }
  const value = player[key];
  if (typeof value !== "number") return "—";
  return decimals === 0 ? value.toString() : value.toFixed(decimals);
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

function PlayerRow({ player, columns = INFLUENTIAL_STATS }: { player: Player; columns?: readonly StatColumn[] }) {
  const profileHref = player.player_id ? `/player/${player.player_id}` : null;

  return (
    <tr className={styles.playerRow}>
      <td><RankBadge rank={player.rank} /></td>
      <td className={styles.nameCell}>
        {profileHref
          ? <Link href={profileHref} className={styles.playerLink}>{player.name}</Link>
          : player.name}
      </td>
      <td>{player.team_abbrev}</td>
      <td>
        <span className={styles.posBadge} data-pos={player.position[0]}>
          {player.position}
        </span>
      </td>
      <td className={styles.scoreCell}>{scoreBar(player.score)}</td>
      {columns.map(stat => (
        <td className={styles.statCell} key={stat.key}>
          {renderStat(player, stat.key, stat.decimals)}
        </td>
      ))}
    </tr>
  );
}

function PlayerInputZone({
  label,
  color,
  value,
  onChange,
  placeholder,
}: {
  label:       string;
  color:       string;
  value:       string;
  onChange:    (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className={styles.inputZone} style={{ borderColor: color }}>
      <label className={styles.inputLabel} style={{ color }}>{label}</label>
      <p className={styles.inputHint}>One player name per line</p>
      <textarea
        className={styles.playerTextarea}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        rows={6}
        spellCheck={false}
      />
    </div>
  );
}

function ListResultPanel({ listKey, result }: { listKey: string; result: ListResult }) {
  const meta = LIST_LABELS.find(l => l.key === listKey)!;
  if (!result || result.ranked_picks.length === 0) return null;

  return (
    <div className={styles.listResult}>
      <h3 style={{ color: meta.color }}>{meta.label}</h3>

      {result.top_pick && (
        <div className={styles.topPick}>
          <span className={styles.topPickLabel}>⭐ Top Pick</span>
          <span className={styles.topPickName}>{result.top_pick.name}</span>
          <span className={styles.topPickTeam}>
            {result.top_pick.team_abbrev} · {result.top_pick.position} · {result.top_pick.home_or_away}
          </span>
          <span className={styles.topPickScore}>Score: {result.top_pick.score.toFixed(4)}</span>
        </div>
      )}

      <details>
        <summary className={styles.detailsSummary}>
          All {result.ranked_picks.length} matched players
        </summary>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>RK</th><th>Name</th><th>Team</th><th>Pos</th><th>Score</th>
                {INFLUENTIAL_STATS.map(stat => <th key={stat.key}>{stat.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {result.ranked_picks.map(p => <PlayerRow key={p.name} player={p} />)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [rankings, setRankings]         = useState<{ date: string; ranking: Player[]; feature_weights?: Record<string, number>; message?: string } | null>(null);
  const [loadingRanks, setLoadingRanks] = useState(false);
  const [ranksError, setRanksError]     = useState<string | null>(null);

  const [list1Text, setList1Text] = useState("");
  const [list2Text, setList2Text] = useState("");
  const [list3Text, setList3Text] = useState("");

  const [analyzing, setAnalyzing]         = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);
  const [analyzeError, setAnalyzeError]   = useState<string | null>(null);

  async function loadRankings() {
    setLoadingRanks(true);
    setRanksError(null);
    try {
      // Fetch directly from GitHub — always reflects the latest commit,
      // no Render redeploy needed. Add a cache-bust so the browser
      // doesn't serve a stale version from earlier today.
      const url = `https://raw.githubusercontent.com/${process.env.NEXT_PUBLIC_GITHUB_USER}/${process.env.NEXT_PUBLIC_GITHUB_REPO}/main/data/rankings.json?t=${Date.now()}`;
      const res  = await fetch(url);
      if (!res.ok) throw new Error(`Could not load rankings (${res.status})`);
      const data = await res.json();
      setRankings(data);
    } catch (e: unknown) {
      setRanksError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoadingRanks(false);
    }
  }

  // Parse a textarea value into an array of non-empty trimmed name strings
  function parseNames(raw: string): string[] {
    return raw.split("\n").map(l => l.trim()).filter(Boolean);
  }

  async function analyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalyzeResult(null);

    const body = {
      list1: parseNames(list1Text),
      list2: parseNames(list2Text),
      list3: parseNames(list3Text),
    };

    try {
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setAnalyzeResult(data);
    } catch (e: unknown) {
      setAnalyzeError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setAnalyzing(false);
    }
  }

  const hasNames = list1Text.trim() || list2Text.trim() || list3Text.trim();
  const rankingColumns = statColumns(rankings?.feature_weights);

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

          {rankings && rankings.message && (
            <div className={styles.noGamesMsg}>
              <span className={styles.noGamesIcon}>🏒</span>
              <p>No NHL games scheduled today.</p>
              <p className={styles.noGamesSub}>Check back tomorrow — rankings update every morning at 3 AM ET.</p>
            </div>
          )}

          {rankings && !rankings.message && rankings.ranking.length > 0 && (
            <div className={styles.tableContainer}>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>RK</th><th>Name</th><th>Team</th><th>Pos</th><th>Score</th>
                      {rankingColumns.map(stat => <th key={stat.key}>{stat.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rankings.ranking.map(p => (
                      <PlayerRow key={`${p.name}-${p.team_abbrev}`} player={p} columns={rankingColumns} />
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

        {/* ── Name Entry Section ── */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>Analyze Your Tim Hortons Lists</h2>
          </div>
          <p className={styles.helpText}>
            Open the Tim Hortons app and type the players from each list below —
            one name per line. Last name only works fine (e.g. &ldquo;Matthews&rdquo;).
          </p>

          <div className={styles.inputGrid}>
            <PlayerInputZone
              label="List 1 — Likely to Score"
              color="#2ecc71"
              value={list1Text}
              onChange={setList1Text}
              placeholder={"Matthews\nMcDavid\nOvechkin"}
            />
            <PlayerInputZone
              label="List 2 — Less Likely to Score"
              color="#f39c12"
              value={list2Text}
              onChange={setList2Text}
              placeholder={"Hedman\nFox\nMakar"}
            />
            <PlayerInputZone
              label="List 3 — Unlikely to Score"
              color="#e74c3c"
              value={list3Text}
              onChange={setList3Text}
              placeholder={"Tkachuk\nBarzal\nPastrnak"}
            />
          </div>

          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={analyze}
            disabled={!hasNames || analyzing}
          >
            {analyzing ? "Ranking…" : "⚡ Get My Best Picks"}
          </button>

          {analyzeError && <p className={styles.error}>{analyzeError}</p>}
        </section>

        {/* ── Analysis Results ── */}
        {analyzeResult && (
          <section className={styles.section}>
            <h2>Your Picks for {analyzeResult.date}</h2>
            <p className={styles.helpText}>
              Players are ranked by their composite score — pick the ⭐ top player
              from each list for the best chance at a goal tonight.
            </p>
            {LIST_LABELS.map(({ key }) => (
              <ListResultPanel
                key={key}
                listKey={key}
                result={(analyzeResult.results as Record<string, ListResult>)[key]}
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
