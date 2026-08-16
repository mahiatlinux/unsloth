export const OBJECT_ROUTES = {
  "/api/health": { status: "ok" },
  "/api/auth/status": { initialized: true, requires_password_change: false },
  "/api/settings/hugging-face-token": { token: null },
  "/api/settings/personalization": {},
  "/api/chat/settings": {},
  "/api/inference/status": { loaded: false, checkpoint: null, model_loaded: false },
  "/api/inference/monitor": { enabled: false, entries: [] },
  "/api/export/status": { running: false },
  "/api/providers/registry": { providers: [] },
  "/api/models/list": { models: [] },
  "/api/hub/local": { models: [] },
  "/api/chat/threads": { threads: [], total: 0 },
  "/api/chat/projects": { projects: [] },
  "/api/rag/knowledge-bases": { knowledge_bases: [] },
  "/api/hub/active-downloads": { downloads: [] },
  "/api/hub/datasets/active-downloads": { downloads: [] },
  "/api/hub/hidden-models": { hidden: [] },
  "/api/providers/": { providers: [] },
};

export function stubBody(pathname) {
  if (Object.hasOwn(OBJECT_ROUTES, pathname)) return OBJECT_ROUTES[pathname];
  return [];
}
