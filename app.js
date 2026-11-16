"use strict";

const SOURCE_LABELS = {
  get_on_board: "Get on Board",
  chiletrabajos: "Chiletrabajos",
  computrabajo_chile: "Computrabajo",
  laborum: "Laborum",
  trabajando_cl: "Trabajando",
};

const CHILE_TIME_ZONE = "America/Santiago";
const DAY_IN_MS = 24 * 60 * 60 * 1000;
const state = {
  jobs: [],
};

const elements = {};

function cacheElements() {
  const ids = [
    "active-chips",
    "clear-filters",
    "company-filter",
    "dataset-status",
    "empty-message",
    "empty-state",
    "error-message",
    "error-state",
    "filters-form",
    "filters-summary",
    "hero-sources",
    "hero-total",
    "hero-visible",
    "jobs-list",
    "last-update",
    "location-filter",
    "modality-filter",
    "period-filter",
    "reset-empty",
    "result-count",
    "result-noun",
    "retry-load",
    "search",
    "sort-order",
    "source-filter",
    "status-light",
    "tag-filter",
  ];

  for (const id of ids) {
    elements[toCamelCase(id)] = document.getElementById(id);
  }
}

function toCamelCase(value) {
  return value.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function makeElement(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function sourceLabel(source) {
  if (!source) return "Fuente no informada";
  return SOURCE_LABELS[source] || source.replaceAll("_", " ");
}

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es")
    .trim();
}

function uniqueSorted(values) {
  const unique = [...new Set(values.filter((value) => typeof value === "string" && value.trim()))];
  return unique.sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
}

function populateSelect(select, values, { unknownValue, unknownLabel } = {}) {
  const sorted = uniqueSorted(values);
  if (unknownValue !== undefined) sorted.push(unknownValue);

  const fragment = document.createDocumentFragment();
  for (const value of sorted) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value === unknownValue ? unknownLabel : value;
    fragment.append(option);
  }
  select.append(fragment);
}

function populateFilters() {
  const sources = state.jobs.map((job) => job.source);
  const modalities = state.jobs.map((job) => job.modality);
  const locations = state.jobs.map((job) => job.location);
  const companies = state.jobs.map((job) => job.company);
  const tags = state.jobs.flatMap((job) => (Array.isArray(job.tags) ? job.tags : []));

  populateSelect(elements.sourceFilter, sources.map(sourceLabel));
  populateSelect(elements.modalityFilter, modalities);
  populateSelect(elements.locationFilter, locations, {
    unknownValue: "__none__",
    unknownLabel: "Ubicación no informada",
  });
  populateSelect(elements.companyFilter, companies, {
    unknownValue: "__none__",
    unknownLabel: "Empresa no informada",
  });
  populateSelect(elements.tagFilter, tags);

  // El filtro compara la etiqueta visible, no el identificador interno de la fuente.
}

function readFilters() {
  return {
    query: elements.search.value.trim(),
    source: elements.sourceFilter.value,
    modality: elements.modalityFilter.value,
    location: elements.locationFilter.value,
    company: elements.companyFilter.value,
    tag: elements.tagFilter.value,
    period: elements.periodFilter.value,
  };
}

function matchesExact(value, filterValue) {
  return filterValue === "all" || (value ?? "__none__") === filterValue;
}

function matchesPeriod(job, period) {
  if (period === "all") return true;
  const publishedAt = Date.parse(job.published_at);
  if (!Number.isFinite(publishedAt)) return false;
  return publishedAt >= Date.now() - Number(period) * DAY_IN_MS && publishedAt <= Date.now();
}

function matchesSearch(job, query) {
  if (!query) return true;
  const terms = normalizeText(query).split(/\s+/).filter(Boolean);
  const haystack = normalizeText([
    job.title,
    job.company,
    job.location,
    job.modality,
    job.salary,
    sourceLabel(job.source),
    job.description,
    ...(Array.isArray(job.tags) ? job.tags : []),
  ].filter(Boolean).join(" "));

  return terms.every((term) => haystack.includes(term));
}

