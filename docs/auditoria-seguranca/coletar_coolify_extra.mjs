import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/*
 * Coletor COMPLEMENTAR somente-leitura (auditoria PACTHA, seção 2, passos 4/6/7/8).
 * Cobre o que o coletor principal não guardou: detalhes de cada application do
 * projeto `pactha` (campos de exposição/labels/comandos, allowlist explícita),
 * backups por banco, servidor, team/membros e chaves SSH (só contagem).
 *
 * Credenciais lidas do prompt local; usadas apenas no header Authorization de GETs.
 * Nada bruto é persistido: campos fora da allowlist são descartados e qualquer
 * campo com nome sensível vira máscara + fingerprint.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const prompt = readFileSync(join(HERE, "prompt-auditoria-seguranca-pactha.md"), "utf8");
const baseMatch = prompt.match(/COOLIFY_URL\s*=\s*(https?:\/\/[^\s;]+)/);
const tokenMatch = prompt.match(/COOLIFY_TOKEN\s*=\s*([A-Za-z0-9|_-]+)/);
if (!baseMatch || !tokenMatch) throw new Error("COOLIFY_URL/COOLIFY_TOKEN não encontrados no prompt local");
const API_BASE = `${baseMatch[1].replace(/\/$/, "")}/api/v1`;
const TOKEN = tokenMatch[1];

const fp = (v) => createHash("sha256").update(String(v)).digest("hex").slice(0, 12);
function masked(value) {
  const t = String(value ?? "");
  if (!t) return "<vazio>";
  const edge = Math.min(3, Math.floor(t.length / 3));
  return `${t.slice(0, edge)}...${t.slice(-edge)} (len=${t.length}; sha256=${fp(t)})`;
}
const SENS = /(secret|token|password|passwd|private|credential|key$|_key|webhook)/i;

async function get(path) {
  const r = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${TOKEN}`, Accept: "application/json" }, redirect: "manual" });
  const text = await r.text();
  let body = null; try { body = text ? JSON.parse(text) : null; } catch { body = text.slice(0, 200); }
  return { status: r.status, body };
}

// Campos de application que interessam à auditoria (sem valores de segredo)
const APP_FIELDS = [
  "uuid", "name", "fqdn", "status", "build_pack", "git_repository", "git_branch", "git_commit_sha",
  "docker_registry_image_name", "docker_registry_image_tag", "ports_exposes", "ports_mappings",
  "redirect", "is_static", "static_image", "base_directory", "dockerfile_location", "docker_compose_location",
  "custom_docker_run_options", "post_deployment_command", "post_deployment_command_container",
  "pre_deployment_command", "pre_deployment_command_container", "custom_labels",
  "limits_memory", "limits_cpus", "limits_memory_swap", "limits_cpu_shares",
  "health_check_enabled", "health_check_path", "health_check_port", "health_check_host",
  "is_auto_deploy_enabled", "is_force_https_enabled", "is_gzip_enabled", "is_stripprefix_enabled",
  "is_container_label_escape_enabled", "is_container_label_readonly_enabled", "is_preview_deployments_enabled",
  "is_log_drain_enabled", "connect_to_docker_network", "is_consistent_container_name_enabled",
  "is_raw_compose_deployment_enabled", "is_env_sorting_enabled", "is_build_server_enabled",
  "preview_url_template", "created_at", "updated_at", "last_online_at", "environment_id", "destination_type",
];
function pickApp(a) {
  const out = {};
  for (const k of APP_FIELDS) if (k in (a ?? {})) out[k] = a[k];
  if (typeof out.custom_labels === "string" && out.custom_labels.length) {
    try { out.custom_labels_decoded = Buffer.from(out.custom_labels, "base64").toString("utf8").split("\n").filter(Boolean); } catch {}
    delete out.custom_labels;
  }
  // qualquer campo com nome sensível presente na resposta é registrado só como máscara
  out.campos_sensiveis_presentes = Object.keys(a ?? {}).filter((k) => SENS.test(k) && a[k]).map((k) => `${k}=${masked(a[k])}`);
  out.todos_os_campos = Object.keys(a ?? {}).sort();
  return out;
}

const principal = JSON.parse(readFileSync(join(HERE, "coolify-auditoria-sanitizada.json"), "utf8"));
const apps = principal.applications.filter((a) => a.project_name === "pactha");
const dbs = principal.databases.filter((d) => d.project_name === "pactha");

const out = { schema: "pactha-coolify-audit-extra-v1", version: principal.version, applications: [], databases: [], server: null, team: null, members: null, security_keys_count: null, endpoints: {} };

for (const a of apps) {
  const r = await get(`/applications/${a.uuid}`);
  out.applications.push({ status_http: r.status, ...(r.status === 200 ? pickApp(r.body) : { uuid: a.uuid, name: a.name }) });
}
for (const d of dbs) {
  const det = await get(`/databases/${d.uuid}`);
  const bk = await get(`/databases/${d.uuid}/backups`);
  const b = det.body ?? {};
  out.databases.push({
    uuid: d.uuid, name: d.name, status_http: det.status,
    is_public: b.is_public ?? null, public_port: b.public_port ?? null, ports_mappings: b.ports_mappings ?? null,
    image: b.image ?? null, status: b.status ?? null, limits_memory: b.limits_memory ?? null,
    is_log_drain_enabled: b.is_log_drain_enabled ?? null, created_at: b.created_at ?? null,
    campos: Object.keys(b).sort(),
    campos_sensiveis_presentes: Object.keys(b).filter((k) => SENS.test(k) && b[k]).map((k) => `${k}=${masked(b[k])}`),
    backups_http: bk.status,
    backups: Array.isArray(bk.body) ? bk.body.map((x) => ({ uuid: x.uuid ?? null, enabled: x.enabled ?? null, frequency: x.frequency ?? null, save_s3: x.save_s3 ?? null, number_of_backups_locally: x.number_of_backups_locally ?? null, databases_to_backup: x.databases_to_backup ?? null })) : (typeof bk.body === "string" ? bk.body.slice(0, 120) : bk.body),
  });
}
const srv = await get(`/servers/${principal.servers[0]?.uuid}`);
if (srv.status === 200) {
  const s = srv.body;
  out.server = { uuid: s.uuid, name: s.name, ip: s.ip, port: s.port, user: s.user, proxy_type: s.proxy?.type ?? s.proxy_type ?? null, settings: s.settings ? Object.fromEntries(Object.entries(s.settings).filter(([k]) => !SENS.test(k))) : null, campos: Object.keys(s).sort() };
} else out.server = { status_http: srv.status };
for (const [name, path] of Object.entries({ teams: "/teams", team_current: "/teams/current", members: "/teams/current/members", security_keys: "/security/keys", resources: `/servers/${principal.servers[0]?.uuid}/resources`, domains: `/servers/${principal.servers[0]?.uuid}/domains` })) {
  const r = await get(path);
  out.endpoints[name] = { status_http: r.status };
  if (r.status !== 200) continue;
  if (name === "teams") out.endpoints[name].teams = (Array.isArray(r.body) ? r.body : []).map((t) => ({ id: t.id, name: t.name, personal_team: t.personal_team, created_at: t.created_at }));
  if (name === "team_current") out.team = { id: r.body?.id, name: r.body?.name, personal_team: r.body?.personal_team };
  if (name === "members") out.members = (Array.isArray(r.body) ? r.body : []).map((m) => ({ id: m.id, name: m.name, email_masked: masked(m.email ?? ""), two_factor: m.two_factor_confirmed_at ? true : (m.two_factor_confirmed_at === null ? false : null), force_password_reset: m.force_password_reset ?? null, campos: Object.keys(m).sort() }));
  if (name === "security_keys") out.security_keys_count = Array.isArray(r.body) ? r.body.length : null;
  if (name === "resources") out.endpoints[name].resources = (Array.isArray(r.body) ? r.body : []).map((x) => ({ uuid: x.uuid, name: x.name, type: x.type, status: x.status }));
  if (name === "domains") out.endpoints[name].domains = r.body;
}
mkdirSync(join(HERE, "dados"), { recursive: true });
writeFileSync(join(HERE, "dados", "coolify-extra-sanitizado.json"), JSON.stringify(out, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ apps: out.applications.length, dbs: out.databases.length, server: !!out.server, endpoints: Object.fromEntries(Object.entries(out.endpoints).map(([k, v]) => [k, v.status_http])) }));
