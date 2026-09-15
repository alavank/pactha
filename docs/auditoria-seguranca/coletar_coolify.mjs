import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/*
 * Coletor somente-leitura para a auditoria PACTHA.
 *
 * As credenciais são lidas do prompt local e usadas exclusivamente no header
 * Authorization de requisições GET. Respostas brutas nunca são persistidas.
 * Valores de env são reduzidos a metadados, máscara e fingerprint.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const PROMPT = join(HERE, "prompt-auditoria-seguranca-pactha.md");
const OUTPUT = join(HERE, "coolify-auditoria-sanitizada.json");

const prompt = readFileSync(PROMPT, "utf8");
const baseMatch = prompt.match(/COOLIFY_URL\s*=\s*(https?:\/\/[^\s;]+)/);
// O texto corrido do prompt põe pontuação logo depois do token; limite o
// capture ao alfabeto usado pelo token para não incluir o ponto final.
const tokenMatch = prompt.match(/COOLIFY_TOKEN\s*=\s*([A-Za-z0-9|_-]+)/);
if (!baseMatch || !tokenMatch) {
  throw new Error("COOLIFY_URL/COOLIFY_TOKEN não encontrados no prompt local");
}

const API_BASE = `${baseMatch[1].replace(/\/$/, "")}/api/v1`;
const COOLIFY_TOKEN = tokenMatch[1];
const VERSION_ONLY = process.argv.includes("--version-only");

function fp(value) {
  return createHash("sha256").update(String(value)).digest("hex").slice(0, 12);
}

function masked(value) {
  const text = String(value ?? "");
  if (!text) return "<vazio>";
  if (/^(\*+|redacted|null)$/i.test(text)) return `<redigido-pela-api; len=${text.length}>`;
  const edge = Math.min(3, Math.floor(text.length / 3));
  const prefix = edge ? text.slice(0, edge) : "";
  const suffix = edge ? text.slice(-edge) : "";
  return `${prefix}...${suffix} (len=${text.length}; sha256=${fp(text)})`;
}

function redactInline(text) {
  if (text == null) return text;
  let out = String(text);
  out = out.replace(
    /([a-z][a-z0-9+.-]*:\/\/)([^\s/@:]+):([^\s/@]+)@/gi,
    (_m, scheme, user, pass) => `${scheme}${user}:${masked(pass)}@`,
  );
  out = out.replace(
    /\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASS|API_KEY|PRIVATE_KEY|CREDENTIAL|COFRE_KEY|JWT_SECRET)[A-Z0-9_]*)\s*=\s*([^\s]+)/gi,
    (_m, key, value) => `${key}=${masked(value)}`,
  );
  out = out.replace(/(Authorization:\s*Bearer\s+)([^\s]+)/gi, (_m, p, value) => `${p}${masked(value)}`);
  return out;
}

function urlMetadata(value) {
  const entries = String(value ?? "").split(",").map((v) => v.trim()).filter(Boolean);
  return entries.map((entry) => {
    try {
      const u = new URL(entry);
      return {
        scheme: u.protocol.replace(":", ""),
        host: u.hostname,
        port: u.port || null,
        path: u.pathname || "/",
        has_username: Boolean(u.username),
        has_password: Boolean(u.password),
        username: u.username ? masked(decodeURIComponent(u.username)) : null,
        password: u.password ? masked(decodeURIComponent(u.password)) : null,
        has_query: Boolean(u.search),
        fingerprint: fp(entry),
      };
    } catch {
      return { malformed_or_non_url: true, masked: masked(entry), fingerprint: fp(entry) };
    }
  });
}

const URL_KEYS = /(?:^|_)(?:DATABASE_URL|DB_URL|INTERNAL_DB_URL|EXTERNAL_DB_URL|FRONTEND_URL|API_URL|ALLOWED_ORIGINS|CORS_ORIGINS|API_PROXY_TARGET|SMTP_URL)(?:$|_)/i;
const SENSITIVE_KEYS = /(?:SECRET|TOKEN|PASSWORD|PASSWD|PASS$|API_KEY|PRIVATE_KEY|CREDENTIAL|COFRE|DATABASE_URL|DB_URL|AUTH_SECRET|SIGNING|ENCRYPTION|CERTIFICATE|SMTP_PASS|POSTGRES_PASSWORD)/i;
const SAFE_LITERAL_KEYS = /^(?:ENV|NODE_ENV|PORT|HOST|INSTANCE_SLUG|MUNICIPIO_(?:NOME|IBGE|UF)|BI_MODULE|AUTHZ_MODO|TELEGRAM_MODULE|SISMOB_ENABLED|JWT_ALGORITHM|JWT_EXPIRE_MINUTES|POSTGRES_(?:USER|DB)|CORS_ORIGIN_REGEX|CONTROL_PLANE_ALLOWED_IPS|RM_(?:RODAPE|LOGO|EMAIL|CIDADE)|VAPID_SUBJECT)$/i;

function envMetadata(row) {
  const key = String(row?.key ?? row?.name ?? "<sem-chave>");
  const raw = row?.value ?? row?.real_value ?? row?.runtime_value ?? "";
  const text = String(raw ?? "");
  const apiRedacted = /^(\*+|redacted|null)$/i.test(text);
  const base = {
    key,
    is_build_time: Boolean(row?.is_build_time),
    is_preview: Boolean(row?.is_preview),
    is_literal: row?.is_literal ?? null,
    value_present: text.length > 0,
    api_redacted: apiRedacted,
    length: text.length,
    fingerprint: apiRedacted ? null : fp(text),
    masked: masked(text),
  };
  if (URL_KEYS.test(key) || /URL|ORIGIN|DOMAIN/i.test(key)) {
    base.url = urlMetadata(text);
  } else if (SAFE_LITERAL_KEYS.test(key)) {
    base.safe_value = redactInline(text);
  } else if (/^NEXT_PUBLIC_/i.test(key)) {
    base.public_exposure = true;
    if (/URL|ORIGIN|DOMAIN/i.test(key)) base.url = urlMetadata(text);
  } else if (!SENSITIVE_KEYS.test(key) && /^(?:true|false|0|1|[0-9]{1,8})$/i.test(text)) {
    base.safe_value = text;
  }
  return base;
}

function asArray(body) {
  if (Array.isArray(body)) return body;
  for (const key of ["data", "items", "results", "applications", "databases", "services", "servers", "projects"]) {
    if (Array.isArray(body?.[key])) return body[key];
  }
  return [];
}

function identity(item) {
  const env = item?.environment ?? {};
  const project = env?.project ?? item?.project ?? {};
  return {
    uuid: item?.uuid ?? null,
    id: item?.id ?? null,
    name: item?.name ?? null,
    description: item?.description ?? null,
    status: item?.status ?? null,
    environment_uuid: item?.environment_uuid ?? env?.uuid ?? null,
    environment_id: item?.environment_id ?? env?.id ?? null,
    environment_name: item?.environment_name ?? env?.name ?? null,
    project_uuid: item?.project_uuid ?? project?.uuid ?? null,
    project_id: item?.project_id ?? project?.id ?? null,
    project_name: item?.project_name ?? project?.name ?? null,
    server_uuid: item?.server_uuid ?? item?.destination?.server?.uuid ?? null,
  };
}

function appMetadata(item) {
  return {
    ...identity(item),
    fqdn: item?.fqdn ?? item?.domains ?? null,
    git_repository: item?.git_repository ?? null,
    git_branch: item?.git_branch ?? null,
    git_commit_sha: item?.git_commit_sha ?? null,
    build_pack: item?.build_pack ?? null,
    dockerfile_location: item?.dockerfile_location ?? null,
    docker_registry_image_name: item?.docker_registry_image_name ?? null,
    docker_registry_image_tag: item?.docker_registry_image_tag ?? null,
    ports_exposes: item?.ports_exposes ?? null,
    ports_mappings: item?.ports_mappings ?? null,
    is_public: item?.is_public ?? null,
    public_port: item?.public_port ?? null,
    redirect: item?.redirect ?? null,
  };
}

function databaseMetadata(item) {
  const urls = {};
  for (const key of ["internal_db_url", "external_db_url", "database_url"]) {
    if (item?.[key]) urls[key] = urlMetadata(item[key]);
  }
  return {
    ...identity(item),
    image: item?.image ?? item?.docker_image ?? null,
    database_type: item?.database_type ?? item?.type ?? null,
    is_public: item?.is_public ?? null,
    public_port: item?.public_port ?? null,
    ports_exposes: item?.ports_exposes ?? null,
    postgres_user: item?.postgres_user ?? null,
    postgres_db: item?.postgres_db ?? null,
    urls,
    backup_enabled: item?.backup_enabled ?? item?.is_backup_enabled ?? null,
  };
}

function serviceMetadata(item) {
  return {
    ...identity(item),
    fqdn: item?.fqdn ?? item?.domains ?? null,
    docker_compose_location: item?.docker_compose_location ?? null,
    is_container_label_escape_enabled: item?.is_container_label_escape_enabled ?? null,
  };
}

function serverMetadata(item) {
  return {
    uuid: item?.uuid ?? null,
    id: item?.id ?? null,
    name: item?.name ?? null,
    description: item?.description ?? null,
    ip: item?.ip ?? null,
    port: item?.port ?? null,
    user: item?.user ?? null,
    is_reachable: item?.is_reachable ?? null,
    is_usable: item?.is_usable ?? null,
  };
}

function projectMetadata(item) {
  return {
    uuid: item?.uuid ?? null,
    id: item?.id ?? null,
    name: item?.name ?? null,
    description: item?.description ?? null,
  };
}

function projectDetailMetadata(item) {
  const environments = asArray(item?.environments ?? item?.data?.environments ?? []);
  return {
    ...projectMetadata(item),
    environments: environments.map((env) => ({
      uuid: env?.uuid ?? null,
      id: env?.id ?? null,
      name: env?.name ?? null,
      description: env?.description ?? null,
      applications: asArray(env?.applications ?? []).map(appMetadata),
      databases: [
        ...asArray(env?.databases ?? []),
        ...asArray(env?.postgresqls ?? []),
      ].map(databaseMetadata),
      services: asArray(env?.services ?? []).map(serviceMetadata),
    })),
  };
}

async function get(path) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${COOLIFY_TOKEN}`,
      Accept: "application/json",
    },
    redirect: "manual",
  });
  const raw = await response.text();
  let body = raw;
  try { body = raw ? JSON.parse(raw) : null; } catch { /* mantém texto */ }
  if (!response.ok) {
    const error = new Error(`GET ${path} -> HTTP ${response.status}`);
    error.status = response.status;
    error.body = redactInline(typeof body === "string" ? body.slice(0, 500) : JSON.stringify(body).slice(0, 500));
    throw error;
  }
  return body;
}

