"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import styles from "./player.module.css";

// ─── Types ────────────────────────────────────────────────────────────────────

interface GameLogEntry {
  gameId:         number;
  gameDate:       string;
  homeRoadFlag:   string;
  opponentAbbrev: string;
  goals:          number;
  assists:        number;
  points:         number;
  shots:          number;
  plusMinus:      number;
  toi:            string;
}

interface PlayerInfo {
  playerId:      number;
  firstName:     { default: string };
  lastName:      { default: string };
  teamAbbrev:    { default: string };
  position:      string;
  headshot:      string;
  sweaterNumber: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const BASE   = "https://api-web.nhle.com/v1";
const SEASON = "20252026";

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function nhlfetch(url: string) {
  const res = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept":     "application/json",
      "Referer":    "https://www.nhl.com/",
    },
  });
  if (!res.ok) throw new Error(`NHL API returned ${res.status}`);
  return res.json();
}

function totals(log: GameLogEntry[]) {
  const gp  = log.length;
  const g   = log.reduce((s, r) => s + r.goals,   0);
  const a   = log.reduce((s, r) => s + r.assists,  0);
  const pts = log.reduce((s, r) => s + r.points,   0);
  const sog = log.reduce((s, r) => s + r.shots,    0);
  const gpg = gp > 0 ? (g / gp).toFixed(3) : "—";
  return { gp, g, a, pts, sog, gpg };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className={styles.statCard}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}

