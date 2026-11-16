const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadApp() {
  const filename = path.resolve(__dirname, "..", "app.js");
  const source = fs.readFileSync(filename, "utf-8");
  const context = vm.createContext({
    console,
    document: { addEventListener() {} },
  });
  const exposed = `\n;globalThis.__webTest = {
    elements,
    state,
    filterJobs,
    formatDate,
    matchesPeriod,
    normalizeText,
    sortJobs,
    sourceLabel,
  };`;
  vm.runInContext(source + exposed, context, { filename });
  return context.__webTest;
}

function installFilters(app) {
  Object.assign(app.elements, {
    search: { value: "" },
    sourceFilter: { value: "all" },
    modalityFilter: { value: "all" },
    locationFilter: { value: "all" },
    companyFilter: { value: "all" },
    tagFilter: { value: "all" },
    periodFilter: { value: "all" },
    sortOrder: { value: "date-desc" },
  });
}

function jobsFixture() {
  const now = Date.now();
  return [
    {
      job_id: "remote-python",
      source: "get_on_board",
      title: "Backend Python",
      company: null,
      location: null,
      modality: "remoto",
      tags: ["Python"],
      published_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    },
    {
      job_id: "hybrid-dotnet",
      source: "chiletrabajos",
      title: "Backend .NET",
      company: "Acme",
      location: "Santiago",
      modality: "híbrido",
      tags: [".NET"],
      published_at: new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString(),
    },
    {
      job_id: "no-date",
      source: "get_on_board",
      title: "Frontend",
      company: "Beta",
      location: "Valparaíso",
      modality: "presencial",
      tags: ["JavaScript"],
      published_at: null,
    },
  ];
}

test("normaliza tildes para comparar términos de búsqueda", () => {
  const app = loadApp();
  assert.equal(app.normalizeText("  HÍBRIDO Ñandú "), "hibrido nandu");
  assert.equal(app.sourceLabel("get_on_board"), "Get on Board");
});

test("filtra por búsqueda multitérmino sin distinguir tildes", () => {
  const app = loadApp();
  installFilters(app);
  app.state.jobs = jobsFixture();
  app.elements.search.value = "hibrido acme";
  assert.deepEqual(Array.from(app.filterJobs(), (job) => job.job_id), ["hybrid-dotnet"]);
});

test("filtra por portal, modalidad y tecnología", () => {
  const app = loadApp();
  installFilters(app);
  app.state.jobs = jobsFixture();

  app.elements.sourceFilter.value = "Get on Board";
  assert.equal(app.filterJobs().length, 2);
  app.elements.sourceFilter.value = "all";
  app.elements.modalityFilter.value = "remoto";
  assert.equal(app.filterJobs().length, 1);
  app.elements.modalityFilter.value = "all";
  app.elements.tagFilter.value = ".NET";
  assert.deepEqual(Array.from(app.filterJobs(), (job) => job.job_id), ["hybrid-dotnet"]);
});

test("permite seleccionar empresa y ubicación no informadas", () => {
  const app = loadApp();
  installFilters(app);
  app.state.jobs = jobsFixture();

  app.elements.companyFilter.value = "__none__";
  assert.deepEqual(Array.from(app.filterJobs(), (job) => job.job_id), ["remote-python"]);
  app.elements.companyFilter.value = "all";
  app.elements.locationFilter.value = "__none__";
  assert.deepEqual(Array.from(app.filterJobs(), (job) => job.job_id), ["remote-python"]);
});

test("descarta fechas ausentes sólo cuando hay filtro de período", () => {
  const app = loadApp();
  installFilters(app);
  app.state.jobs = jobsFixture();
  assert.equal(app.filterJobs().length, 3);

  app.elements.periodFilter.value = "7";
  assert.deepEqual(Array.from(app.filterJobs(), (job) => job.job_id), ["remote-python"]);
  assert.equal(app.matchesPeriod({ published_at: new Date(Date.now() + 60_000).toISOString() }, "7"), false);
});

test("ordena por fecha y deja valores ausentes al final", () => {
  const app = loadApp();
  installFilters(app);
  app.state.jobs = jobsFixture();

  assert.deepEqual(
    Array.from(app.sortJobs(app.state.jobs), (job) => job.job_id),
    ["remote-python", "hybrid-dotnet", "no-date"],
  );
  app.elements.sortOrder.value = "date-asc";
  assert.deepEqual(
    Array.from(app.sortJobs(app.state.jobs), (job) => job.job_id),
    ["hybrid-dotnet", "remote-python", "no-date"],
  );
});

test("acepta timestamp numérico al mostrar la última extracción", () => {
  const app = loadApp();
  assert.match(app.formatDate(Date.UTC(2026, 10, 16, 1, 3, 8), true), /2026/);
  assert.equal(app.formatDate(null), "FECHA NO INFORMADA");
});
