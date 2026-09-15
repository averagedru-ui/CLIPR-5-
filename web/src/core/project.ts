import { defaultRegion, regionGridPos, outputNodePos, type Project, type GraphNode } from "./types";

let counter = 0;
export function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}_${counter}`;
}

export function newProject(): Project {
  const out = outputNodePos();
  return {
    name: "Untitled",
    canvas_w: 1080,
    canvas_h: 1920,
    nodes: [
      { id: "source", kind: "source", x: 40, y: 40 },
      { id: "output", kind: "output", x: out.x, y: out.y },
    ],
    wires: [],
  };
}

function regionCount(p: Project): number {
  return p.nodes.filter((n) => n.kind === "region").length;
}

export function addRegion(p: Project): GraphNode {
  const pos = regionGridPos(regionCount(p));
  const n = defaultRegion(nextId("region"), pos.x, pos.y);
  p.nodes.push(n);
  return n;
}

const DB_NAME = "clipr-mobile";
const STORE = "projects";
const TPL_STORE = "templates";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 2);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
      if (!db.objectStoreNames.contains(TPL_STORE)) db.createObjectStore(TPL_STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function saveProjectLocal(key: string, p: Project): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(JSON.stringify(p), key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function loadProjectLocal(key: string): Promise<Project | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).get(key);
    req.onsuccess = () => resolve(req.result ? JSON.parse(req.result) : null);
    req.onerror = () => reject(req.error);
  });
}

export async function listProjectKeys(): Promise<string[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAllKeys();
    req.onsuccess = () => resolve(req.result as string[]);
    req.onerror = () => reject(req.error);
  });
}

export async function saveTemplateLocal(name: string, p: Project): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(TPL_STORE, "readwrite");
    tx.objectStore(TPL_STORE).put(JSON.stringify(p), name);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function loadTemplateLocal(name: string): Promise<Project | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(TPL_STORE, "readonly");
    const req = tx.objectStore(TPL_STORE).get(name);
    req.onsuccess = () => resolve(req.result ? JSON.parse(req.result) : null);
    req.onerror = () => reject(req.error);
  });
}

export async function listLocalTemplateNames(): Promise<string[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(TPL_STORE, "readonly");
    const req = tx.objectStore(TPL_STORE).getAllKeys();
    req.onsuccess = () => resolve(req.result as string[]);
    req.onerror = () => reject(req.error);
  });
}

export async function deleteTemplateLocal(name: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(TPL_STORE, "readwrite");
    tx.objectStore(TPL_STORE).delete(name);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