function GameRow({ game, playoff }: { game: GameLogEntry; playoff: boolean }) {
  const scored = game.goals > 0;
  const multi  = game.goals > 1;
  return (
    <tr className={`${styles.gameRow} ${scored ? styles.scoredRow : ""}`}>
      <td className={styles.dateCell}>
        {game.gameDate}
        {playoff && <span className={styles.playoffTag}>PO</span>}
      </td>
      <td>
        <span className={game.homeRoadFlag === "H" ? styles.home : styles.away}>
          {game.homeRoadFlag === "H" ? "vs" : "@"}
        </span>
        {" "}{game.opponentAbbrev}
      </td>
      <td className={styles.goalCell}>
        {multi  ? <span className={styles.multiGoal}>{game.goals}</span>
        : scored ? <span className={styles.goalScored}>{game.goals}</span>
                 : <span className={styles.noGoal}>0</span>}
      </td>
      <td className={styles.statNum}>{game.assists}</td>
      <td className={styles.statNum}>{game.points}</td>
      <td className={styles.statNum}>{game.shots}</td>
      <td className={`${styles.statNum} ${game.plusMinus > 0 ? styles.pos : game.plusMinus < 0 ? styles.neg : ""}`}>
        {game.plusMinus > 0 ? `+${game.plusMinus}` : game.plusMinus}
      </td>
      <td className={styles.statNum}>{game.toi}</td>
    </tr>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PlayerPage() {
  const params   = useParams();
  const router   = useRouter();
  const id       = params.id as string;

  const [info,      setInfo]      = useState<PlayerInfo | null>(null);
  const [rsLog,     setRsLog]     = useState<GameLogEntry[]>([]);
  const [poLog,     setPoLog]     = useState<GameLogEntry[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [tab,       setTab]       = useState<"all" | "rs" | "po">("all");

  useEffect(() => {
    if (!id) return;
    let dead = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [landing, rsData] = await Promise.all([
          nhlfetch(`${BASE}/player/${id}/landing`),
          nhlfetch(`${BASE}/player/${id}/game-log/${SEASON}/2`),
        ]);
        if (dead) return;
        setInfo(landing);
        setRsLog(rsData.gameLog ?? []);

        // Playoff log is optional — swallow errors
        try {
          const poData = await nhlfetch(`${BASE}/player/${id}/game-log/${SEASON}/3`);
          if (!dead) setPoLog(poData.gameLog ?? []);
        } catch { /* no playoff data */ }
      } catch (e: unknown) {
        if (!dead) setError(e instanceof Error ? e.message : "Failed to load player");
      } finally {
        if (!dead) setLoading(false);
      }
    })();

    return () => { dead = true; };
  }, [id]);

  const allGames   = [...poLog, ...rsLog];
  const displayed  = tab === "rs" ? rsLog : tab === "po" ? poLog : allGames;
  const rsStats    = totals(rsLog);
  const poStats    = totals(poLog);
  const firstName  = info?.firstName?.default  ?? "";
  const lastName   = info?.lastName?.default   ?? "";
  const fullName   = [firstName, lastName].filter(Boolean).join(" ") || "Player";

  return (
    <main className={styles.main}>

      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => router.back()}>
          ← Back to Rankings
        </button>
        <span className={styles.topBarTitle}>🏒 Hockey Score Predictor</span>
      </div>

      {loading && <p className={styles.centred}>Loading…</p>}
      {error   && <p className={styles.centredError}>{error}</p>}

      {!loading && !error && info && (
        <div className={styles.content}>

          {/* ── Header ── */}
          <div className={styles.playerHeader}>
            {info.headshot && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={info.headshot} alt={fullName} className={styles.headshot} />
            )}
            <div className={styles.playerMeta}>
              <h1 className={styles.playerName}>{fullName}</h1>
              <div className={styles.tags}>
                <span className={styles.tag}>#{info.sweaterNumber}</span>
                <span className={styles.tag}>{info.teamAbbrev?.default}</span>
                <span className={styles.tag}>{info.position}</span>
              </div>
            </div>
          </div>

          {/* ── Summary cards ── */}
          <div className={styles.summaryGrid}>
            <div className={styles.summaryBlock}>
              <p className={styles.summaryTitle}>
                Regular Season {SEASON.slice(0, 4)}–{SEASON.slice(4)}
              </p>
              <div className={styles.statCards}>
                <StatCard label="GP"   value={rsStats.gp}  />
                <StatCard label="G"    value={rsStats.g}   />
                <StatCard label="A"    value={rsStats.a}   />
                <StatCard label="PTS"  value={rsStats.pts} />
                <StatCard label="G/GP" value={rsStats.gpg} />
              </div>
            </div>

            {poLog.length > 0 && (
              <div className={styles.summaryBlock}>
                <p className={styles.summaryTitle}>
                  Playoffs {SEASON.slice(0, 4)}–{SEASON.slice(4)}
                </p>
                <div className={styles.statCards}>
                  <StatCard label="GP"   value={poStats.gp}  />
                  <StatCard label="G"    value={poStats.g}   />
                  <StatCard label="A"    value={poStats.a}   />
                  <StatCard label="PTS"  value={poStats.pts} />
                  <StatCard label="G/GP" value={poStats.gpg} />
                </div>
              </div>
            )}
          </div>

          {/* ── Tabs ── */}
          <div className={styles.tabs}>
            {(["all", "rs", ...(poLog.length > 0 ? ["po"] : [])] as const).map(t => (
              <button
                key={t}
                className={`${styles.tab} ${tab === t ? styles.tabActive : ""}`}
                onClick={() => setTab(t)}
              >
                {t === "all" ? `All Games (${allGames.length})`
                 : t === "rs" ? `Regular Season (${rsLog.length})`
                 : `Playoffs (${poLog.length})`}
              </button>
            ))}
          </div>

          {/* ── Game log ── */}
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Date</th><th>Opp</th><th>G</th><th>A</th>
                  <th>PTS</th><th>SOG</th><th>+/-</th><th>TOI</th>
                </tr>
              </thead>
              <tbody>
                {displayed.length === 0
                  ? <tr><td colSpan={8} className={styles.noData}>No games to display.</td></tr>
                  : displayed.map((g, i) => (
                    <GameRow
                      key={`${g.gameId}-${i}`}
                      game={g}
                      playoff={tab === "all" ? i < poLog.length : tab === "po"}
                    />
                  ))
                }
              </tbody>
            </table>
          </div>

        </div>
      )}
    </main>
  );
}
