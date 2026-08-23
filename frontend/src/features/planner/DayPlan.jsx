import { useCallback, useEffect, useRef, useState } from "react";
import { plannerApi } from "./plannerApi.js";

const DAYS = [
  { key: "Mon", label: "Monday" },
  { key: "Tue", label: "Tuesday" },
  { key: "Wed", label: "Wednesday" },
  { key: "Thu", label: "Thursday" },
  { key: "Fri", label: "Friday" },
  { key: "Sat", label: "Saturday" },
  { key: "Sun", label: "Sunday" },
];

// JS getDay(): 0=Sun,1=Mon,...6=Sat -> map to our keys
const JSDAY_TO_KEY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const CATEGORIES = {
  morning: { label: "Morning routine", tag: "MORNING", color: "#fabd2f" },
  training: { label: "Training", tag: "TRAINING", color: "#b8bb26" },
  school: { label: "School", tag: "SCHOOL", color: "#83a598" },
  infosec: { label: "Computer science / security", tag: "INFOSEC", color: "#fe8019" },
  freelance: { label: "Freelance", tag: "FREELANCE", color: "#d3869b" },
  other: { label: "Free time / other", tag: "FREE", color: "#8ec07c" },
};
const CAT_KEYS = Object.keys(CATEGORIES);

function timeToMinutes(t) {
  if (!t) return 0;
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

// "2026-08-17" -> "17.08." for the status bar. Parsed by hand rather than via
// new Date(), which would read the string as UTC and can shift the day.
function shortDate(iso) {
  if (!iso) return "";
  const [, month, day] = iso.split("-");
  return `${day}.${month}.`;
}

export default function DayPlan({ onSessionLost }) {
  const [data, setData] = useState(null);
  const [selectedDay, setSelectedDay] = useState(JSDAY_TO_KEY[new Date().getDay()]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showBlockForm, setShowBlockForm] = useState(false);
  const [showTodoForm, setShowTodoForm] = useState(false);
  const [newBlock, setNewBlock] = useState({ time: "12:00", title: "", cat: "other" });
  const [newTodo, setNewTodo] = useState({ title: "", cat: "other" });
  const [now, setNow] = useState(new Date());

  // One timer per field: typing in the title must not fire a PATCH per
  // keystroke. Ticking off and the category go out immediately.
  const patchTimer = useRef({});

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    const timer = patchTimer.current;
    return () => Object.values(timer).forEach(clearTimeout);
  }, []);

  // Handle errors in one place: an expired session goes back to the login,
  // everything else shows up in the status bar.
  const report = useCallback(
    (error) => {
      if (onSessionLost(error)) return;
      setError("Server unreachable — change may not have been saved.");
    },
    [onSessionLost]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Creates the default plan on the very first sign-in and returns the
        // week either way. Idempotent server side, so React StrictMode firing
        // the effect twice in dev does no harm.
        const week = await plannerApi.loadOrSeedWeek();
        if (!cancelled) setData(week);
      } catch (err) {
        if (!cancelled) report(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [report]);

  if (loading) {
    return (
      <div className="dp-loading">
        <div className="dp-loading-text">loading schedule …</div>
        <style>{GLOBAL_CSS}</style>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="dp-loading">
        <div className="dp-loading-text" style={{ color: "#fb4934" }}>
          Could not load the plan. Is the backend running?
        </div>
        <style>{GLOBAL_CSS}</style>
      </div>
    );
  }

  const todayKey = JSDAY_TO_KEY[now.getDay()];
  const day = data[selectedDay];
  // The date this weekday maps to in the loaded week. It comes from the
  // server, so both sides agree on which day a tick belongs to.
  const dayDate = day.date;
  const sortedBlocks = [...day.blocks].sort(
    (a, b) => timeToMinutes(a.time) - timeToMinutes(b.time)
  );
  const doneBlocks = day.blocks.filter((b) => b.done).length;
  const doneTodos = day.todos.filter((t) => t.done).length;

  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const nextBlock =
    selectedDay === todayKey
      ? sortedBlocks.find((b) => timeToMinutes(b.time) > nowMinutes)
      : null;
  const currentBlock =
    selectedDay === todayKey
      ? [...sortedBlocks].reverse().find((b) => timeToMinutes(b.time) <= nowMinutes)
      : null;

  function updateDay(dayKey, mutator) {
    setData((prev) => ({ ...prev, [dayKey]: mutator(prev[dayKey]) }));
  }

  // Writes to local state right away (typing must not stutter) and sends the
  // PATCH afterwards, delayed.
  function later(key, action, delay) {
    clearTimeout(patchTimer.current[key]);
    patchTimer.current[key] = setTimeout(() => {
      action().catch(report);
    }, delay);
  }

  const TYPING_DELAY = 600;

  function editBlock(id, patch) {
    updateDay(selectedDay, (d) => ({
      ...d,
      blocks: d.blocks.map((b) => (b.id === id ? { ...b, ...patch } : b)),
    }));
    later(`b${id}`, () => plannerApi.updateBlock(id, patch, dayDate), TYPING_DELAY);
  }

  // Ticking off is bound to the date, not to the weekday template — that is
  // the whole point: next Monday starts unticked again.
  function toggleBlock(id, done) {
    updateDay(selectedDay, (d) => ({
      ...d,
      blocks: d.blocks.map((b) => (b.id === id ? { ...b, done } : b)),
    }));
    plannerApi.setBlockDone(id, dayDate, done).catch(report);
  }

  function deleteBlock(id) {
    clearTimeout(patchTimer.current[`b${id}`]);
    const before = data;
    updateDay(selectedDay, (d) => ({ ...d, blocks: d.blocks.filter((b) => b.id !== id) }));
    plannerApi.deleteBlock(id).catch((err) => {
      setData(before); // roll back, otherwise the row is gone but the block is not
      report(err);
    });
  }

  async function addBlock() {
    const title = newBlock.title.trim();
    if (!title) return;
    const draft = { ...newBlock, title };
    setNewBlock({ time: "12:00", title: "", cat: "other" });
    setShowBlockForm(false);
    try {
      const created = await plannerApi.createBlock(selectedDay, draft);
      updateDay(selectedDay, (d) => ({ ...d, blocks: [...d.blocks, created] }));
    } catch (err) {
      report(err);
    }
  }

  function editTodo(id, patch) {
    updateDay(selectedDay, (d) => ({
      ...d,
      todos: d.todos.map((t) => (t.id === id ? { ...t, ...patch } : t)),
    }));
    later(`t${id}`, () => plannerApi.updateTodo(id, patch, dayDate), TYPING_DELAY);
  }

  function toggleTodo(id, done) {
    updateDay(selectedDay, (d) => ({
      ...d,
      todos: d.todos.map((t) => (t.id === id ? { ...t, done } : t)),
    }));
    plannerApi.setTodoDone(id, dayDate, done).catch(report);
  }

  function deleteTodo(id) {
    clearTimeout(patchTimer.current[`t${id}`]);
    const before = data;
    updateDay(selectedDay, (d) => ({ ...d, todos: d.todos.filter((t) => t.id !== id) }));
    plannerApi.deleteTodo(id).catch((err) => {
      setData(before);
      report(err);
    });
  }

  async function addTodo() {
    const title = newTodo.title.trim();
    if (!title) return;
    const draft = { ...newTodo, title };
    setNewTodo({ title: "", cat: "other" });
    setShowTodoForm(false);
    try {
      const created = await plannerApi.createTodo(selectedDay, draft);
      updateDay(selectedDay, (d) => ({ ...d, todos: [...d.todos, created] }));
    } catch (err) {
      report(err);
    }
  }

  const dayLabel = DAYS.find((d) => d.key === selectedDay).label;

  return (
    <div className="dp-app">
      <style>{GLOBAL_CSS}</style>

      <nav className="dp-tabs">
        {DAYS.map((d) => {
          const active = d.key === selectedDay;
          const isToday = d.key === todayKey;
          return (
            <button
              key={d.key}
              onClick={() => setSelectedDay(d.key)}
              className={active ? "dp-tab dp-tab-active" : "dp-tab"}
            >
              {isToday && <span className="dp-today-dot" />}
              {d.key}
            </button>
          );
        })}
      </nav>

      <main className="dp-main">
        <section className="dp-col">
          <div className="dp-col-head">
            <span className="dp-col-title">[ schedule — {dayLabel} ]</span>
            <span className="dp-col-count">
              {doneBlocks}/{day.blocks.length}
            </span>
          </div>

          <div className="dp-list">
            {sortedBlocks.length === 0 && (
              <div className="dp-empty">no blocks — add one below.</div>
            )}
            {sortedBlocks.map((b) => (
              <div key={b.id} className="dp-row" style={{ opacity: b.done ? 0.5 : 1 }}>
                <input
                  type="checkbox"
                  checked={b.done}
                  onChange={(e) => toggleBlock(b.id, e.target.checked)}
                  className="dp-check"
                  aria-label="done"
                />
                <input
                  type="time"
                  value={b.time}
                  onChange={(e) => editBlock(b.id, { time: e.target.value })}
                  className="dp-time"
                />
                <input
                  type="text"
                  value={b.title}
                  onChange={(e) => editBlock(b.id, { title: e.target.value })}
                  className="dp-title"
                  style={{ textDecoration: b.done ? "line-through" : "none" }}
                />
                <select
                  value={b.cat}
                  onChange={(e) => editBlock(b.id, { cat: e.target.value })}
                  className="dp-cat"
                  style={{
                    color: CATEGORIES[b.cat].color,
                    borderColor: CATEGORIES[b.cat].color,
                  }}
                >
                  {CAT_KEYS.map((c) => (
                    <option key={c} value={c} className="dp-cat-option">
                      {CATEGORIES[c].tag}
                    </option>
                  ))}
                </select>
                <button onClick={() => deleteBlock(b.id)} className="dp-del" aria-label="delete">
                  ×
                </button>
              </div>
            ))}
          </div>

          {showBlockForm ? (
            <div className="dp-form">
              <input
                type="time"
                value={newBlock.time}
                onChange={(e) => setNewBlock({ ...newBlock, time: e.target.value })}
                className="dp-time"
              />
              <input
                type="text"
                placeholder="Title …"
                value={newBlock.title}
                onChange={(e) => setNewBlock({ ...newBlock, title: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && addBlock()}
                className="dp-title"
                autoFocus
              />
              <select
                value={newBlock.cat}
                onChange={(e) => setNewBlock({ ...newBlock, cat: e.target.value })}
                className="dp-cat"
                style={{
                  color: CATEGORIES[newBlock.cat].color,
                  borderColor: CATEGORIES[newBlock.cat].color,
                }}
              >
                {CAT_KEYS.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORIES[c].tag}
                  </option>
                ))}
              </select>
              <button onClick={addBlock} className="dp-ok">✓</button>
              <button onClick={() => setShowBlockForm(false)} className="dp-del">×</button>
            </div>
          ) : (
            <button onClick={() => setShowBlockForm(true)} className="dp-add">
              + new block
            </button>
          )}
        </section>

        <section className="dp-col">
          <div className="dp-col-head">
            <span className="dp-col-title">[ tasks — {dayLabel} ]</span>
            <span className="dp-col-count">
              {doneTodos}/{day.todos.length}
            </span>
          </div>

          <div className="dp-list">
            {day.todos.length === 0 && (
              <div className="dp-empty">no tasks — add one below.</div>
            )}
            {day.todos.map((t) => (
              <div key={t.id} className="dp-row" style={{ opacity: t.done ? 0.5 : 1 }}>
                <input
                  type="checkbox"
                  checked={t.done}
                  onChange={(e) => toggleTodo(t.id, e.target.checked)}
                  className="dp-check"
                  aria-label="done"
                />
                <input
                  type="text"
                  value={t.title}
                  onChange={(e) => editTodo(t.id, { title: e.target.value })}
                  className="dp-title"
                  style={{ textDecoration: t.done ? "line-through" : "none" }}
                />
                <select
                  value={t.cat}
                  onChange={(e) => editTodo(t.id, { cat: e.target.value })}
                  className="dp-cat"
                  style={{
                    color: CATEGORIES[t.cat].color,
                    borderColor: CATEGORIES[t.cat].color,
                  }}
                >
                  {CAT_KEYS.map((c) => (
                    <option key={c} value={c}>
                      {CATEGORIES[c].tag}
                    </option>
                  ))}
                </select>
                <button onClick={() => deleteTodo(t.id)} className="dp-del" aria-label="delete">
                  ×
                </button>
              </div>
            ))}
          </div>

          {showTodoForm ? (
            <div className="dp-form">
              <input
                type="text"
                placeholder="Task …"
                value={newTodo.title}
                onChange={(e) => setNewTodo({ ...newTodo, title: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && addTodo()}
                className="dp-title"
                autoFocus
              />
              <select
                value={newTodo.cat}
                onChange={(e) => setNewTodo({ ...newTodo, cat: e.target.value })}
                className="dp-cat"
                style={{
                  color: CATEGORIES[newTodo.cat].color,
                  borderColor: CATEGORIES[newTodo.cat].color,
                }}
              >
                {CAT_KEYS.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORIES[c].tag}
                  </option>
                ))}
              </select>
              <button onClick={addTodo} className="dp-ok">✓</button>
              <button onClick={() => setShowTodoForm(false)} className="dp-del">×</button>
            </div>
          ) : (
            <button onClick={() => setShowTodoForm(true)} className="dp-add">
              + new task
            </button>
          )}

          <div className="dp-legend">
            {CAT_KEYS.map((c) => (
              <span key={c} className="dp-legend-item">
                <span
                  className="dp-legend-dot"
                  style={{ background: CATEGORIES[c].color }}
                />
                {CATEGORIES[c].label}
              </span>
            ))}
          </div>
        </section>
      </main>

      <footer className="dp-status">
        <span className="dp-status-item">
          {selectedDay === todayKey ? "● today" : "○ " + dayLabel.toLowerCase()}
        </span>
        <span className="dp-sep">|</span>
        {/* The date makes visible what "3/8" actually refers to. */}
        <span className="dp-status-item">{shortDate(dayDate)}</span>
        <span className="dp-sep">|</span>
        <span className="dp-status-item">
          blocks {doneBlocks}/{day.blocks.length}
        </span>
        <span className="dp-sep">|</span>
        <span className="dp-status-item">
          tasks {doneTodos}/{day.todos.length}
        </span>
        {selectedDay === todayKey && currentBlock && (
          <>
            <span className="dp-sep">|</span>
            <span
              className="dp-status-item"
              style={{ color: CATEGORIES[currentBlock.cat].color }}
            >
              now: {currentBlock.title}
            </span>
          </>
        )}
        {selectedDay === todayKey && nextBlock && (
          <>
            <span className="dp-sep">|</span>
            <span className="dp-status-item">
              next {nextBlock.time} {nextBlock.title}
            </span>
          </>
        )}
        {error && (
          <>
            <span className="dp-sep">|</span>
            <span className="dp-status-item" style={{ color: "#fb4934" }}>
              {error}
            </span>
          </>
        )}
      </footer>
    </div>
  );
}

