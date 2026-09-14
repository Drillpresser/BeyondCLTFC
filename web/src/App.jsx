import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const PHASE_COLORS = { before: "#9aa0a6", during: "#1e90ff", after: "#f5a623" };

const num = (v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v));

// Normalise a season row from any source (ASA / Wikipedia / FBref) into a
// common shape so the before/during/after timeline can mix them.
function seasonMetrics(s) {
  if (s.source === "asa") {
    const x = s.xgoals || {};
    return { goals: num(x.goals), xg: num(x.xgoals), minutes: num(x.minutes ?? x.minutes_played), apps: null };
  }
  if (s.source === "wikipedia") {
    const w = s.wikipedia || {};
    return { goals: num(w.goals), xg: null, minutes: null, apps: num(w.apps) };
  }
  if (s.source === "fbref") {
    const f = s.fbref || {};
    return { goals: num(f.goals), xg: num(f.xg), minutes: num(f.minutes), apps: num(f.mp) };
  }
  return { goals: null, xg: null, minutes: null, apps: null };
}

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/players.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setSelectedId(d.players?.[0]?.player_id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  const player = useMemo(
    () => data?.players?.find((p) => p.player_id === selectedId) ?? null,
    [data, selectedId]
  );

  // One bar per calendar year, aggregating rows that share a year (e.g. a
  // mid-season transfer, or overlapping ASA + Wikipedia rows).
  const chartData = useMemo(() => {
    if (!player) return [];
    const byYear = new Map();
    for (const s of player.seasons) {
      const m = seasonMetrics(s);
      const y = byYear.get(s.season) || {
        season: s.season,
        phase: s.phase,
        goals: 0,
        xgoals: 0,
        apps: 0,
        teams: new Set(),
      };
      // "during" wins the color if any row that year is a CLTFC season.
      if (s.phase === "during") y.phase = "during";
      y.goals += m.goals ?? 0;
      y.xgoals += m.xg ?? 0;
      y.apps += m.apps ?? 0;
      if (s.team) y.teams.add(s.team);
      byYear.set(s.season, y);
    }
    return [...byYear.values()]
      .sort((a, b) => a.season - b.season)
      .map((y) => ({ ...y, team: [...y.teams].join(", ") }));
  }, [player]);

  const phaseSummary = useMemo(() => {
    const acc = { before: [], during: [], after: [] };
    chartData.forEach((d) => acc[d.phase]?.push(d));
    return Object.entries(acc).map(([phase, rows]) => {
      const goals = rows.reduce((t, r) => t + r.goals, 0);
      const xg = rows.reduce((t, r) => t + r.xgoals, 0);
      const apps = rows.reduce((t, r) => t + r.apps, 0);
      return {
        phase,
        seasons: rows.length,
        goals: +goals.toFixed(1),
        xgoals: +xg.toFixed(2),
        apps,
        perApp: apps ? +(goals / apps).toFixed(2) : 0,
      };
    });
  }, [chartData]);

  if (error)
    return (
      <div className="wrap">
        <h1>BeyondCLTFC</h1>
        <p className="error">Couldn't load data: {error}</p>
        <p>Run the pipeline in <code>scripts/</code> to generate <code>data/players.json</code>.</p>
      </div>
    );
  if (!data) return <div className="wrap">Loading…</div>;

  return (
    <div className="wrap">
      <header>
        <h1>BeyondCLTFC</h1>
        <p className="sub">
          {data.club} players — performance <em>before</em>, <em>during</em>, and{" "}
          <em>after</em> their time at the club. {data.player_count} players tracked.
        </p>
      </header>

      <div className="layout">
        <aside>
          <input
            className="search"
            placeholder="Filter players…"
            onChange={(e) => {
              const q = e.target.value.toLowerCase();
              const hit = data.players.find((p) => p.name?.toLowerCase().includes(q));
              if (hit && q) setSelectedId(hit.player_id);
            }}
          />
          <ul className="playerlist">
            {data.players.map((p) => (
              <li key={p.player_id}>
                <button
                  className={p.player_id === selectedId ? "active" : ""}
                  onClick={() => setSelectedId(p.player_id)}
                >
                  {p.name}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main>
          {player && (
            <>
              <h2>{player.name}</h2>
              <p className="tenure">
                CLTFC tenure: {player.tenure.start}–{player.tenure.end ?? "present"}
              </p>

              <div className="summary">
                {phaseSummary.map((s) => (
                  <div className="card" key={s.phase} style={{ borderColor: PHASE_COLORS[s.phase] }}>
                    <div className="phase" style={{ color: PHASE_COLORS[s.phase] }}>
                      {s.phase}
                    </div>
                    <div className="big">{s.goals} G</div>
                    <div className="small">
                      {s.seasons} seasons · {s.apps} apps · {s.perApp} G/app
                      {s.xgoals ? ` · ${s.xgoals} xG` : ""}
                    </div>
                  </div>
                ))}
              </div>

              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                  <XAxis dataKey="season" />
                  <YAxis />
                  <Tooltip
                    formatter={(v, n) => [v, n]}
                    labelFormatter={(l, payload) =>
                      `${l} — ${payload?.[0]?.payload?.team ?? ""} (${payload?.[0]?.payload?.phase ?? ""})`
                    }
                  />
                  <Legend />
                  <Bar dataKey="goals" name="Goals">
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={PHASE_COLORS[d.phase]} />
                    ))}
                  </Bar>
                  <Bar dataKey="xgoals" name="xG" fill="#c9d6e5" />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