function filterJobs() {
  const filters = readFilters();
  return state.jobs.filter((job) => (
    matchesSearch(job, filters.query)
    && (filters.source === "all" || sourceLabel(job.source) === filters.source)
    && matchesExact(job.modality, filters.modality)
    && matchesExact(job.location, filters.location)
    && matchesExact(job.company, filters.company)
    && (filters.tag === "all" || (Array.isArray(job.tags) && job.tags.includes(filters.tag)))
    && matchesPeriod(job, filters.period)
  ));
}

function sortJobs(jobs) {
  const order = elements.sortOrder.value;
  const sorted = [...jobs];

  sorted.sort((a, b) => {
    if (order === "title-asc") {
      return (a.title ?? "").localeCompare(b.title ?? "", "es", { sensitivity: "base" });
    }
    if (order === "company-asc") {
      return (a.company ?? "").localeCompare(b.company ?? "", "es", { sensitivity: "base" });
    }

    const timeA = Date.parse(a.published_at);
    const timeB = Date.parse(b.published_at);
    const hasDateA = Number.isFinite(timeA);
    const hasDateB = Number.isFinite(timeB);
    if (hasDateA !== hasDateB) return hasDateA ? -1 : 1;
    if (!hasDateA) return 0;
    return order === "date-asc" ? timeA - timeB : timeB - timeA;
  });

  return sorted;
}

function formatDate(value, includeTime = false) {
  const timestamp = typeof value === "number" ? value : Date.parse(value);
  if (!Number.isFinite(timestamp)) return "FECHA NO INFORMADA";

  const options = includeTime
    ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: CHILE_TIME_ZONE }
    : { day: "2-digit", month: "short", year: "numeric", timeZone: CHILE_TIME_ZONE };

  return new Intl.DateTimeFormat("es-CL", options)
    .format(new Date(timestamp))
    .replaceAll(".", "")
    .toLocaleUpperCase("es");
}

function appendMetadata(list, value, className = "") {
  if (!value) return;
  const item = makeElement("li", className, value);
  list.append(item);
}

function createJobCard(job, index) {
  const card = makeElement("article", "job-card");
  card.dataset.jobId = job.job_id ?? "";

  const main = makeElement("div", "job-main");
  const topline = makeElement("div", "job-topline");
  topline.append(
    makeElement("span", "job-number", String(index + 1).padStart(2, "0")),
    makeElement("span", "job-source", sourceLabel(job.source)),
  );

  const title = makeElement("h3", "job-title");
  if (job.url) {
    const titleLink = makeElement("a", "", job.title ?? "Cargo no informado");
    titleLink.href = job.url;
    titleLink.target = "_blank";
    titleLink.rel = "noopener noreferrer";
    title.append(titleLink);
  } else {
    title.textContent = job.title ?? "Cargo no informado";
  }

  const company = makeElement("p", "job-company");
  company.append("EN ", makeElement("strong", "", job.company ?? "Empresa no informada"));

  const metadata = makeElement("ul", "job-meta");
  appendMetadata(metadata, job.location ?? "Ubicación no informada");
  appendMetadata(metadata, job.modality ?? "Modalidad no informada");
  appendMetadata(metadata, job.salary, "salary");

  const tags = makeElement("ul", "job-tags");
  const jobTags = Array.isArray(job.tags) ? job.tags.filter(Boolean) : [];
  for (const tag of jobTags.slice(0, 6)) {
    tags.append(makeElement("li", "", tag));
  }
  if (jobTags.length > 6) {
    const remaining = makeElement("li", "more-tags", `+${jobTags.length - 6} skills`);
    remaining.title = jobTags.slice(6).join(", ");
    tags.append(remaining);
  }

  main.append(topline, title, company, metadata);
  if (jobTags.length) main.append(tags);

  if (job.description) {
    const details = makeElement("details", "job-description");
    const summary = makeElement("summary");
    summary.append(
      makeElement("span", "description-symbol", "+"),
      document.createTextNode("VER DESCRIPCIÓN"),
    );
    details.append(summary, makeElement("div", "description-content", job.description));
    main.append(details);
  }

  const side = makeElement("div", "job-side");
  const published = makeElement("time", "job-date", formatDate(job.published_at));
  if (job.published_at) {
    published.dateTime = job.published_at;
    published.title = formatDate(job.published_at, true);
  }

  if (job.url) {
    const link = makeElement("a", "job-link");
    link.href = job.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `Abrir oferta: ${job.title ?? "cargo no informado"}`);
    link.append(document.createTextNode("ABRIR OFERTA"), makeElement("span", "", "↗"));
    side.append(published, link);
  } else {
    side.append(published, makeElement("span", "job-link is-unavailable", "URL NO DISPONIBLE"));
  }

  card.append(main, side);
  return card;
}

