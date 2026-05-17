import { NextResponse } from "next/server";

const BASE = "https://api-web.nhle.com/v1";
const SEASON = "20252026";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function nhlFetch(path: string) {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: {
      "Accept": "application/json",
      "User-Agent": "Mozilla/5.0 Hockey Score Predictor",
      "Referer": "https://www.nhl.com/",
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`NHL API returned ${res.status} for ${path}: ${body.slice(0, 160)}`);
  }

  return res.json();
}

async function optionalNhlFetch(path: string) {
  try {
    return await nhlFetch(path);
  } catch {
    return null;
  }
}

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const { id } = params;

  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ error: "Invalid player ID" }, { status: 400 });
  }

  try {
    const [landing, rsData, poData] = await Promise.all([
      nhlFetch(`/player/${id}/landing`),
      optionalNhlFetch(`/player/${id}/game-log/${SEASON}/2`),
      optionalNhlFetch(`/player/${id}/game-log/${SEASON}/3`),
    ]);

    return NextResponse.json({
      player: landing,
      regularSeasonLog: rsData?.gameLog ?? [],
      playoffLog: poData?.gameLog ?? [],
      season: SEASON,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to load player profile";

    return NextResponse.json({ error: message }, { status: 502 });
  }
}