async function tryGet(path, errors) {
  try {
    return await get(path);
  } catch (error) {
    errors.push({ path, status: error.status ?? null, message: error.message, body: error.body ?? null });
    return null;
  }
}

const version = await get("/version");
if (VERSION_ONLY) {
  process.stdout.write(`${JSON.stringify({ version }, null, 2)}\n`);
  process.exit(0);
}

const errors = [];
const [projectsRaw, appsRaw, dbsRaw, servicesRaw, serversRaw] = await Promise.all([
  tryGet("/projects", errors),
  tryGet("/applications", errors),
  tryGet("/databases", errors),
  tryGet("/services", errors),
  tryGet("/servers", errors),
]);

const projects = asArray(projectsRaw);
const apps = asArray(appsRaw);
const databases = asArray(dbsRaw);
const services = asArray(servicesRaw);
const servers = asArray(serversRaw);

const projectDetails = [];
for (const project of projects) {
  if (!project?.uuid) continue;
  const detail = await tryGet(`/projects/${encodeURIComponent(project.uuid)}`, errors);
  if (detail) projectDetails.push(projectDetailMetadata(detail));
}

const applicationDetails = [];
for (const app of apps) {
  if (!app?.uuid) continue;
  const uuid = encodeURIComponent(app.uuid);
  const detail = await tryGet(`/applications/${uuid}`, errors);
  const envs = await tryGet(`/applications/${uuid}/envs`, errors);
  const tasks = await tryGet(`/applications/${uuid}/scheduled-tasks`, errors);
  applicationDetails.push({
    ...appMetadata(detail ?? app),
    envs: asArray(envs).map(envMetadata),
    scheduled_tasks: asArray(tasks).map((task) => ({
      uuid: task?.uuid ?? null,
      name: task?.name ?? null,
      command: redactInline(task?.command ?? ""),
      command_fingerprint: fp(task?.command ?? ""),
      frequency: task?.frequency ?? null,
      enabled: task?.enabled ?? task?.is_enabled ?? null,
      timeout: task?.timeout ?? null,
    })),
  });
}