function countActiveFilters(filters) {
  return Object.values(filters).filter((value) => value !== "all" && value !== "").length;
}

function renderActiveChips(filters) {
  const labels = {
    query: "BUSQUEDA",
    source: "PORTAL",
    modality: "MODALIDAD",
    location: "UBICACIÓN",
    company: "EMPRESA",
    tag: "TECNOLOGÍA",
    period: "PUBLICACIÓN",
  };
  const periodLabels = {
    "1": "Últimas 24 horas",
    "7": "Últimos 7 días",
    "14": "Últimos 14 días",
    "30": "Últimos 30 días",
  };
  const noneLabels = {
    "__none__": "No informada",
  };

  elements.activeChips.replaceChildren();
  for (const [key, value] of Object.entries(filters)) {
    if (value === "all" || value === "") continue;
    const button = makeElement("button", "filter-chip");
    button.type = "button";
    button.dataset.filter = key;
    button.setAttribute("aria-label", `Quitar filtro ${labels[key]}: ${value}`);
    const displayValue = key === "period" ? periodLabels[value] : (noneLabels[value] ?? value);
    button.append(
      makeElement("span", "", `${labels[key]}: ${displayValue}`),
      makeElement("span", "", "×"),
    );
    elements.activeChips.append(button);
  }
  elements.activeChips.hidden = countActiveFilters(filters) === 0;
}

function renderResults() {
  const filters = readFilters();
  const visibleJobs = sortJobs(filterJobs());
  const activeCount = countActiveFilters(filters);
  const fragment = document.createDocumentFragment();

  elements.errorState.hidden = true;
  elements.emptyState.hidden = visibleJobs.length > 0;
  elements.jobsList.hidden = visibleJobs.length === 0;
  elements.jobsList.setAttribute("aria-busy", "false");
  elements.jobsList.replaceChildren();

  visibleJobs.forEach((job, index) => fragment.append(createJobCard(job, index)));
  elements.jobsList.append(fragment);
  elements.activeChips.hidden = activeCount === 0;
  renderActiveChips(filters);

  elements.resultCount.textContent = visibleJobs.length;
  elements.resultNoun.textContent = visibleJobs.length === 1 ? "oferta" : "ofertas";
  elements.heroVisible.textContent = String(visibleJobs.length).padStart(2, "0");
  elements.filtersSummary.textContent = activeCount === 0
    ? "SIN FILTROS ACTIVOS"
    : `${activeCount} ${activeCount === 1 ? "FILTRO ACTIVO" : "FILTROS ACTIVOS"}`;
  elements.clearFilters.disabled = activeCount === 0;
  elements.retryLoad.hidden = true;
  elements.emptyMessage.textContent = state.jobs.length === 0
    ? "El archivo jobs.json está vacío. Ejecuta una búsqueda con los conectores para incorporar ofertas."
    : "Prueba con otros filtros o elimina algunos términos de búsqueda.";
  elements.resetEmpty.hidden = activeCount === 0;
}

function updateDatasetMetadata() {
  const sourceCount = new Set(state.jobs.map((job) => job.source).filter(Boolean)).size;
  const scrapeTimes = state.jobs
    .map((job) => Date.parse(job.scraped_at))
    .filter(Number.isFinite);
  const latestScrape = scrapeTimes.length ? Math.max(...scrapeTimes) : null;

  elements.heroTotal.textContent = String(state.jobs.length).padStart(2, "0");
  elements.heroSources.textContent = String(sourceCount).padStart(2, "0");
  elements.datasetStatus.textContent = `${state.jobs.length} OFERTAS CARGADAS`;
  elements.statusLight.className = "status-light is-ready";
  elements.lastUpdate.textContent = latestScrape
    ? `EXTRACCIÓN: ${formatDate(latestScrape, true)}`
    : "FECHA DE EXTRACCIÓN NO INFORMADA";
}

