// Translates between the backend shape (weekday keys, per-day dates) and the
// shape DayPlan.jsx expects. The translation belongs exactly here — not in the
// component and not in the backend.

import { api } from "../../lib/api.js";

function blockIn(b) {
  return { id: b.id, time: b.time, title: b.title, cat: b.category, done: b.done };
}

function todoIn(t) {
  return { id: t.id, title: t.title, cat: t.category, done: t.done };
}

// Component field names -> backend field names
const FIELDS = { time: "time", title: "title", cat: "category" };

function patchOut(patch) {
  const out = {};
  for (const [k, v] of Object.entries(patch)) {
    if (k in FIELDS) out[FIELDS[k]] = v;
  }
  return out;
}

function weekIn(week) {
  const data = {};
  for (const [day, content] of Object.entries(week)) {
    data[day] = {
      date: content.date, // the server owns the week arithmetic
      blocks: content.blocks.map(blockIn),
      todos: content.todos.map(todoIn),
    };
  }
  return data;
}

// `date` may be any day of the wanted week; the server normalises to Monday.
const forWeek = (date) => (date ? `?date=${date}` : "");

export const plannerApi = {
  loadWeek: (date) => api.get(`/planner/week${forWeek(date)}`).then(weekIn),

  // First sign-in: creates the default plan, otherwise just returns the
  // existing week. Safe to call more than once.
  loadOrSeedWeek: (date) =>
    api.post(`/planner/default-plan${forWeek(date)}`, {}).then(weekIn),

  async createBlock(weekday, { time, title, cat }) {
    return blockIn(
      await api.post("/planner/blocks", { weekday, time, title, category: cat })
    );
  },
  updateBlock: (id, patch, date) =>
    api.patch(`/planner/blocks/${id}${forWeek(date)}`, patchOut(patch)).then(blockIn),
  deleteBlock: (id) => api.delete(`/planner/blocks/${id}`),

  async createTodo(weekday, { title, cat }) {
    return todoIn(
      await api.post("/planner/todos", { weekday, title, category: cat })
    );
  },
  updateTodo: (id, patch, date) =>
    api.patch(`/planner/todos/${id}${forWeek(date)}`, patchOut(patch)).then(todoIn),
  deleteTodo: (id) => api.delete(`/planner/todos/${id}`),

  // Ticking off is bound to a concrete day, not to the weekday template.
  setBlockDone: (id, date, done) =>
    api.put(`/planner/blocks/${id}/completion`, { date, done }),
  setTodoDone: (id, date, done) =>
    api.put(`/planner/todos/${id}/completion`, { date, done }),
};
