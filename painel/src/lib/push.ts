import { getVapidKey, pushSubscribe, pushUnsubscribe } from "./painel";

function urlB64ToUint8Array(b64: string) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buffer = new ArrayBuffer(raw.length);
  const arr = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

export function pushSuportado(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** Detecta iOS + Safari fora do modo standalone (precisa instalar antes do push). */
export function precisaInstalarNoIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  const iOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = (window.navigator as unknown as { standalone?: boolean }).standalone === true
    || window.matchMedia("(display-mode: standalone)").matches;
  return iOS && !standalone;
}

/** Pede permissão, inscreve no push e registra no backend. Retorna a permissão final. */
export async function ativarPush(municipioId: number): Promise<NotificationPermission> {
  if (!pushSuportado()) return "denied";
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return perm;
  try {
    const reg = await navigator.serviceWorker.ready;
    const key = await getVapidKey();
    if (!key) return perm; // VAPID ainda não configurado no servidor
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(key),
    });
    const j = sub.toJSON();
    await pushSubscribe({
      municipio_id: municipioId,
      endpoint: sub.endpoint,
      p256dh: j.keys?.p256dh || "",
      auth: j.keys?.auth || "",
      ua: navigator.userAgent,
    });
  } catch {
    // segue: a permissão foi concedida; a inscrição pode ser refeita depois
  }
  return perm;
}

export async function desativarPush(): Promise<void> {
  if (!pushSuportado()) return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await pushUnsubscribe(sub.endpoint).catch(() => {});
      await sub.unsubscribe().catch(() => {});
    }
  } catch {}
}
