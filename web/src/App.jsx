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

// Pull a numeric stat from an ASA xgoals blob, tolerant of key naming.
function stat(season, keys) {
  const x = season.xgoals || {};
  for (const k of keys) {
    if (x[k] != null && !Number.isNaN(Number(x[k]))) return Number(x[k]);
  }
  return 0;
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

  const chartData = useMemo(() => {
    if (!player) return [];
    return player.seasons.map((s) => ({
      season: s.season,
      phase: s.phase,
      team: s.team,
      goals: stat(s, ["goals"]),
      xgoals: stat(s, ["xgoals"]),
      minutes: stat(s, ["minutes", "minutes_played"]),
    }));
  }, [player]);

  const phaseSummary = useMemo(() => {
    const acc = { before: [], during: [], after: [] };
    chartData.forEach((d) => acc[d.phase]?.push(d));
    return Object.entries(acc).map(([phase, rows]) => {
      const mins = rows.reduce((t, r) => t + r.minutes, 0);
      const goals = rows.reduce((t, r) => t + r.goals, 0);
      const xg = rows.reduce((t, r) => t + r.xgoals, 0);
      return {
        phase,
        seasons: rows.length,
        goals: +goals.toFixed(1),
        xgoals: +xg.toFixed(2),
        minutes: mins,
        per96: mins ? +((goals / mins) * 96).toFixed(2) : 0,
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
                      {s.xgoals} xG · {s.seasons} seasons · {s.per96}/96′
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