const databaseDetails = [];
for (const db of databases) {
  if (!db?.uuid) continue;
  const detail = await tryGet(`/databases/${encodeURIComponent(db.uuid)}`, errors);
  databaseDetails.push(databaseMetadata(detail ?? db));
}

const serviceDetails = [];
for (const service of services) {
  if (!service?.uuid) continue;
  const uuid = encodeURIComponent(service.uuid);
  const detail = await tryGet(`/services/${uuid}`, errors);
  const envs = await tryGet(`/services/${uuid}/envs`, errors);
  serviceDetails.push({
    ...serviceMetadata(detail ?? service),
    envs: asArray(envs).map(envMetadata),
  });
}

const output = {
  schema: "pactha-coolify-audit-sanitized-v1",
  collected_at_utc: new Date().toISOString(),
  methodology: "Somente GET; respostas brutas não persistidas; envs reduzidas a máscara/fingerprint/metadados de URL.",
  version,
  projects: projects.map(projectMetadata),
  project_details: projectDetails,
  applications: applicationDetails,
  databases: databaseDetails,
  services: serviceDetails,
  servers: servers.map(serverMetadata),
  errors,
};

writeFileSync(OUTPUT, `${JSON.stringify(output, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({
  output: OUTPUT,
  projects: output.projects.length,
  applications: output.applications.length,
  databases: output.databases.length,
  services: output.services.length,
  servers: output.servers.length,
  errors: output.errors.length,
}, null, 2)}\n`);