const MONO =
  "'JetBrains Mono', 'Fira Code', ui-monospace, 'SF Mono', Menlo, Consolas, monospace";

// Layout as real CSS instead of inline styles: media queries do not work
// inline, and those are exactly what is needed — at 375px the two columns
// must not sit side by side.
const GLOBAL_CSS = `
  .dp-app {
    font-family: ${MONO};
    background: #1d2021;
    color: #ebdbb2;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }
  .dp-app *, .dp-app *::before, .dp-app *::after { box-sizing: border-box; }

  .dp-loading {
    font-family: ${MONO};
    background: #1d2021;
    color: #a89984;
    padding: 40px 20px;
    text-align: center;
    border-radius: 8px;
  }
  .dp-loading-text { font-size: 13px; }

  /* ---------- weekday tabs ---------- */
  .dp-tabs {
    display: flex;
    background: #242322;
    border-bottom: 1px solid #3c3836;
    padding: 0 6px;
  }
  .dp-tab {
    font-family: inherit;
    flex: 0 0 auto;
    min-width: 64px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #a89984;
    font-size: 12px;
    min-height: 48px;
    padding: 0 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
  }
  .dp-tab-active { color: #ebdbb2; border-bottom-color: #fe8019; }
  .dp-today-dot {
    width: 5px; height: 5px; border-radius: 50%;
    background: #b8bb26; flex-shrink: 0;
  }

  /* ---------- columns ---------- */
  .dp-main { display: flex; gap: 1px; background: #3c3836; flex: 1; }
  .dp-col {
    flex: 1 1 0;
    min-width: 0;
    background: #1d2021;
    padding: 12px;
    display: flex;
    flex-direction: column;
  }
  .dp-col-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
    color: #83a598;
    margin-bottom: 10px;
  }
  .dp-col-title { min-width: 0; overflow-wrap: anywhere; }
  .dp-col-count { color: #a89984; flex-shrink: 0; }
  .dp-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
  .dp-empty { color: #665c54; font-size: 12px; padding: 8px 0; }

  /* ---------- row ---------- */
  .dp-row, .dp-form {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 6px;
    border-radius: 4px;
    background: #242322;
    min-height: 48px;
  }
  .dp-form { background: #282828; border: 1px dashed #504945; }

  /* Visually 20px, 48x48 hit area via ::after — WCAG 2.5.8 without the
     clunky look. appearance:none is required so the box is styleable at all
     and ::after gets rendered. */
  .dp-check {
    appearance: none;
    -webkit-appearance: none;
    position: relative;
    width: 20px;
    height: 20px;
    margin: 0;
    flex-shrink: 0;
    border: 1px solid #665c54;
    border-radius: 3px;
    background: #1d2021;
    cursor: pointer;
  }
  .dp-check:checked {
    background-color: #b8bb26;
    border-color: #b8bb26;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path d='M3 8.5l3.5 3.5L13 5' fill='none' stroke='%231d2021' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/></svg>");
    background-repeat: no-repeat;
    background-position: center;
    background-size: 14px 14px;
  }
  .dp-check::after {
    content: " ";
    position: absolute;
    left: 50%;
    top: 50%;
    width: 48px;
    height: 48px;
    transform: translate(-50%, -50%);
  }

  .dp-time {
    font-family: inherit;
    background: transparent;
    border: none;
    color: #ebdbb2;
    font-size: 12px;
    min-height: 48px;
    width: 76px;
    flex: 0 0 auto;
    padding: 0;
  }
  .dp-title {
    font-family: inherit;
    background: transparent;
    border: none;
    color: #ebdbb2;
    font-size: 13px;
    min-height: 48px;
    flex: 1 1 auto;
    min-width: 0;
    padding: 0 2px;
    text-overflow: ellipsis;
  }
  /* 48px tall hit area, but visually just coloured text: a 48px box with a
     coloured border would otherwise dominate the whole row. The colour comes
     from the data via inline style. */
  .dp-cat {
    font-family: inherit;
    background: rgba(235, 219, 178, 0.04);
    border: none;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
    min-height: 48px;
    padding: 0 8px;
    flex: 0 0 auto;
    cursor: pointer;
    appearance: none;
    text-align: center;
  }
  .dp-cat:hover { background: rgba(235, 219, 178, 0.09); }
  .dp-cat-option { background: #1d2021; color: #ebdbb2; }
  .dp-del, .dp-ok {
    font-family: inherit;
    background: transparent;
    border: none;
    font-size: 16px;
    min-width: 48px;
    min-height: 48px;
    padding: 0;
    cursor: pointer;
    flex: 0 0 auto;
  }
  .dp-del { color: #665c54; }
  .dp-ok { color: #b8bb26; }
  .dp-add {
    font-family: inherit;
    background: transparent;
    border: 1px dashed #504945;
    border-radius: 4px;
    color: #a89984;
    font-size: 12px;
    min-height: 48px;
    padding: 0 14px;
    cursor: pointer;
    align-self: flex-start;
  }

  /* ---------- legend + status bar ---------- */
  .dp-legend {
    margin-top: auto;
    padding-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    border-top: 1px solid #3c3836;
  }
  .dp-legend-item {
    font-size: 10px;
    color: #a89984;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .dp-legend-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dp-status {
    background: #282828;
    border-top: 1px solid #3c3836;
    margin-top: auto;
    padding: 8px 14px;
    font-size: 11px;
    color: #a89984;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
  }
  .dp-status-item { overflow-wrap: anywhere; }
  .dp-sep { color: #504945; }

  /* ---------- phone ---------- */
  @media (max-width: 720px) {
    /* Edge to edge: on a phone the card-in-a-box only wastes width */
    /* On a phone spread the full width evenly across the 7 days */
    .dp-tab { flex: 1 1 0; min-width: 0; }

    /* Two columns side by side leave zero room for the title at 375px */
    .dp-main { flex-direction: column; }
    .dp-col { flex: 0 0 auto; }
    .dp-legend { margin-top: 16px; }

    /* The row wraps: the title gets the full width on line 2 */
    .dp-row, .dp-form {
      flex-wrap: wrap;
      align-items: center;
      padding: 0 6px;
      row-gap: 0;
    }
    .dp-check { order: 1; }
    .dp-time  { order: 2; }
    .dp-cat   { order: 3; margin-left: auto; }
    .dp-del, .dp-ok { order: 4; }
    .dp-title { order: 5; flex: 1 1 100%; padding: 0; }
    /* This makes the row ~100px tall on a phone. That is intended: two
       comfortably tappable lines beat one where nothing fits. */
  }

  /* ---------- shared ---------- */
  .dp-app input[type="time"]::-webkit-calendar-picker-indicator {
    filter: invert(0.6);
    cursor: pointer;
  }
  .dp-app input:focus-visible,
  .dp-app select:focus-visible,
  .dp-app button:focus-visible {
    outline: 2px solid #fe8019;
    outline-offset: 1px;
  }
  .dp-app button:hover { color: #ebdbb2; }
`;