function clearFilters() {
  elements.filtersForm.reset();
  elements.search.value = "";
  renderResults();
}

function clearSingleFilter(filterName) {
  const controls = {
    query: elements.search,
    source: elements.sourceFilter,
    modality: elements.modalityFilter,
    location: elements.locationFilter,
    company: elements.companyFilter,
    tag: elements.tagFilter,
    period: elements.periodFilter,
  };
  const control = controls[filterName];
  if (!control) return;
  control.value = filterName === "query" ? "" : "all";
  renderResults();
}

function showLoadError(error) {
  state.jobs = [];
  elements.jobsList.replaceChildren();
  elements.jobsList.hidden = true;
  elements.jobsList.setAttribute("aria-busy", "false");
  elements.emptyState.hidden = true;
  elements.activeChips.hidden = true;
  elements.errorState.hidden = false;
  elements.retryLoad.hidden = false;
  elements.errorMessage.textContent = error.message;
  elements.datasetStatus.textContent = "ERROR DE CARGA";
  elements.statusLight.className = "status-light is-error";
  elements.heroTotal.textContent = "00";
  elements.heroSources.textContent = "00";
  elements.heroVisible.textContent = "00";
  elements.resultCount.textContent = "0";
  elements.resultNoun.textContent = "ofertas";
  elements.lastUpdate.textContent = "SIN DATOS";
}

async function loadJobs() {
  elements.errorState.hidden = true;
  elements.emptyState.hidden = true;
  elements.jobsList.hidden = false;
  elements.jobsList.setAttribute("aria-busy", "true");
  elements.datasetStatus.textContent = "CARGANDO DATOS";
  elements.statusLight.className = "status-light";

  try {
    const response = await fetch("jobs.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status} al solicitar jobs.json.`);
    const payload = await response.json();
    if (!Array.isArray(payload)) throw new Error("jobs.json debe contener una lista de ofertas.");
    if (payload.some((job) => !job || typeof job !== "object" || Array.isArray(job))) {
      throw new Error("jobs.json contiene elementos que no son ofertas válidas.");
    }

    state.jobs = payload;
    populateFilters();
    updateDatasetMetadata();
    renderResults();
  } catch (error) {
    const message = window.location.protocol === "file:"
      ? "El navegador no permite leer jobs.json desde file://. Sirve el proyecto mediante un servidor HTTP local."
      : error.message;
    showLoadError(new Error(message));
    console.error("No se pudo cargar jobs.json:", error);
  }
}

function bindEvents() {
  elements.filtersForm.addEventListener("submit", (event) => event.preventDefault());
  elements.filtersForm.addEventListener("input", renderResults);
  elements.filtersForm.addEventListener("change", renderResults);
  elements.sortOrder.addEventListener("change", renderResults);
  elements.clearFilters.addEventListener("click", clearFilters);
  elements.resetEmpty.addEventListener("click", clearFilters);
  elements.retryLoad.addEventListener("click", () => window.location.reload());

  elements.activeChips.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (button) clearSingleFilter(button.dataset.filter);
  });

  document.addEventListener("keydown", (event) => {
    const activeElement = document.activeElement;
    const isEditing = activeElement instanceof HTMLInputElement
      || activeElement instanceof HTMLTextAreaElement
      || activeElement instanceof HTMLSelectElement
      || activeElement?.isContentEditable;

    if (event.key === "/" && !isEditing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      elements.search.focus();
    }

    if (event.key === "Escape" && activeElement === elements.search && elements.search.value) {
      elements.search.value = "";
      renderResults();
    }
  });
}

function init() {
  cacheElements();
  bindEvents();
  loadJobs();
}

document.addEventListener("DOMContentLoaded", init);
